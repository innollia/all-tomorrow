"""02B+02C — typed decision validation + materialization (02B-01..06, 02C-01..06)."""

from __future__ import annotations

import pytest

from all_tomorrow.domain.ids import new_event_id, new_goal_id, new_work_id, utc_now
from all_tomorrow.domain.state import GoalRecord, RunStatus, WorkRecord, WorkStatus
from all_tomorrow.domain.outcomes import CompletionEvidence
from all_tomorrow.researcher import (
    Action,
    DecisionMaterializer,
    DecisionValidationError,
    validate_decision,
)
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore, SemanticEvent


def _evt(**kw):
    kw.setdefault("actor", "test"); kw.setdefault("type", "e")
    return SemanticEvent(event_id=new_event_id(), **kw)


def _decide(action, payload, *, evidence=(), known=frozenset(), scope=frozenset(), did="d1"):
    return validate_decision(
        decision_id=did, action=action, summary="s", reason="r",
        evidence_refs=evidence, payload=payload, prompt_version="p1",
        known_evidence_refs=known, owner_scope_refs=scope,
    )


# 02B-02/03: valid NOOP; action/payload mismatch rejected.
def test_02b_noop_and_mismatch() -> None:
    d = _decide("NOOP", {})
    assert d.action == Action.NOOP
    with pytest.raises(DecisionValidationError):
        _decide("NOOP", {"title": "x"})              # NOOP must carry no payload
    with pytest.raises(DecisionValidationError):
        _decide("CREATE_GOAL", {"title": "x"})        # missing objective


# 02B-04: unknown / cross-owner evidence rejected.
def test_02b_evidence_validation() -> None:
    with pytest.raises(DecisionValidationError):
        _decide("CREATE_GOAL", {"title": "t", "objective": "o"}, evidence=("ev9",), known=frozenset())
    with pytest.raises(DecisionValidationError):
        _decide("CREATE_GOAL", {"title": "t", "objective": "o"},
                evidence=("ev1",), known=frozenset({"ev1"}), scope=frozenset({"other"}))


# 02B: forbidden control fields rejected (no blind status/sql/credential copy).
def test_02b_forbidden_payload_keys() -> None:
    with pytest.raises(DecisionValidationError):
        _decide("CREATE_WORK", {"target_goal_id": "g", "title": "t", "objective": "o", "status": "SUCCEEDED"})


# 02C-02: CREATE_GOAL materializes goal + event.
async def test_02c_create_goal() -> None:
    store = InMemoryGoalWorkRunStore()
    m = DecisionMaterializer(store, user_id="u1")
    d = _decide("CREATE_GOAL", {"title": "Ship", "objective": "obj"})
    res = await m.materialize(d)
    assert res.action == Action.CREATE_GOAL and res.goal_id is not None
    assert (await store.get_goal(res.goal_id)).title == "Ship"


# 02C-01: replay same decision → one mutation.
async def test_02c_replay_idempotent() -> None:
    store = InMemoryGoalWorkRunStore()
    m = DecisionMaterializer(store, user_id="u1")
    d = _decide("CREATE_GOAL", {"title": "Ship", "objective": "obj"}, did="dX")
    r1 = await m.materialize(d)
    r2 = await m.materialize(d)
    assert r2.already_applied is True
    assert r1.goal_id == r2.goal_id
    assert len(await store.list_goals(user_id="u1")) == 1


# 02C-02: CREATE_WORK against a live goal.
async def test_02c_create_work() -> None:
    store = InMemoryGoalWorkRunStore()
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    m = DecisionMaterializer(store, user_id="u1")
    d = _decide("CREATE_WORK", {"target_goal_id": str(g.goal_id), "title": "w", "objective": "o"},
                scope=frozenset({str(g.goal_id)}))
    res = await m.materialize(d)
    assert res.work_id is not None
    assert (await store.get_work(res.work_id)).goal_id == g.goal_id


# 02C-03: revise terminal Work → successor (never revive).
async def test_02c_revise_terminal_creates_successor() -> None:
    store = InMemoryGoalWorkRunStore()
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title="w")
    await store.create_work(w, _evt(work_id=w.work_id))
    await store.transition_work_status(w.work_id, WorkStatus.RUNNING, w.revision, _evt(work_id=w.work_id))
    cur = await store.get_work(w.work_id)
    await store.transition_work_status(w.work_id, WorkStatus.SUCCEEDED, cur.revision,
        _evt(work_id=w.work_id), evidence=CompletionEvidence(criterion_ref="c", evaluator_ref="e", evaluator_version="1"))
    m = DecisionMaterializer(store, user_id="u1")
    d = _decide("REVISE_WORK", {"target_work_id": str(w.work_id), "revision_intent": "fix"},
                evidence=("ev1",), known=frozenset({"ev1"}))
    res = await m.materialize(d)
    assert res.work_id is not None and res.work_id != w.work_id  # successor, not revived
    assert len(await store.list_work(g.goal_id)) == 2


# 02C-05: ASK_USER creates a durable question on a non-terminal work.
async def test_02c_ask_user() -> None:
    store = InMemoryGoalWorkRunStore()
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title="w")
    await store.create_work(w, _evt(work_id=w.work_id))
    m = DecisionMaterializer(store, user_id="u1")
    d = _decide("ASK_USER", {"target_work_id": str(w.work_id), "question": "Approve?"})
    res = await m.materialize(d)
    assert res.question_id is not None
    assert (await store.get_question(res.question_id)).prompt == "Approve?"


# 02C-06: proposal candidate does NOT make a production mutation.
async def test_02c_proposal_no_production_mutation() -> None:
    store = InMemoryGoalWorkRunStore()
    m = DecisionMaterializer(store, user_id="u1")
    d = _decide("PROPOSE_IMPROVEMENT",
                {"target_type": "prompt", "target_id": "p1", "candidate_intent": "tune"})
    res = await m.materialize(d)
    assert res.proposal_ref is not None
    # No goal/work created by a proposal.
    assert len(await store.list_goals(user_id="u1")) == 0
    assert m.proposals()[res.proposal_ref]["candidate_intent"] == "tune"
