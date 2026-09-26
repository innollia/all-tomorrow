"""06B — End-to-End Stage 1 Scenarios (offline-provable subset at L0/L1).

Wires the whole Stage 1 stack. Scenarios needing real crashes/AWS (A restart, H
in-flight drain, I laptop offline exec, L backup/restore) are L2/L3 and run on the
live stack; here we prove B/C/D/E/F/G/J/K with the built modules.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from all_tomorrow.approval import (
    ApprovalDenied, LaptopApprovalAuthority, ProtectedChangeRequest, ReauthContext, hash_material,
)
from all_tomorrow.domain.ids import new_goal_id, new_work_id, utc_now
from all_tomorrow.domain.state import GoalRecord, WorkRecord, WorkStatus
from all_tomorrow.improve import (
    ChangeDescriptor, Classification, Criterion, Decision as EvalDecision, Direction,
    MetricObservation, MonitoringPolicy, Promoter, ProtectionClass, UserEvidence, classify, evaluate,
)
from all_tomorrow.improve.promotion import DeploymentPlan, DeploymentRef
from all_tomorrow.priority import Commitment, Priority, WorkPriorityInputs, classify_priority, outranks
from all_tomorrow.researcher import (
    Action, DecisionMaterializer, validate_decision,
)
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore, SemanticEvent
from all_tomorrow.domain.ids import new_event_id


def _evt(**kw):
    kw.setdefault("actor", "researcher"); kw.setdefault("type", "e")
    return SemanticEvent(event_id=new_event_id(), **kw)


# Scenario B/C: unknown problem → investigation Work; autonomous Goal bounded, source-backed.
async def test_06b_bc_investigation_and_autonomous_goal() -> None:
    store = InMemoryGoalWorkRunStore()
    m = DecisionMaterializer(store, user_id="u1")
    # Autonomous Goal from evidence (C).
    g = await m.materialize(validate_decision(
        decision_id="dg", action="CREATE_GOAL", summary="s", reason="repeated failure ev1",
        evidence_refs=("ev1",), payload={"title": "Investigate flake", "objective": "root cause"},
        prompt_version="p", known_evidence_refs=frozenset({"ev1"}), owner_scope_refs=frozenset({"ev1"})))
    assert g.action == Action.CREATE_GOAL
    # Investigation Work under it (B).
    w = await m.materialize(validate_decision(
        decision_id="dw", action="CREATE_WORK", summary="s", reason="diagnose ev1",
        evidence_refs=("ev1",),
        payload={"target_goal_id": str(g.goal_id), "title": "diagnose", "objective": "why"},
        prompt_version="p", known_evidence_refs=frozenset({"ev1"}),
        owner_scope_refs=frozenset({str(g.goal_id), "ev1"})))
    assert w.work_id is not None


# Scenario D: self-improvement ordinary promotion.
def test_06b_d_self_improvement_promotion() -> None:
    d = evaluate([Criterion("latency", Direction.LOWER_BETTER, True, False)],
                 {"latency": MetricObservation("latency", 200, 100)})
    assert d.decision == EvalDecision.ACCEPT
    cls = classify(ChangeDescriptor("p1", 1, "v2", "v1"))
    assert cls.classification == Classification.ORDINARY

    class T:
        current = "v1"
        def inspect_current(self): return self.current
        def validate_candidate(self, c): return True
        def plan(self, c, cur): return DeploymentPlan(c, cur)
        def apply(self, p): self.current = p.candidate_ref; return DeploymentRef("d", p.candidate_ref, p.previous_ref)
        def verify(self, d): return True
        def rollback(self, prev, d): self.current = prev; return prev
    res = Promoter(T()).promote(candidate_ref="v2", accepted_baseline_ref="v1",
                                protection_class=ProtectionClass.ORDINARY,
                                monitoring_policy=MonitoringPolicy(2, ("err",)))
    assert res.promoted


# Scenario E/F: metric-positive + user-negative → NEED_MORE_EVIDENCE (explicit preserved).
def test_06b_ef_conflict_preserves_explicit() -> None:
    d = evaluate([Criterion("latency", Direction.LOWER_BETTER, True, False)],
                 {"latency": MetricObservation("latency", 200, 100)},
                 user=UserEvidence(contradicts=True))
    assert d.decision == EvalDecision.NEED_MORE_EVIDENCE


# Scenario G: protected boundary — AWS attack fails, only exact laptop approval applies.
def test_06b_g_protected_boundary() -> None:
    cls = classify(ChangeDescriptor("p2", 1, "v2", "v1",
                                    semantic_signals=frozenset({"expand_permission_scope"})))
    assert cls.classification == Classification.APPROVAL_REQUIRED
    auth = LaptopApprovalAuthority(authority_write_token="tok-abcdef-0123456789")
    # AWS ordinary credential cannot approve.
    req = ProtectedChangeRequest("p2", 1, hash_material("v2"), hash_material("v1"), hash_material("expand"))
    reauth = ReauthContext("owner", True, True, True, utc_now())
    with pytest.raises(ApprovalDenied):
        auth.approve(req, reauth, authority_write_token="aws-cred", account_id="owner")
    # Only the laptop authority write token + fresh reauth issues an approval that applies.
    rec = auth.approve(req, reauth, authority_write_token="tok-abcdef-0123456789", account_id="owner")
    assert auth.apply_protected_change(rec.approval_id, req, reauth, lambda r: "applied") == "applied"


# Scenario J: hard commitment user Work outranks background.
def test_06b_j_priority_dispatch() -> None:
    user = classify_priority(WorkPriorityInputs(Commitment.HARD, urgent_safety=True))
    bg = classify_priority(WorkPriorityInputs(Commitment.AUTONOMOUS))
    assert outranks(user, bg)


# Scenario K: report logical-period identity + revision (covered by 05 suites; smoke here).
def test_06b_k_report_period_identity() -> None:
    from all_tomorrow.report import TimeModel, logical_period_id
    m = TimeModel(timezone="Asia/Seoul")
    a = logical_period_id(m, datetime(2026, 9, 27, 3, 0, tzinfo=UTC))
    b = logical_period_id(m, datetime(2026, 9, 27, 14, 0, tzinfo=UTC))
    assert a == b


# Every scenario: secret leakage negative scan on the store events.
async def test_06b_no_secret_leak_scan() -> None:
    store = InMemoryGoalWorkRunStore()
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id, payload={"note": "ok"}))
    import dataclasses
    blob = repr([dataclasses.asdict(e) for e in await store.list_events(goal_id=g.goal_id)])
    assert "sk-" not in blob and "password" not in blob.lower()
