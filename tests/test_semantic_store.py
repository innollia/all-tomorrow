"""01B — Goal/Work/Run domain store verification (requirements 01B-01..09).

Runs against the deterministic in-memory reference store always. When the env
var ``AT_SEMANTIC_TEST_URL`` points at a live PostgreSQL with migration 0006
applied, the same suite also runs against ``PostgresGoalWorkRunStore``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from all_tomorrow.domain.errors import (
    InvalidStateTransitionError,
    MissingCompletionEvidenceError,
    TerminalReviveError,
)
from all_tomorrow.domain.ids import (
    ExecutionRef,
    new_event_id,
    new_goal_id,
    new_question_id,
    new_run_id,
    new_work_id,
)
from all_tomorrow.domain.outcomes import CompletionEvidence
from all_tomorrow.domain.state import (
    GoalRecord,
    RunRecord,
    RunStatus,
    WorkRecord,
    WorkStatus,
)
from all_tomorrow.storage.semantic_store import (
    ExecutionRefConflictError,
    InMemoryGoalWorkRunStore,
    PendingQuestionExistsError,
    PostgresGoalWorkRunStore,
    QuestionRecordSemantic,
    SemanticEvent,
    StoreConflictError,
)

_LIVE_URL = os.environ.get("AT_SEMANTIC_TEST_URL")


def _evt(**kwargs) -> SemanticEvent:
    kwargs.setdefault("actor", "test")
    kwargs.setdefault("type", "test.event")
    return SemanticEvent(event_id=new_event_id(), **kwargs)


def _evidence() -> CompletionEvidence:
    return CompletionEvidence(
        criterion_ref="crit:done",
        evaluator_ref="eval:human",
        evaluator_version="1",
    )


async def _fresh_inmemory() -> InMemoryGoalWorkRunStore:
    return InMemoryGoalWorkRunStore()


async def _fresh_postgres() -> PostgresGoalWorkRunStore:
    store = PostgresGoalWorkRunStore(_LIVE_URL)  # type: ignore[arg-type]
    await store.open()
    async with store.pool.connection() as conn:
        for path in sorted(Path("migrations").glob("*.sql")):
            await conn.execute(path.read_text(encoding="utf-8"))
        await conn.execute(
            "TRUNCATE semantic_events, questions_semantic, outcomes, "
            "runs_semantic, work_items, goals RESTART IDENTITY CASCADE"
        )
    return store


_BACKENDS = ["inmemory"] + (["postgres"] if _LIVE_URL else [])


@pytest.fixture(params=_BACKENDS)
async def store(request):
    if request.param == "inmemory":
        yield await _fresh_inmemory()
    else:
        s = await _fresh_postgres()
        try:
            yield s
        finally:
            await s.close()


async def _seed_goal_work(store) -> tuple[GoalRecord, WorkRecord]:
    goal = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="Ship kernel")
    await store.create_goal(goal, _evt(goal_id=goal.goal_id, type="goal.created"))
    work = WorkRecord(work_id=new_work_id(), goal_id=goal.goal_id, title="Build store")
    await store.create_work(work, _evt(work_id=work.work_id, type="work.created"))
    return goal, work


# ---------------------------------------------------------------------------
# 01B-01: backend import 없이 Goal/Work/Run CRUD
# ---------------------------------------------------------------------------
async def test_01b_01_goal_work_run_crud(store) -> None:
    goal, work = await _seed_goal_work(store)

    got_goal = await store.get_goal(goal.goal_id)
    assert got_goal is not None and got_goal.title == "Ship kernel"

    got_work = await store.get_work(work.work_id)
    assert got_work is not None and got_work.goal_id == goal.goal_id

    run = RunRecord(run_id=new_run_id(), work_id=work.work_id)
    await store.create_run(run, _evt(run_id=run.run_id, type="run.created"))
    got_run = await store.get_run(run.run_id)
    assert got_run is not None and got_run.status == RunStatus.STARTING

    assert [g.goal_id for g in await store.list_goals(user_id="u1")] == [goal.goal_id]
    assert [w.work_id for w in await store.list_work(goal.goal_id)] == [work.work_id]
    assert [r.run_id for r in await store.list_runs(work.work_id)] == [run.run_id]


def test_01b_01_domain_pure_no_backend_import() -> None:
    """domain/state.py must not import any external durable backend package."""
    src = Path("src/all_tomorrow/domain/state.py").read_text(encoding="utf-8")
    for banned in ("import dbos", "from dbos", "import restate", "from restate", "psycopg"):
        assert banned not in src, f"domain leaked backend import: {banned}"


# ---------------------------------------------------------------------------
# 01B-02: Work 1:N Run + single active run
# ---------------------------------------------------------------------------
async def test_01b_02_work_has_many_runs_one_active(store) -> None:
    _, work = await _seed_goal_work(store)

    run1 = RunRecord(run_id=new_run_id(), work_id=work.work_id)
    await store.create_run(run1, _evt(run_id=run1.run_id, type="run.created"))

    run2 = RunRecord(run_id=new_run_id(), work_id=work.work_id)
    with pytest.raises(Exception):
        await store.create_run(run2, _evt(run_id=run2.run_id, type="run.created"))

    rev = _rev(store, run1)
    await store.transition_run_status(
        run1.run_id, RunStatus.RUNNING, rev, _evt(run_id=run1.run_id, type="run.running")
    )
    await store.transition_run_status(
        run1.run_id, RunStatus.FAILED, rev + 1, _evt(run_id=run1.run_id, type="run.failed")
    )
    run3 = RunRecord(run_id=new_run_id(), work_id=work.work_id, attempt_number=2)
    await store.create_run(run3, _evt(run_id=run3.run_id, type="run.created"))
    assert len(await store.list_runs(work.work_id)) == 2


# ---------------------------------------------------------------------------
# 01B-03: transition + Event atomic
# ---------------------------------------------------------------------------
async def test_01b_03_transition_appends_event(store) -> None:
    goal, work = await _seed_goal_work(store)
    await store.transition_work_status(
        work.work_id, WorkStatus.RUNNING, work.revision,
        _evt(work_id=work.work_id, type="work.running"),
    )
    events = await store.list_events(work_id=work.work_id)
    types = [e.type for e in events]
    assert "work.created" in types and "work.running" in types


async def test_01b_03_failed_transition_writes_no_event(store) -> None:
    goal, work = await _seed_goal_work(store)
    before = len(await store.list_events(work_id=work.work_id))
    with pytest.raises((InvalidStateTransitionError, MissingCompletionEvidenceError)):
        await store.transition_work_status(
            work.work_id, WorkStatus.SUCCEEDED, work.revision,
            _evt(work_id=work.work_id, type="work.succeeded"), evidence=_evidence(),
        )
    after = len(await store.list_events(work_id=work.work_id))
    assert after == before


# ---------------------------------------------------------------------------
# 01B-04: concurrent revision conflict → no lost update
# ---------------------------------------------------------------------------
async def test_01b_04_concurrent_revision_no_lost_update(store) -> None:
    goal, work = await _seed_goal_work(store)
    await store.transition_work_status(
        work.work_id, WorkStatus.RUNNING, work.revision,
        _evt(work_id=work.work_id, type="work.running"),
    )
    current = await store.get_work(work.work_id)
    rev = current.revision

    async def go(target: WorkStatus):
        return await store.transition_work_status(
            work.work_id, target, rev, _evt(work_id=work.work_id, type=f"work.{target.value}")
        )

    results = await asyncio.gather(
        go(WorkStatus.WAITING), go(WorkStatus.CANCEL_REQUESTED), return_exceptions=True
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    conflicts = [r for r in results if isinstance(r, StoreConflictError)]
    assert len(ok) == 1, "exactly one writer wins the revision"
    assert len(conflicts) == 1, "the loser fails closed with a conflict"


# ---------------------------------------------------------------------------
# 01B-05: ExecutionRef conflicting attach fails closed (CAS)
# ---------------------------------------------------------------------------
async def test_01b_05_execution_ref_cas_conflict(store) -> None:
    _, work = await _seed_goal_work(store)
    run = RunRecord(run_id=new_run_id(), work_id=work.work_id)
    await store.create_run(run, _evt(run_id=run.run_id, type="run.created"))
    rev = _rev(store, run)

    ref_a = ExecutionRef(backend="dbos", execution_id="exec-a")
    ref_b = ExecutionRef(backend="dbos", execution_id="exec-b")

    async def attach(ref):
        return await store.attach_execution_ref(
            run.run_id, rev, ref, _evt(run_id=run.run_id, type="run.attached")
        )

    results = await asyncio.gather(attach(ref_a), attach(ref_b), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    failed = [r for r in results if isinstance(r, (ExecutionRefConflictError, StoreConflictError))]
    assert len(ok) == 1 and len(failed) == 1

    final = await store.get_run(run.run_id)
    assert final.execution_ref is not None
    winner_id = final.execution_ref.execution_id
    assert winner_id in {"exec-a", "exec-b"}
    with pytest.raises(ExecutionRefConflictError):
        other = "exec-b" if winner_id == "exec-a" else "exec-a"
        await store.attach_execution_ref(
            run.run_id, _rev_after(store, run.run_id, final),
            ExecutionRef(backend="dbos", execution_id=other),
            _evt(run_id=run.run_id, type="run.attached"),
        )


# ---------------------------------------------------------------------------
# 01B-06: Work owns no ExecutionRef
# ---------------------------------------------------------------------------
async def test_01b_06_work_cannot_hold_execution_ref() -> None:
    from all_tomorrow.domain.errors import WorkExecutionRefForbiddenError

    with pytest.raises(WorkExecutionRefForbiddenError):
        WorkRecord(
            work_id=new_work_id(), goal_id=new_goal_id(), title="x",
            execution_ref=ExecutionRef(backend="dbos", execution_id="e"),
        )


# ---------------------------------------------------------------------------
# 01B-07: SUCCEEDED without CompletionEvidence is refused
# ---------------------------------------------------------------------------
async def test_01b_07_success_requires_evidence(store) -> None:
    goal, work = await _seed_goal_work(store)
    await store.transition_work_status(
        work.work_id, WorkStatus.RUNNING, work.revision,
        _evt(work_id=work.work_id, type="work.running"),
    )
    cur = await store.get_work(work.work_id)
    with pytest.raises(MissingCompletionEvidenceError):
        await store.transition_work_status(
            work.work_id, WorkStatus.SUCCEEDED, cur.revision,
            _evt(work_id=work.work_id, type="work.succeeded"),
        )
    ok = await store.transition_work_status(
        work.work_id, WorkStatus.SUCCEEDED, cur.revision,
        _evt(work_id=work.work_id, type="work.succeeded"), evidence=_evidence(),
    )
    assert ok.status == WorkStatus.SUCCEEDED


async def test_01b_07_terminal_work_cannot_revive(store) -> None:
    goal, work = await _seed_goal_work(store)
    await store.transition_work_status(
        work.work_id, WorkStatus.RUNNING, work.revision,
        _evt(work_id=work.work_id, type="work.running"),
    )
    cur = await store.get_work(work.work_id)
    done = await store.transition_work_status(
        work.work_id, WorkStatus.SUCCEEDED, cur.revision,
        _evt(work_id=work.work_id, type="work.succeeded"), evidence=_evidence(),
    )
    with pytest.raises(TerminalReviveError):
        await store.transition_work_status(
            work.work_id, WorkStatus.RUNNING, done.revision,
            _evt(work_id=work.work_id, type="work.revive"),
        )


# ---------------------------------------------------------------------------
# 01B-08: events are append-only
# ---------------------------------------------------------------------------
async def test_01b_08_events_append_only(store) -> None:
    goal, work = await _seed_goal_work(store)
    n1 = len(await store.list_events(goal_id=goal.goal_id))
    await store.transition_work_status(
        work.work_id, WorkStatus.RUNNING, work.revision,
        _evt(work_id=work.work_id, type="work.running"),
    )
    n2 = len(await store.list_events())
    assert n2 >= n1 + 1
    assert not hasattr(store, "update_event")
    assert not hasattr(store, "delete_event")


# ---------------------------------------------------------------------------
# 01B-09: Question answer + Delivery signal atomic
# ---------------------------------------------------------------------------
async def test_01b_09_answer_question_atomic_signal(store) -> None:
    _, work = await _seed_goal_work(store)
    q = QuestionRecordSemantic(
        question_id=new_question_id(), prompt="Approve deploy?", work_id=work.work_id
    )
    await store.create_question(q)

    answered = await store.answer_question(
        q.question_id, q.revision, answer_ref="ans:yes", signal_correlation="sig-123"
    )
    assert answered.status == "ANSWERED"
    assert answered.answer_ref == "ans:yes"
    assert answered.signal_correlation == "sig-123"

    with pytest.raises(StoreConflictError):
        await store.answer_question(
            q.question_id, q.revision, answer_ref="ans:no", signal_correlation="sig-x"
        )


async def test_01b_09_one_pending_question_per_work(store) -> None:
    _, work = await _seed_goal_work(store)
    q1 = QuestionRecordSemantic(
        question_id=new_question_id(), prompt="Q1", work_id=work.work_id
    )
    await store.create_question(q1)
    q2 = QuestionRecordSemantic(
        question_id=new_question_id(), prompt="Q2", work_id=work.work_id
    )
    with pytest.raises(PendingQuestionExistsError):
        await store.create_question(q2)


# ---------------------------------------------------------------------------
# revision helpers (RunRecord has no revision field; the store owns it)
# ---------------------------------------------------------------------------
def _rev(store, run: RunRecord) -> int:
    if isinstance(store, InMemoryGoalWorkRunStore):
        return store.run_revision(run.run_id)
    from all_tomorrow.storage.semantic_store import _run_revision
    return _run_revision(run)


def _rev_after(store, run_id, current_run: RunRecord) -> int:
    if isinstance(store, InMemoryGoalWorkRunStore):
        return store.run_revision(run_id)
    from all_tomorrow.storage.semantic_store import _run_revision
    return _run_revision(current_run)
