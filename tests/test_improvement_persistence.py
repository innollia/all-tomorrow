"""03A — Improvement/Evaluation persistence verification (03A-02,03,04 at L0)."""

from __future__ import annotations

import pytest

from all_tomorrow.domain.errors import InvalidStateTransitionError
from all_tomorrow.improve import (
    EvaluationCriteria,
    EvaluationRun,
    ImprovementProposal,
    ImprovementStore,
    ProposalError,
    ProposalStatus,
)


def _proposal() -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id="p1", target_type="prompt", target_id="t1",
        baseline_hash="base-hash", reason="improve", protection_class="ordinary",
    )


def _store() -> tuple[ImprovementStore, ImprovementProposal]:
    s = ImprovementStore()
    p = s.create_proposal(_proposal())
    return s, p


def test_legal_lifecycle() -> None:
    s, p = _store()
    p = s.sandbox_candidate("p1", "cand-hash-1", p.revision)
    assert p.status == ProposalStatus.SANDBOXED and p.candidate_hash == "cand-hash-1"
    p = s.transition("p1", ProposalStatus.EVALUATED, p.revision)
    p = s.transition("p1", ProposalStatus.ACCEPTED, p.revision)
    p = s.transition("p1", ProposalStatus.PROMOTED, p.revision)
    assert p.status == ProposalStatus.PROMOTED


def test_illegal_transition_rejected() -> None:
    s, p = _store()
    with pytest.raises(InvalidStateTransitionError):
        s.transition("p1", ProposalStatus.PROMOTED, p.revision)  # PROPOSED->PROMOTED illegal


# 03A-02: criteria must be frozen BEFORE evaluation (while SANDBOXED).
def test_criteria_frozen_before_evaluation() -> None:
    s, p = _store()
    # Cannot freeze while still PROPOSED.
    crit = EvaluationCriteria("c1", "p1", ("latency",), ("no_regression",), "crit-hash")
    with pytest.raises(ProposalError):
        s.freeze_criteria(crit, p.revision)
    p = s.sandbox_candidate("p1", "cand-hash-1", p.revision)
    frozen = s.freeze_criteria(crit, p.revision)
    assert frozen.content_hash == "crit-hash"
    assert s.get("p1").criteria_ref == "c1"


# 03A-03: candidate hash change invalidates prior evaluation → STALE.
def test_candidate_hash_change_invalidates() -> None:
    s, p = _store()
    p = s.sandbox_candidate("p1", "cand-hash-1", p.revision)
    p = s.transition("p1", ProposalStatus.EVALUATED, p.revision)
    p = s.transition("p1", ProposalStatus.ACCEPTED, p.revision)
    s.record_evaluation(EvaluationRun("e1", "p1", "c1", "base-hash", "cand-hash-1",
                                      "ACCEPT", "ok", "evaluator-1"))
    stale = s.invalidate_if_candidate_changed("p1", "cand-hash-2-CHANGED")
    assert stale.status == ProposalStatus.STALE


def test_evaluation_hash_must_match_candidate() -> None:
    s, p = _store()
    p = s.sandbox_candidate("p1", "cand-hash-1", p.revision)
    with pytest.raises(ProposalError):
        s.record_evaluation(EvaluationRun("e1", "p1", "c1", "base-hash", "WRONG-HASH",
                                          "ACCEPT", "x", "evaluator-1"))
