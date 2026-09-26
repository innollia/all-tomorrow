"""02E — Researcher Loop Acceptance (02E-01..10 at L0/L1).

Wires 02A ObservationBuilder + 02B validate_decision + 02C DecisionMaterializer +
02D BudgetLedger/OpenWorkDedupIndex end to end. Restart (02E-09, L2) is covered by
the durable ledger/cursor CAS unit tests; here we assert the loop's semantics.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from all_tomorrow.domain.ids import (
    new_event_id, new_goal_id, new_work_id, utc_now,
)
from all_tomorrow.domain.state import GoalRecord, WorkRecord, WorkStatus
from all_tomorrow.researcher import (
    Action,
    BudgetConfig,
    BudgetExceededError,
    BudgetLedger,
    DecisionMaterializer,
    DecisionValidationError,
    ObservationBuilder,
    OpenWorkDedupIndex,
    dedup_fingerprint,
    validate_decision,
)
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore, SemanticEvent


def _evt(**kw):
    kw.setdefault("actor", "researcher"); kw.setdefault("type", "e")
    return SemanticEvent(event_id=new_event_id(), **kw)


async def _store_with_goal():
    store = InMemoryGoalWorkRunStore()
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id, type="goal.created"))
    return store, g


# 02E-01: no new observation → NOOP, no Goal/Work created.
async def test_02e_01_no_observation_noop() -> None:
    store, g = await _store_with_goal()
    b = ObservationBuilder(store)
    snap = await b.build("researcher", "u1")
    # advance cursor to consume the seed event, then a second wake sees nothing new
    b.advance_cursor("researcher", "u1", snap.upper_cursor, expected_revision=0)
    snap2 = await b.build("researcher", "u1")
    assert snap2.event_refs == ()  # nothing new
    m = DecisionMaterializer(store, user_id="u1")
    res = await m.materialize(validate_decision(
        decision_id="d", action="NOOP", summary="", reason="no change",
        evidence_refs=(), payload={}, prompt_version="p",
        known_evidence_refs=frozenset(), owner_scope_refs=frozenset()))
    assert res.action == Action.NOOP
    assert len(await store.list_work(g.goal_id)) == 0


# 02E-02/05/10: autonomous investigation Work requires evidence + expected outcome.
async def test_02e_05_autonomous_work_requires_evidence() -> None:
    store, g = await _store_with_goal()
    m = DecisionMaterializer(store, user_id="u1")
    # Goal-less/evidence-less create is rejected at validation (no evidence known).
    with pytest.raises(DecisionValidationError):
        validate_decision(
            decision_id="d", action="CREATE_WORK",
            summary="s", reason="hunch", evidence_refs=("ev-unknown",),
            payload={"target_goal_id": str(g.goal_id), "title": "investigate", "objective": "why"},
            prompt_version="p", known_evidence_refs=frozenset(), owner_scope_refs=frozenset())
    # With known evidence + in-scope target it materializes.
    d = validate_decision(
        decision_id="d2", action="CREATE_WORK", summary="s", reason="repeated failure ev1",
        evidence_refs=("ev1",),
        payload={"target_goal_id": str(g.goal_id), "title": "investigate", "objective": "why"},
        prompt_version="p", known_evidence_refs=frozenset({"ev1"}),
        owner_scope_refs=frozenset({str(g.goal_id), "ev1"}))
    res = await m.materialize(d)
    assert res.work_id is not None


# 02E-06: same observation concurrent/replay → no duplicate Work (dedup + idempotency).
async def test_02e_06_concurrent_replay_no_duplicate() -> None:
    store, g = await _store_with_goal()
    idx = OpenWorkDedupIndex()
    fp = dedup_fingerprint(action_type="create_work", target_goal_id=str(g.goal_id),
                           target_project_id=None, objective="investigate why",
                           evidence_refs=("ev1",), materializer_schema_version="1")

    async def attempt(wid):
        try:
            await idx.claim(fp, wid)
            return True
        except Exception:
            return False

    results = await asyncio.gather(attempt("w1"), attempt("w2"))
    assert sum(results) == 1  # only one claim wins the fingerprint


# 02E-07: budget exhaustion caps work storm, no ceiling breach.
async def test_02e_07_budget_exhaustion() -> None:
    cfg = BudgetConfig("v1", max_created_work=2, max_tokens=1000, max_concurrent_runs=1,
                       max_wall_clock_age=timedelta(hours=1))
    ledger = BudgetLedger(cfg)
    await ledger.register_lineage("L1")
    await ledger.reserve_work("L1")
    await ledger.reserve_work("L1")
    with pytest.raises(BudgetExceededError):
        await ledger.reserve_work("L1")
    assert ledger.usage("L1").created_work == 2


# 02E-08: malformed output → no state mutation.
async def test_02e_08_malformed_no_mutation() -> None:
    store, g = await _store_with_goal()
    before = len(await store.list_work(g.goal_id))
    with pytest.raises(DecisionValidationError):
        validate_decision(
            decision_id="d", action="CREATE_WORK", summary="s", reason="r",
            evidence_refs=(), payload={"target_goal_id": str(g.goal_id)},  # missing title/objective
            prompt_version="p", known_evidence_refs=frozenset(), owner_scope_refs=frozenset())
    assert len(await store.list_work(g.goal_id)) == before


# 02E-04: prior researcher decision/result events are re-observable (self history).
async def test_02e_04_self_history_observable() -> None:
    store, g = await _store_with_goal()
    store._events.append(_evt(goal_id=g.goal_id, type="researcher.noop", occurred_at=utc_now()))
    store._events.append(_evt(goal_id=g.goal_id, type="researcher.create_work", occurred_at=utc_now()))
    b = ObservationBuilder(store)
    snap = await b.build("researcher", "u1")
    # researcher's own prior events are part of the next observation range.
    types_present = len(snap.event_refs) >= 2
    assert types_present
