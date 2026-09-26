"""03F — Evaluation & Self-Improvement Acceptance (wires 03A-03E, L0/L1)."""

from __future__ import annotations

import pytest

from all_tomorrow.improve import (
    ChangeDescriptor,
    Classification,
    Criterion,
    Decision,
    Direction,
    EvaluationCriteria,
    ImprovementProposal,
    ImprovementStore,
    MetricObservation,
    MonitoringPolicy,
    Promoter,
    ProposalStatus,
    ProtectedChangeError,
    ProtectionClass,
    UserEvidence,
    classify,
    evaluate,
)
from all_tomorrow.improve.promotion import DeploymentPlan, DeploymentRef


class _Target:
    def __init__(self, current="v1", verify_ok=True):
        self.current, self.verify_ok, self.rollbacks = current, verify_ok, 0
    def inspect_current(self): return self.current
    def validate_candidate(self, c): return True
    def plan(self, c, cur): return DeploymentPlan(c, cur)
    def apply(self, p): self.current = p.candidate_ref; return DeploymentRef("d", p.candidate_ref, p.previous_ref)
    def verify(self, d): return self.verify_ok
    def rollback(self, prev, d): self.current = prev; self.rollbacks += 1; return prev


_CRIT = [Criterion("latency", Direction.LOWER_BETTER, required=True, is_hard_invariant=False)]
_POLICY = MonitoringPolicy(min_observations=2, hard_rollback_signals=("error_rate",))


# Scenario 1-6: proposal → freeze criteria → sandbox-equivalent → evaluate ACCEPT → promote.
def test_03f_ordinary_accept_and_promote() -> None:
    store = ImprovementStore()
    p = store.create_proposal(ImprovementProposal(
        proposal_id="p1", target_type="prompt", target_id="t1",
        baseline_hash="v1", reason="low utility", protection_class="ordinary"))
    p = store.sandbox_candidate("p1", "v2", p.revision)           # (2) candidate hash set while SANDBOXED
    store.freeze_criteria(EvaluationCriteria("c1", "p1", ("latency",), (), "crit"), store.get("p1").revision)

    # (4) mixed evaluator on real evidence
    d = evaluate(_CRIT, {"latency": MetricObservation("latency", 200, 100)})
    assert d.decision == Decision.ACCEPT

    # (10) classify ordinary
    cls = classify(ChangeDescriptor("p1", store.get("p1").revision, "v2", "v1"))
    assert cls.classification == Classification.ORDINARY

    # (6) promote ordinary prompt
    prom = Promoter(_Target(current="v1")).promote(
        candidate_ref="v2", accepted_baseline_ref="v1",
        protection_class=ProtectionClass.ORDINARY, monitoring_policy=_POLICY)
    assert prom.promoted


# Scenario 8: monitoring hard regression → exact rollback.
def test_03f_verify_regression_rolls_back() -> None:
    t = _Target(current="v1", verify_ok=False)
    prom = Promoter(t).promote(candidate_ref="v2", accepted_baseline_ref="v1",
                               protection_class=ProtectionClass.ORDINARY, monitoring_policy=_POLICY)
    assert not prom.promoted and prom.rolled_back and t.current == "v1"


# Scenario 9: evidence conflict → NEED_MORE_EVIDENCE.
def test_03f_evidence_conflict_needs_more() -> None:
    d = evaluate(_CRIT, {"latency": MetricObservation("latency", 200, 100)},
                 user=UserEvidence(contradicts=True))
    assert d.decision == Decision.NEED_MORE_EVIDENCE


# Scenario 10/11: protected proposal → cannot auto-promote (needs 04E authority).
def test_03f_protected_blocks_auto_apply() -> None:
    cls = classify(ChangeDescriptor("p2", 1, "v2", "v1",
                                    semantic_signals=frozenset({"expand_permission_scope"})))
    assert cls.classification == Classification.APPROVAL_REQUIRED
    with pytest.raises(ProtectedChangeError):
        Promoter(_Target()).promote(candidate_ref="v2", accepted_baseline_ref="v1",
                                    protection_class=ProtectionClass.PROTECTED, monitoring_policy=_POLICY)


# Scenario 5: candidate tampering criteria → evaluator rejects.
def test_03f_candidate_tamper_rejected() -> None:
    d = evaluate(_CRIT, {"latency": MetricObservation("latency", 200, 100)},
                 candidate_tampered_criteria=True)
    assert d.decision == Decision.REJECT


# Scenario 13: candidate hash change after ACCEPT invalidates prior evaluation.
def test_03f_candidate_hash_change_invalidates() -> None:
    store = ImprovementStore()
    p = store.create_proposal(ImprovementProposal(
        proposal_id="p3", target_type="prompt", target_id="t", baseline_hash="v1",
        reason="r", protection_class="ordinary"))
    p = store.sandbox_candidate("p3", "v2", p.revision)
    p = store.transition("p3", ProposalStatus.EVALUATED, p.revision)
    p = store.transition("p3", ProposalStatus.ACCEPTED, p.revision)
    stale = store.invalidate_if_candidate_changed("p3", "v2-CHANGED")
    assert stale.status == ProposalStatus.STALE
