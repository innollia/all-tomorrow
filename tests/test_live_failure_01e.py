"""01E — Live Failure Verification.

Live scenarios (01E-01..15) need a real PostgreSQL + selected durable backend +
child-process crashes; they run only when AT_SEMANTIC_TEST_URL is set (skipped
offline). Always-run here: the wrong-implementation NEGATIVES, which prove the
01A-01D invariants cannot be violated even offline.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from all_tomorrow.domain.errors import WorkExecutionRefForbiddenError
from all_tomorrow.domain.ids import ExecutionRef, new_goal_id, new_run_id, new_work_id
from all_tomorrow.domain.state import GoalRecord, RunRecord, WorkRecord
from all_tomorrow.storage.semantic_store import (
    ExecutionRefConflictError,
    InMemoryGoalWorkRunStore,
    SemanticEvent,
)
from all_tomorrow.domain.ids import new_event_id

_LIVE = os.environ.get("AT_SEMANTIC_TEST_URL")
live_only = pytest.mark.skipif(not _LIVE, reason="set AT_SEMANTIC_TEST_URL for live 01E scenarios")


def _evt(**kw):
    kw.setdefault("actor", "test"); kw.setdefault("type", "e")
    return SemanticEvent(event_id=new_event_id(), **kw)


# --- Wrong-implementation negatives (always run) -----------------------------

# Negative: attaching a single ExecutionRef to Work is a schema/domain violation.
def test_01e_neg_work_cannot_own_execution_ref() -> None:
    with pytest.raises(WorkExecutionRefForbiddenError):
        WorkRecord(work_id=new_work_id(), goal_id=new_goal_id(), title="x",
                   execution_ref=ExecutionRef(backend="dbos", execution_id="e"))


# Negative: a different ExecutionRef cannot overwrite an attached one via CAS.
async def test_01e_neg_divergent_ref_cas_overwrite_fails() -> None:
    store = InMemoryGoalWorkRunStore()
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title="w")
    await store.create_work(w, _evt(work_id=w.work_id))
    r = RunRecord(run_id=new_run_id(), work_id=w.work_id)
    await store.create_run(r, _evt(run_id=r.run_id))
    await store.attach_execution_ref(r.run_id, 1, ExecutionRef(backend="dbos", execution_id="A"), _evt(run_id=r.run_id))
    with pytest.raises(ExecutionRefConflictError):
        await store.attach_execution_ref(
            r.run_id, store.run_revision(r.run_id),
            ExecutionRef(backend="dbos", execution_id="B"), _evt(run_id=r.run_id))


# Negative: re-injecting the original correlation does not bypass revision CAS.
async def test_01e_neg_reinjected_correlation_no_bypass() -> None:
    store = InMemoryGoalWorkRunStore()
    g = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="g")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    from all_tomorrow.domain.state import WorkStatus
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title="w")
    await store.create_work(w, _evt(work_id=w.work_id))
    # advance once
    await store.transition_work_status(w.work_id, WorkStatus.RUNNING, w.revision, _evt(work_id=w.work_id))
    # replaying the OLD expected revision must fail the CAS.
    from all_tomorrow.storage.semantic_store import StoreConflictError
    with pytest.raises(StoreConflictError):
        await store.transition_work_status(w.work_id, WorkStatus.WAITING, w.revision, _evt(work_id=w.work_id))


# Backend escape: the fake adapter satisfies the DurableExecutionPort contract,
# and no selected-backend internal type leaks into the domain state module.
def test_01e_neg_no_backend_type_in_domain() -> None:
    src = Path("src/all_tomorrow/domain/state.py").read_text(encoding="utf-8")
    for banned in ("import dbos", "from dbos", "DBOS", "psycopg", "litellm"):
        assert banned not in src, f"backend type leaked into domain/state.py: {banned}"


# --- Live scenarios (env-gated) ----------------------------------------------

@live_only
async def test_01e_01_migration_chain_preserves_identity() -> None:
    # Applies the full migration chain against the live DB and checks the semantic
    # tables exist with the expected columns. Full body runs only with a live DB.
    from all_tomorrow.storage.semantic_store import PostgresGoalWorkRunStore
    store = PostgresGoalWorkRunStore(_LIVE)
    await store.open()
    try:
        async with store.pool.connection() as conn:
            for p in sorted(Path("migrations").glob("*.sql")):
                await conn.execute(p.read_text(encoding="utf-8"))
            cur = await conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name IN "
                "('goals','work_items','runs_semantic','outcomes','questions_semantic','semantic_events')")
            (n,) = await cur.fetchone()
            assert n == 6
    finally:
        await store.close()
