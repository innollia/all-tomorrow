"""Stage 2.3B — Run/Cancel/Replan verification (S2-23B-01..05)."""

from __future__ import annotations

import pytest

from all_tomorrow.domain.errors import InvariantViolationError, MissingCompletionEvidenceError
from all_tomorrow.domain.ids import new_event_id, new_goal_id, new_work_id
from all_tomorrow.domain.outcomes import CompletionEvidence
from all_tomorrow.domain.state import GoalRecord, RunStatus, WorkRecord, WorkStatus
from all_tomorrow.execution_service import ExecutionService, ReplanBudgetExceededError
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore, SemanticEvent


def _evt(**kw):
    kw.setdefault("actor", "t"); kw.setdefault("type", "e")
    return SemanticEvent(event_id=new_event_id(), **kw)


async def _goal_work(store):
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title="w")
    await store.create_work(w, _evt(work_id=w.work_id))
    return g, w


# S2-23B-01: two active Runs blocked by default.
async def test_23b_01_two_active_runs_blocked() -> None:
    store = InMemoryGoalWorkRunStore()
    _, w = await _goal_work(store)
    svc = ExecutionService(store)
    await svc.start_run(w.work_id)
    with pytest.raises(InvariantViolationError):
        await svc.start_run(w.work_id)


# S2-23B-02: Work success requires CompletionEvidence.
async def test_23b_02_work_success_needs_evidence() -> None:
    store = InMemoryGoalWorkRunStore()
    _, w = await _goal_work(store)
    await store.transition_work_status(w.work_id, WorkStatus.RUNNING, w.revision, _evt(work_id=w.work_id))
    svc = ExecutionService(store)
    cur = await store.get_work(w.work_id)
    with pytest.raises(MissingCompletionEvidenceError):
        await svc.complete_work(w.work_id, cur.revision, evidence=None)  # type: ignore[arg-type]
    ev = CompletionEvidence(criterion_ref="c", evaluator_ref="e", evaluator_version="1")
    done = await svc.complete_work(w.work_id, cur.revision, evidence=ev)
    assert done.status == WorkStatus.SUCCEEDED


# S2-23B-03: replan storm ceiling.
async def test_23b_03_replan_budget() -> None:
    store = InMemoryGoalWorkRunStore()
    _, w = await _goal_work(store)
    svc = ExecutionService(store, max_replans=2)
    r1 = await svc.start_run(w.work_id)
    # terminalize then replan, twice, third replan exceeds budget
    from all_tomorrow.domain.state import RunStatus
    async def terminalize(run):
        rev = store.run_revision(run.run_id)
        await store.transition_run_status(run.run_id, RunStatus.FAILED, rev, _evt(run_id=run.run_id))
    await terminalize(r1)
    r2 = await svc.replan(w.work_id); await terminalize(r2)
    r3 = await svc.replan(w.work_id); await terminalize(r3)
    with pytest.raises(ReplanBudgetExceededError):
        await svc.replan(w.work_id)


# S2-23B-05: Goal cancel propagates to child Work.
async def test_23b_05_goal_cancel_propagation() -> None:
    store = InMemoryGoalWorkRunStore()
    g, w = await _goal_work(store)
    await store.transition_work_status(w.work_id, WorkStatus.RUNNING, w.revision, _evt(work_id=w.work_id))
    svc = ExecutionService(store)
    g_cur = await store.get_goal(g.goal_id)
    summary = await svc.cancel_goal(g.goal_id, g_cur.revision)
    assert str(w.work_id) in summary["cancelled_work"]
    assert (await store.get_work(w.work_id)).status == WorkStatus.CANCEL_REQUESTED
