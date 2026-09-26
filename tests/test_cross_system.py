"""Stage 2.4C — Fallback & cross-system mutation verification (S2-24C-01..04)."""

from __future__ import annotations

import pytest

from all_tomorrow.domain.errors import ErrorCategory
from all_tomorrow.cross_system import (
    AmbiguousEffectError,
    CompensationSpec,
    CrossSystemError,
    CrossSystemMutator,
    FallbackAction,
    SourceMutation,
    VersionConflictError,
    decide_fallback,
)


# S2-24C-01: resource unavailable → new Run fallback.
def test_24c_01_unavailable_new_run() -> None:
    assert decide_fallback(ErrorCategory.UNAVAILABLE) == FallbackAction.NEW_RUN_FALLBACK
    assert decide_fallback(ErrorCategory.TIMEOUT) == FallbackAction.SAME_RUN_RECOVERY


# S2-24C-02: ambiguous mutation → no blind fallback (must reconcile).
def test_24c_02_ambiguous_no_blind_fallback() -> None:
    assert decide_fallback(ErrorCategory.AMBIGUOUS_EFFECT) == FallbackAction.RECONCILE_FIRST
    m = CrossSystemMutator()
    with pytest.raises(AmbiguousEffectError):
        m.fallback_on_ambiguous_must_reconcile(ErrorCategory.AMBIGUOUS_EFFECT)


# S2-24C-03: source owner optimistic version conflict fails closed.
def test_24c_03_version_conflict() -> None:
    m = CrossSystemMutator()
    m.grant("owner")
    m.seed("doc1", "v1")
    ok = m.apply(SourceMutation("doc1", "v1", "owner", "h1"), new_version="v2", result_hash="rh1")
    assert ok.new_version == "v2"
    # a stale expected version now conflicts
    with pytest.raises(VersionConflictError):
        m.apply(SourceMutation("doc1", "v1", "owner", "h2"), new_version="v3", result_hash="rh2")


def test_24c_unauthorized_rejected() -> None:
    m = CrossSystemMutator()
    m.seed("doc1", "v1")
    with pytest.raises(CrossSystemError):
        m.apply(SourceMutation("doc1", "v1", "stranger", "h"), new_version="v2", result_hash="r")


# S2-24C-04: compensation is a new authorized mutation with its own provenance.
def test_24c_04_compensation_new_authorized_mutation() -> None:
    m = CrossSystemMutator()
    m.grant("owner")
    m.seed("doc1", "v1")
    m.apply(SourceMutation("doc1", "v1", "owner", "h1"), new_version="v2", result_hash="rh1")
    comp = m.compensate(
        CompensationSpec(target_source_id="doc1", reason="revert", authority="owner", payload_hash="hc"),
        new_version="v3", result_hash="rh-comp")
    assert comp.new_version == "v3"          # forward mutation, not a silent undo
    # unauthorized compensation is refused
    with pytest.raises(CrossSystemError):
        m.compensate(CompensationSpec("doc1", "revert", "stranger", "h"),
                     new_version="v4", result_hash="r")
