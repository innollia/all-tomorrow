"""04F — Artifact Store & Integrity verification (S1-04F-01..06)."""

from __future__ import annotations

from pathlib import Path

import pytest

from all_tomorrow.domain.artifacts import ArtifactRef, RetentionClass, compute_content_hash
from all_tomorrow.storage.artifact_store import (
    ArtifactAccessDeniedError,
    ArtifactIntegrityError,
    ArtifactSubstitutionError,
    FinalizingArtifactStore,
)


async def _store(tmp_path: Path) -> FinalizingArtifactStore:
    return FinalizingArtifactStore(tmp_path / "artifacts")


# S1-04F-01: immutable content hash; finalize is content-addressed & idempotent
async def test_04f_01_content_hash_immutable_and_idempotent(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    staged = await store.stage(b"hello world")
    assert staged.content_hash == compute_content_hash(b"hello world")
    ref1 = await store.finalize(staged, owner_id="u1")
    # Finalizing the same content again lands on the same object (idempotent).
    staged2 = await store.stage(b"hello world")
    ref2 = await store.finalize(staged2, owner_id="u1")
    assert ref1.content_hash == ref2.content_hash
    assert await store.retrieve(ref1, requester_id="u1") == b"hello world"


# S1-04F-02: user/project access enforcement
async def test_04f_02_access_enforcement(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    ref = await store.finalize(await store.stage(b"secret"), owner_id="alice")
    assert await store.retrieve(ref, requester_id="alice") == b"secret"
    with pytest.raises(ArtifactAccessDeniedError):
        await store.retrieve(ref, requester_id="bob")


# S1-04F-03: orphan GC removes staged-but-never-finalized uploads
async def test_04f_03_orphan_gc(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    staged = await store.stage(b"orphan")
    assert Path(staged.staging_path).exists()
    removed = await store.gc_orphans()
    assert staged.staging_id in removed
    assert not Path(staged.staging_path).exists()
    # A finalized artifact is NOT an orphan and survives GC.
    ref = await store.finalize(await store.stage(b"keep"), owner_id="u1")
    await store.gc_orphans()
    assert await store.retrieve(ref, requester_id="u1") == b"keep"


# S1-04F-04: retention class carried on the ref (drives purge policy)
async def test_04f_04_retention_class_recorded(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    ref = await store.finalize(
        await store.stage(b"x"), owner_id="u1", retention_class=RetentionClass.EXTENDED
    )
    assert ref.retention_class == RetentionClass.EXTENDED


# S1-04F-05: substitution prevention — finalize with wrong expected_hash fails closed
async def test_04f_05_substitution_prevented(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    staged = await store.stage(b"approved-artifact")
    with pytest.raises(ArtifactSubstitutionError):
        await store.finalize(staged, expected_hash=compute_content_hash(b"malicious-swap"))


async def test_04f_05_missing_bytes_is_integrity_failure(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    ref = await store.finalize(await store.stage(b"data"), owner_id="u1")
    # Simulate bytes lost under the metadata → REPAIR_REQUIRED integrity failure.
    Path(store._object_path(ref.content_hash)).unlink()
    with pytest.raises(ArtifactIntegrityError):
        await store.retrieve(ref, requester_id="u1")


# S1-04F-06: oversized raw data lives behind a ref, not inline in the journal/Event
async def test_04f_06_ref_is_small_not_raw_payload(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    big = b"A" * 5_000_000
    ref = await store.finalize(await store.stage(big), owner_id="u1")
    # The ArtifactRef carries only a hash + locator, never the bytes.
    import dataclasses
    ref_dict = dataclasses.asdict(ref)
    serialized = repr(ref_dict)
    assert big.decode() not in serialized
    assert ref.size_bytes == len(big)
    assert len(ref.content_hash) == 64
