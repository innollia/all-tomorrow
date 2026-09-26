from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from all_tomorrow.domain.artifacts import ArtifactRef, RetentionClass, compute_content_hash
from all_tomorrow.domain.errors import CanonicalError, ErrorCategory
from all_tomorrow.domain.ids import ArtifactId, new_artifact_id


class ArtifactIntegrityError(Exception):
    """Raised when artifact content does not match its expected content_hash."""


class ArtifactAccessDeniedError(Exception):
    """Raised when a caller may not read/finalize an artifact it does not own."""


class ArtifactSubstitutionError(Exception):
    """Raised when a finalize's observed hash differs from the expected hash."""


class ArtifactStoreProtocol(Protocol):
    """Protocol for storing and retrieving immutable artifacts."""

    async def store(
        self,
        content: bytes | str,
        media_type: str = "application/octet-stream",
        owner_id: str = "system",
    ) -> ArtifactRef:
        ...

    async def retrieve(self, ref: ArtifactRef) -> bytes:
        ...


class LocalArtifactStore:
    """Local filesystem implementation of immutable artifact storage."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def store(
        self,
        content: bytes | str,
        media_type: str = "application/octet-stream",
        owner_id: str = "system",
    ) -> ArtifactRef:
        data = content.encode("utf-8") if isinstance(content, str) else content
        digest = compute_content_hash(data)
        art_id = new_artifact_id()
        file_path = self.base_dir / f"{digest}.dat"
        if not file_path.exists():
            file_path.write_bytes(data)

        return ArtifactRef(
            artifact_id=art_id,
            content_hash=digest,
            size_bytes=len(data),
            media_type=media_type,
            storage_locator=str(file_path.resolve()),
            owner_id=owner_id,
        )

    async def retrieve(self, ref: ArtifactRef) -> bytes:
        file_path = Path(ref.storage_locator)
        if not file_path.exists():
            # Try finding by hash in base_dir
            file_path = self.base_dir / f"{ref.content_hash}.dat"
            if not file_path.exists():
                raise FileNotFoundError(f"Artifact {ref.artifact_id} not found at {ref.storage_locator}")

        data = file_path.read_bytes()
        actual_hash = compute_content_hash(data)
        if actual_hash != ref.content_hash:
            raise ArtifactIntegrityError(
                f"Artifact hash mismatch: expected {ref.content_hash}, got {actual_hash}"
            )
        return data


@dataclass(frozen=True, slots=True)
class StagedUpload:
    """A temporary, not-yet-finalized upload. Orphaned if never finalized."""
    staging_id: str
    staging_path: str
    content_hash: str
    size_bytes: int


class FinalizingArtifactStore:
    """04F: temporary upload → hash → atomic finalize → metadata ref transaction.

    Lifecycle:
      stage(content)      → StagedUpload written to a temp path (orphan candidate)
      finalize(staged, …) → atomic rename into content-addressed store, returns ref
      retrieve(ref, …)    → integrity-checked read, access-enforced
      gc_orphans()        → remove staged uploads never finalized
      verify(ref)         → integrity check; missing/altered bytes → integrity error

    Content addressing (content_hash) makes finalize idempotent and blocks
    substitution: finalizing with an expected_hash that differs from the observed
    hash fails closed (04F-05).
    """

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.objects_dir = self.base_dir / "objects"
        self.staging_dir = self.base_dir / "staging"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def _object_path(self, content_hash: str) -> Path:
        return self.objects_dir / f"{content_hash}.dat"

    async def stage(self, content: bytes | str) -> StagedUpload:
        data = content.encode("utf-8") if isinstance(content, str) else content
        digest = compute_content_hash(data)
        staging_id = uuid.uuid4().hex
        staging_path = self.staging_dir / f"{staging_id}.part"
        staging_path.write_bytes(data)
        return StagedUpload(
            staging_id=staging_id,
            staging_path=str(staging_path),
            content_hash=digest,
            size_bytes=len(data),
        )

    async def finalize(
        self,
        staged: StagedUpload,
        *,
        media_type: str = "application/octet-stream",
        owner_id: str = "system",
        retention_class: RetentionClass = RetentionClass.STANDARD,
        expected_hash: str | None = None,
    ) -> ArtifactRef:
        staging_path = Path(staged.staging_path)
        if not staging_path.exists():
            raise ArtifactIntegrityError(f"staged upload {staged.staging_id} missing")

        data = staging_path.read_bytes()
        observed = compute_content_hash(data)
        # Substitution guard: staged bytes must match the hash recorded at stage(),
        # and any caller-declared expected_hash (04F-05).
        if observed != staged.content_hash:
            staging_path.unlink(missing_ok=True)
            raise ArtifactSubstitutionError(
                f"staged bytes changed under {staged.staging_id}: {observed} != {staged.content_hash}"
            )
        if expected_hash is not None and observed != expected_hash:
            staging_path.unlink(missing_ok=True)
            raise ArtifactSubstitutionError(
                f"finalize hash mismatch: expected {expected_hash}, observed {observed}"
            )

        dest = self._object_path(observed)
        if not dest.exists():
            # Atomic finalize: os.replace is atomic on the same filesystem.
            os.replace(str(staging_path), str(dest))
        else:
            # Content already present (idempotent): drop the duplicate staging file.
            staging_path.unlink(missing_ok=True)

        return ArtifactRef(
            artifact_id=new_artifact_id(),
            content_hash=observed,
            size_bytes=len(data),
            media_type=media_type,
            storage_locator=str(dest.resolve()),
            owner_id=owner_id,
            retention_class=retention_class,
        )

    async def retrieve(self, ref: ArtifactRef, *, requester_id: str | None = None) -> bytes:
        # Access enforcement (04F-02): a non-system requester must own the ref.
        if requester_id is not None and ref.owner_id != "system" and requester_id != ref.owner_id:
            raise ArtifactAccessDeniedError(
                f"requester {requester_id} may not read artifact owned by {ref.owner_id}"
            )
        path = self._object_path(ref.content_hash)
        if not path.exists():
            # Metadata present, bytes missing → integrity failure (REPAIR_REQUIRED).
            raise ArtifactIntegrityError(
                f"artifact bytes missing for {ref.artifact_id} ({ref.content_hash}); REPAIR_REQUIRED"
            )
        data = path.read_bytes()
        actual = compute_content_hash(data)
        if actual != ref.content_hash:
            raise ArtifactIntegrityError(
                f"artifact hash mismatch for {ref.artifact_id}: expected {ref.content_hash}, got {actual}"
            )
        return data

    async def verify(self, ref: ArtifactRef) -> bool:
        """Return True if bytes exist and hash matches; raise on integrity failure."""
        await self.retrieve(ref)  # raises ArtifactIntegrityError on any problem
        return True

    async def gc_orphans(self) -> list[str]:
        """Remove staged uploads that were never finalized. Returns removed ids."""
        removed: list[str] = []
        for part in self.staging_dir.glob("*.part"):
            part.unlink(missing_ok=True)
            removed.append(part.stem)
        return removed
