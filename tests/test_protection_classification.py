"""03E — Protection classification & handoff verification (03E-01..05)."""

from __future__ import annotations

import pytest

from all_tomorrow.improve.protection import (
    ChangeDescriptor,
    Classification,
    build_handoff,
    classify,
    handoff_valid,
)


def _change(**kw) -> ChangeDescriptor:
    base = dict(proposal_id="p1", proposal_revision=1, candidate_hash="ch1", baseline_hash="bh1")
    base.update(kw)
    return ChangeDescriptor(**base)


# 03E-01: known authority expansion is protected.
def test_03e_01_authority_expansion_protected() -> None:
    r = classify(_change(semantic_signals=frozenset({"expand_permission_scope"})))
    assert r.classification == Classification.APPROVAL_REQUIRED
    assert any("authority expansion" in x for x in r.protected_reasons)


# 03E-02: unknown detector result is protected (fail-closed).
def test_03e_02_unknown_detector_protected() -> None:
    r = classify(_change(detector_confident=False))
    assert r.classification == Classification.APPROVAL_REQUIRED


# 03E-03: a mechanical touch protects even if semantics look ordinary.
def test_03e_03_mechanical_overrides_ordinary() -> None:
    r = classify(_change(touched_surfaces=frozenset({"approval_authority"})))
    assert r.classification == Classification.APPROVAL_REQUIRED


# 03E-04: changing the classifier/policy itself is protected.
def test_03e_04_classifier_change_protected() -> None:
    r = classify(_change(changes_classifier_or_policy=True))
    assert r.classification == Classification.APPROVAL_REQUIRED


def test_03e_ordinary_passes() -> None:
    r = classify(_change())
    assert r.classification == Classification.ORDINARY
    assert r.protected_reasons == ()


# 03E-05: handoff invalid when candidate/proposal changes.
def test_03e_05_handoff_invalidated_on_drift() -> None:
    ch = _change(semantic_signals=frozenset({"weaken_audit"}))
    res = classify(ch)
    pkg = build_handoff(ch, res, requested_boundary_change="weaken audit retention",
                        nonce="n1", expires_at="2099-01-01T00:00:00Z")
    assert handoff_valid(pkg, current_candidate_hash="ch1", current_proposal_revision=1)
    # candidate changed → invalid
    assert not handoff_valid(pkg, current_candidate_hash="ch2", current_proposal_revision=1)
    # proposal revised → invalid
    assert not handoff_valid(pkg, current_candidate_hash="ch1", current_proposal_revision=2)


def test_03e_handoff_only_for_protected() -> None:
    ch = _change()
    res = classify(ch)  # ORDINARY
    with pytest.raises(ValueError):
        build_handoff(ch, res, requested_boundary_change="", nonce="n", expires_at="z")
