"""01B — Goal/Work/Run semantic domain store.

Persists Goal/Work/Run semantic state and provenance independent of any
external durable execution engine, per docs/roadmap/domain-contracts.md and
migration 0006_semantic_kernel.sql.

Two interchangeable implementations behind ``GoalWorkRunStore``:

- ``InMemoryGoalWorkRunStore``: deterministic reference implementation used to
  prove invariants (optimistic revision CAS, ExecutionRef compare-and-set,
  transition+Event atomicity, Question answer atomicity) without a live DB.
- ``PostgresGoalWorkRunStore``: the real store, SQL matching migration 0006.

CRITICAL invariants enforced here (mirrors domain/state.py + the migration):

- Work never owns an ExecutionRef; only Run does.
- Work 1:N Run, at most one active Run per Work.
- A semantic transition and its provenance Event commit atomically.
- Optimistic revision conflicts fail closed (no lost update).
- Attaching a conflicting ExecutionRef to a Run fails closed (compare-and-set).
- Work/Goal SUCCEEDED requires verified CompletionEvidence.
- Answering a Question and signalling its Delivery intent commit atomically.
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from all_tomorrow.domain.errors import (
    DomainError,
    InvariantViolationError,
)
from all_tomorrow.domain.ids import (
    EventId,
    ExecutionRef,
    GoalId,
    QuestionId,
    RunId,
    WorkId,
    new_event_id,
    utc_now,
)
from all_tomorrow.domain.outcomes import CompletionEvidence, OutcomeRecord
from all_tomorrow.domain.state import (
    GoalRecord,
    GoalStatus,
    RunRecord,
    RunStatus,
    WorkRecord,
    WorkStatus,
    assert_active_runs_invariant,
    transition_goal,
    transition_run,
    transition_work,
)


class StoreConflictError(DomainError):
    """Optimistic concurrency / expected-revision mismatch. Fail closed."""


class NotFoundError(DomainError):
    """Requested entity does not exist."""


class ExecutionRefConflictError(InvariantViolationError):
    """A different ExecutionRef is already attached to the Run (CAS fail closed)."""


class PendingQuestionExistsError(InvariantViolationError):
    """A Work already has a PENDING question (one_pending_question_per_work)."""


# ---------------------------------------------------------------------------
# Provenance Event (append-only)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SemanticEvent:
    """Append-only provenance record for Goal/Work/Run transitions."""

    event_id: EventId
    actor: str
    type: str
    occurred_at: datetime = field(default_factory=utc_now)
    goal_id: GoalId | None = None
    work_id: WorkId | None = None
    run_id: RunId | None = None
    trace_id: str | None = None
    external_ref: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.actor or not self.actor.strip():
            raise ValueError("SemanticEvent.actor must be non-empty")
        if not self.type or not self.type.strip():
            raise ValueError("SemanticEvent.type must be non-empty")


@dataclass(frozen=True, slots=True)
class QuestionRecordSemantic:
    """Canonical Question lifecycle projection (questions_semantic)."""

    question_id: QuestionId
    prompt: str
    status: str = "PENDING"  # PENDING/ANSWERED/SUPERSEDED/CANCELLED/EXPIRED
    work_id: WorkId | None = None
    run_id: RunId | None = None
    answer_ref: str | None = None
    signal_correlation: str | None = None
    revision: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    answered_at: datetime | None = None


_QUESTION_ACTIVE = "PENDING"


# ---------------------------------------------------------------------------
# Store protocol
# ---------------------------------------------------------------------------
@runtime_checkable
class GoalWorkRunStore(Protocol):
    # Goal
    async def create_goal(self, goal: GoalRecord, event: SemanticEvent) -> GoalRecord: ...
    async def get_goal(self, goal_id: GoalId) -> GoalRecord | None: ...
    async def list_goals(self, *, user_id: str | None = None) -> list[GoalRecord]: ...
    async def transition_goal_status(
        self,
        goal_id: GoalId,
        target: GoalStatus,
        expected_revision: int,
        event: SemanticEvent,
        *,
        evidence: CompletionEvidence | OutcomeRecord | None = None,
    ) -> GoalRecord: ...

    # Work
    async def create_work(self, work: WorkRecord, event: SemanticEvent) -> WorkRecord: ...
    async def get_work(self, work_id: WorkId) -> WorkRecord | None: ...
    async def list_work(self, goal_id: GoalId) -> list[WorkRecord]: ...
    async def transition_work_status(
        self,
        work_id: WorkId,
        target: WorkStatus,
        expected_revision: int,
        event: SemanticEvent,
        *,
        evidence: CompletionEvidence | OutcomeRecord | None = None,
    ) -> WorkRecord: ...

    # Run
    async def create_run(self, run: RunRecord, event: SemanticEvent) -> RunRecord: ...
    async def get_run(self, run_id: RunId) -> RunRecord | None: ...
    async def list_runs(self, work_id: WorkId) -> list[RunRecord]: ...
    async def attach_execution_ref(
        self, run_id: RunId, expected_revision: int, ref: ExecutionRef, event: SemanticEvent
    ) -> RunRecord: ...
    async def transition_run_status(
        self,
        run_id: RunId,
        target: RunStatus,
        expected_revision: int,
        event: SemanticEvent,
        *,
        execution_ref: ExecutionRef | None = None,
    ) -> RunRecord: ...
    async def find_reconciliation_candidates(self) -> list[RunRecord]: ...

    # Events / Outcomes
    async def list_events(
        self,
        *,
        goal_id: GoalId | None = None,
        work_id: WorkId | None = None,
        run_id: RunId | None = None,
    ) -> list[SemanticEvent]: ...

    # Questions
    async def create_question(self, question: QuestionRecordSemantic) -> QuestionRecordSemantic: ...
    async def get_question(self, question_id: QuestionId) -> QuestionRecordSemantic | None: ...
    async def answer_question(
        self,
        question_id: QuestionId,
        expected_revision: int,
        answer_ref: str,
        signal_correlation: str,
    ) -> QuestionRecordSemantic: ...


# ---------------------------------------------------------------------------
# In-memory reference implementation
# ---------------------------------------------------------------------------
class InMemoryGoalWorkRunStore:
    """Deterministic reference store used to prove invariants in tests.

    Uses a single asyncio lock so each store operation is atomic: a transition
    and its Event append, or a Question answer and its Delivery signal, either
    both apply or neither does.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._goals: dict[GoalId, GoalRecord] = {}
        self._work: dict[WorkId, WorkRecord] = {}
        self._runs: dict[RunId, RunRecord] = {}
        # RunRecord (domain) has no revision field; the store owns Run revisions.
        self._run_revisions: dict[RunId, int] = {}
        self._events: list[SemanticEvent] = []
        self._questions: dict[QuestionId, QuestionRecordSemantic] = {}
        self._delivery_signals: list[dict[str, Any]] = []

    def run_revision(self, run_id: RunId) -> int:
        """Current stored revision for a Run (1 at creation)."""
        return self._run_revisions.get(run_id, 1)

    # -- Goal ---------------------------------------------------------------
    async def create_goal(self, goal: GoalRecord, event: SemanticEvent) -> GoalRecord:
        async with self._lock:
            if goal.goal_id in self._goals:
                raise StoreConflictError(f"goal already exists: {goal.goal_id}")
            self._goals[goal.goal_id] = goal
            self._events.append(event)
            return goal

    async def get_goal(self, goal_id: GoalId) -> GoalRecord | None:
        return self._goals.get(goal_id)

    async def list_goals(self, *, user_id: str | None = None) -> list[GoalRecord]:
        goals = list(self._goals.values())
        if user_id is not None:
            goals = [g for g in goals if g.user_id == user_id]
        return goals

    async def transition_goal_status(
        self,
        goal_id: GoalId,
        target: GoalStatus,
        expected_revision: int,
        event: SemanticEvent,
        *,
        evidence: CompletionEvidence | OutcomeRecord | None = None,
    ) -> GoalRecord:
        async with self._lock:
            current = self._goals.get(goal_id)
            if current is None:
                raise NotFoundError(f"goal not found: {goal_id}")
            _check_revision(current.revision, expected_revision, "goal", goal_id)
            updated = transition_goal(current, target, evidence)  # raises on illegal/terminal
            self._goals[goal_id] = updated
            self._events.append(event)
            return updated

    # -- Work ---------------------------------------------------------------
    async def create_work(self, work: WorkRecord, event: SemanticEvent) -> WorkRecord:
        async with self._lock:
            if work.work_id in self._work:
                raise StoreConflictError(f"work already exists: {work.work_id}")
            if work.goal_id not in self._goals:
                raise NotFoundError(f"goal not found for work: {work.goal_id}")
            self._work[work.work_id] = work
            self._events.append(event)
            return work

    async def get_work(self, work_id: WorkId) -> WorkRecord | None:
        return self._work.get(work_id)

    async def list_work(self, goal_id: GoalId) -> list[WorkRecord]:
        return [w for w in self._work.values() if w.goal_id == goal_id]

    async def transition_work_status(
        self,
        work_id: WorkId,
        target: WorkStatus,
        expected_revision: int,
        event: SemanticEvent,
        *,
        evidence: CompletionEvidence | OutcomeRecord | None = None,
    ) -> WorkRecord:
        async with self._lock:
            current = self._work.get(work_id)
            if current is None:
                raise NotFoundError(f"work not found: {work_id}")
            _check_revision(current.revision, expected_revision, "work", work_id)
            updated = transition_work(current, target, evidence)
            self._work[work_id] = updated
            self._events.append(event)
            return updated

    # -- Run ----------------------------------------------------------------
    async def create_run(self, run: RunRecord, event: SemanticEvent) -> RunRecord:
        async with self._lock:
            if run.run_id in self._runs:
                raise StoreConflictError(f"run already exists: {run.run_id}")
            if run.work_id not in self._work:
                raise NotFoundError(f"work not found for run: {run.work_id}")
            # Work 1:N Run + at most one active Run per Work.
            existing = [r for r in self._runs.values() if r.work_id == run.work_id]
            assert_active_runs_invariant([*existing, run], max_active=1)
            self._runs[run.run_id] = run
            self._run_revisions[run.run_id] = 1
            self._events.append(event)
            return run

    async def get_run(self, run_id: RunId) -> RunRecord | None:
        return self._runs.get(run_id)

    async def list_runs(self, work_id: WorkId) -> list[RunRecord]:
        return [r for r in self._runs.values() if r.work_id == work_id]

    async def attach_execution_ref(
        self, run_id: RunId, expected_revision: int, ref: ExecutionRef, event: SemanticEvent
    ) -> RunRecord:
        async with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                raise NotFoundError(f"run not found: {run_id}")
            _check_revision(self._run_revisions[run_id], expected_revision, "run", run_id)
            # Compare-and-set: never overwrite a different ref.
            if current.execution_ref is not None:
                if _same_ref(current.execution_ref, ref):
                    return current  # idempotent re-attach
                raise ExecutionRefConflictError(
                    f"run {run_id} already has a different ExecutionRef "
                    f"({current.execution_ref.backend}:{current.execution_ref.execution_id})"
                )
            updated = RunRecord(
                run_id=current.run_id,
                work_id=current.work_id,
                status=current.status,
                attempt_number=current.attempt_number,
                execution_ref=ref,
                created_at=current.created_at,
                updated_at=utc_now(),
                terminal_at=current.terminal_at,
            )
            self._runs[run_id] = updated
            self._run_revisions[run_id] = expected_revision + 1
            self._events.append(event)
            return updated

    async def transition_run_status(
        self,
        run_id: RunId,
        target: RunStatus,
        expected_revision: int,
        event: SemanticEvent,
        *,
        execution_ref: ExecutionRef | None = None,
    ) -> RunRecord:
        async with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                raise NotFoundError(f"run not found: {run_id}")
            _check_revision(self._run_revisions[run_id], expected_revision, "run", run_id)
            updated = transition_run(current, target, execution_ref)
            self._runs[run_id] = updated
            self._run_revisions[run_id] = expected_revision + 1
            self._events.append(event)
            return updated

    async def find_reconciliation_candidates(self) -> list[RunRecord]:
        # STARTING runs with no attached ExecutionRef need reconciliation.
        return [
            r
            for r in self._runs.values()
            if r.status == RunStatus.STARTING and r.execution_ref is None
        ]

    # -- Events -------------------------------------------------------------
    async def list_events(
        self,
        *,
        goal_id: GoalId | None = None,
        work_id: WorkId | None = None,
        run_id: RunId | None = None,
    ) -> list[SemanticEvent]:
        events = list(self._events)
        if goal_id is not None:
            events = [e for e in events if e.goal_id == goal_id]
        if work_id is not None:
            events = [e for e in events if e.work_id == work_id]
        if run_id is not None:
            events = [e for e in events if e.run_id == run_id]
        return events

    # -- Questions ----------------------------------------------------------
    async def create_question(self, question: QuestionRecordSemantic) -> QuestionRecordSemantic:
        async with self._lock:
            if question.question_id in self._questions:
                raise StoreConflictError(f"question already exists: {question.question_id}")
            if question.status == _QUESTION_ACTIVE and question.work_id is not None:
                clash = any(
                    q.work_id == question.work_id and q.status == _QUESTION_ACTIVE
                    for q in self._questions.values()
                )
                if clash:
                    raise PendingQuestionExistsError(
                        f"work {question.work_id} already has a PENDING question"
                    )
            self._questions[question.question_id] = question
            return question

    async def get_question(self, question_id: QuestionId) -> QuestionRecordSemantic | None:
        return self._questions.get(question_id)

    async def answer_question(
        self,
        question_id: QuestionId,
        expected_revision: int,
        answer_ref: str,
        signal_correlation: str,
    ) -> QuestionRecordSemantic:
        async with self._lock:
            current = self._questions.get(question_id)
            if current is None:
                raise NotFoundError(f"question not found: {question_id}")
            _check_revision(current.revision, expected_revision, "question", question_id)
            if current.status != _QUESTION_ACTIVE:
                raise StoreConflictError(
                    f"question {question_id} is not PENDING (status={current.status})"
                )
            now = utc_now()
            updated = QuestionRecordSemantic(
                question_id=current.question_id,
                prompt=current.prompt,
                status="ANSWERED",
                work_id=current.work_id,
                run_id=current.run_id,
                answer_ref=answer_ref,
                signal_correlation=signal_correlation,
                revision=current.revision + 1,
                created_at=current.created_at,
                updated_at=now,
                answered_at=now,
            )
            # Atomic: the answer AND the delivery signal land together.
            self._questions[question_id] = updated
            self._delivery_signals.append(
                {"question_id": question_id, "signal_correlation": signal_correlation}
            )
            return updated

    # test/introspection helper (not part of the protocol)
    def delivery_signals(self) -> list[dict[str, Any]]:
        return list(self._delivery_signals)


# ---------------------------------------------------------------------------
# PostgreSQL implementation
# ---------------------------------------------------------------------------
class PostgresGoalWorkRunStore:
    """Durable Goal/Work/Run store on PostgreSQL (migration 0006 schema).

    Each mutating method runs its transition and its provenance Event inside a
    single DB transaction, so provenance can never diverge from state.
    Optimistic concurrency uses ``WHERE revision = expected`` guards.
    """

    def __init__(self, database_url: str, *, pool: AsyncConnectionPool | None = None) -> None:
        self.pool = pool or AsyncConnectionPool(database_url, open=False)

    async def open(self) -> None:
        await self.pool.open()

    async def close(self) -> None:
        await self.pool.close()

    # -- Goal ---------------------------------------------------------------
    async def create_goal(self, goal: GoalRecord, event: SemanticEvent) -> GoalRecord:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO goals
                        (goal_id, user_id, title, semantic_status, priority,
                         commitment, completion_policy_ref, revision,
                         created_at, updated_at, terminal_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        goal.goal_id, goal.user_id, goal.title, goal.status.value,
                        goal.priority, goal.commitment, goal.completion_policy_ref,
                        goal.revision, goal.created_at, goal.updated_at, goal.terminal_at,
                    ),
                )
                await self._append_event_conn(conn, event)
        return goal

    async def get_goal(self, goal_id: GoalId) -> GoalRecord | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT goal_id, user_id, title, semantic_status, completion_policy_ref,
                       priority, commitment, revision, created_at, updated_at, terminal_at
                FROM goals WHERE goal_id = %s
                """,
                (goal_id,),
            )
            row = await cur.fetchone()
        return _goal_from_row(row) if row else None

    async def list_goals(self, *, user_id: str | None = None) -> list[GoalRecord]:
        query = (
            "SELECT goal_id, user_id, title, semantic_status, completion_policy_ref, "
            "priority, commitment, revision, created_at, updated_at, terminal_at FROM goals"
        )
        params: tuple[Any, ...] = ()
        if user_id is not None:
            query += " WHERE user_id = %s"
            params = (user_id,)
        async with self.pool.connection() as conn:
            cur = await conn.execute(query, params)
            rows = await cur.fetchall()
        return [_goal_from_row(r) for r in rows]

    async def transition_goal_status(
        self,
        goal_id: GoalId,
        target: GoalStatus,
        expected_revision: int,
        event: SemanticEvent,
        *,
        evidence: CompletionEvidence | OutcomeRecord | None = None,
    ) -> GoalRecord:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """
                    SELECT goal_id, user_id, title, semantic_status, completion_policy_ref,
                           priority, commitment, revision, created_at, updated_at, terminal_at
                    FROM goals WHERE goal_id = %s FOR UPDATE
                    """,
                    (goal_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise NotFoundError(f"goal not found: {goal_id}")
                current = _goal_from_row(row)
                _check_revision(current.revision, expected_revision, "goal", goal_id)
                updated = transition_goal(current, target, evidence)
                res = await conn.execute(
                    """
                    UPDATE goals
                    SET semantic_status = %s, revision = %s, updated_at = %s, terminal_at = %s
                    WHERE goal_id = %s AND revision = %s
                    RETURNING revision
                    """,
                    (
                        updated.status.value, updated.revision, updated.updated_at,
                        updated.terminal_at, goal_id, expected_revision,
                    ),
                )
                if await res.fetchone() is None:
                    raise StoreConflictError(f"goal {goal_id} revision conflict")
                await self._append_event_conn(conn, event)
        return updated

    # -- Work ---------------------------------------------------------------
    async def create_work(self, work: WorkRecord, event: SemanticEvent) -> WorkRecord:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                goal = await conn.execute("SELECT user_id FROM goals WHERE goal_id = %s", (work.goal_id,))
                grow = await goal.fetchone()
                if grow is None:
                    raise NotFoundError(f"goal not found for work: {work.goal_id}")
                await conn.execute(
                    """
                    INSERT INTO work_items
                        (work_id, goal_id, user_id, title, semantic_status, priority,
                         revision, created_at, updated_at, terminal_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        work.work_id, work.goal_id, grow[0], work.title, work.status.value,
                        work.priority, work.revision, work.created_at, work.updated_at,
                        work.terminal_at,
                    ),
                )
                await self._append_event_conn(conn, event)
        return work

    async def get_work(self, work_id: WorkId) -> WorkRecord | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT work_id, goal_id, title, semantic_status, priority,
                       revision, created_at, updated_at, terminal_at
                FROM work_items WHERE work_id = %s
                """,
                (work_id,),
            )
            row = await cur.fetchone()
        return _work_from_row(row) if row else None

    async def list_work(self, goal_id: GoalId) -> list[WorkRecord]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT work_id, goal_id, title, semantic_status, priority,
                       revision, created_at, updated_at, terminal_at
                FROM work_items WHERE goal_id = %s
                """,
                (goal_id,),
            )
            rows = await cur.fetchall()
        return [_work_from_row(r) for r in rows]

    async def transition_work_status(
        self,
        work_id: WorkId,
        target: WorkStatus,
        expected_revision: int,
        event: SemanticEvent,
        *,
        evidence: CompletionEvidence | OutcomeRecord | None = None,
    ) -> WorkRecord:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """
                    SELECT work_id, goal_id, title, semantic_status, priority,
                           revision, created_at, updated_at, terminal_at
                    FROM work_items WHERE work_id = %s FOR UPDATE
                    """,
                    (work_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise NotFoundError(f"work not found: {work_id}")
                current = _work_from_row(row)
                _check_revision(current.revision, expected_revision, "work", work_id)
                updated = transition_work(current, target, evidence)
                res = await conn.execute(
                    """
                    UPDATE work_items
                    SET semantic_status = %s, revision = %s, updated_at = %s, terminal_at = %s
                    WHERE work_id = %s AND revision = %s
                    RETURNING revision
                    """,
                    (
                        updated.status.value, updated.revision, updated.updated_at,
                        updated.terminal_at, work_id, expected_revision,
                    ),
                )
                if await res.fetchone() is None:
                    raise StoreConflictError(f"work {work_id} revision conflict")
                await self._append_event_conn(conn, event)
        return updated

    # -- Run ----------------------------------------------------------------
    async def create_run(self, run: RunRecord, event: SemanticEvent) -> RunRecord:
        ref = run.execution_ref
        async with self.pool.connection() as conn:
            async with conn.transaction():
                w = await conn.execute("SELECT work_id FROM work_items WHERE work_id = %s", (run.work_id,))
                if await w.fetchone() is None:
                    raise NotFoundError(f"work not found for run: {run.work_id}")
                try:
                    await conn.execute(
                        """
                        INSERT INTO runs_semantic
                            (run_id, work_id, semantic_status, attempt_number,
                             execution_backend, execution_id, execution_version,
                             revision, created_at, updated_at, terminal_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            run.run_id, run.work_id, run.status.value, run.attempt_number,
                            ref.backend if ref else None,
                            ref.execution_id if ref else None,
                            ref.execution_version if ref else None,
                            1, run.created_at, run.updated_at, run.terminal_at,
                        ),
                    )
                except Exception as exc:  # unique-violation on one_active_run_per_work
                    if _is_unique_violation(exc):
                        raise InvariantViolationError(
                            f"work {run.work_id} already has an active Run"
                        ) from exc
                    raise
                await self._append_event_conn(conn, event)
        _set_run_revision(run, 1)
        return run

    async def get_run(self, run_id: RunId) -> RunRecord | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT run_id, work_id, semantic_status, attempt_number,
                       execution_backend, execution_id, execution_version,
                       revision, created_at, updated_at, terminal_at
                FROM runs_semantic WHERE run_id = %s
                """,
                (run_id,),
            )
            row = await cur.fetchone()
        return _run_from_row(row) if row else None

    async def list_runs(self, work_id: WorkId) -> list[RunRecord]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT run_id, work_id, semantic_status, attempt_number,
                       execution_backend, execution_id, execution_version,
                       revision, created_at, updated_at, terminal_at
                FROM runs_semantic WHERE work_id = %s
                """,
                (work_id,),
            )
            rows = await cur.fetchall()
        return [_run_from_row(r) for r in rows]

    async def attach_execution_ref(
        self, run_id: RunId, expected_revision: int, ref: ExecutionRef, event: SemanticEvent
    ) -> RunRecord:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """
                    SELECT run_id, work_id, semantic_status, attempt_number,
                           execution_backend, execution_id, execution_version,
                           revision, created_at, updated_at, terminal_at
                    FROM runs_semantic WHERE run_id = %s FOR UPDATE
                    """,
                    (run_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise NotFoundError(f"run not found: {run_id}")
                current = _run_from_row(row)
                _check_revision(_run_revision(current), expected_revision, "run", run_id)
                if current.execution_ref is not None:
                    if _same_ref(current.execution_ref, ref):
                        return current
                    raise ExecutionRefConflictError(
                        f"run {run_id} already has a different ExecutionRef"
                    )
                res = await conn.execute(
                    """
                    UPDATE runs_semantic
                    SET execution_backend = %s, execution_id = %s, execution_version = %s,
                        revision = revision + 1, updated_at = %s
                    WHERE run_id = %s AND revision = %s
                      AND execution_backend IS NULL
                    RETURNING revision
                    """,
                    (
                        ref.backend, ref.execution_id, ref.execution_version,
                        utc_now(), run_id, expected_revision,
                    ),
                )
                newrow = await res.fetchone()
                if newrow is None:
                    raise ExecutionRefConflictError(
                        f"run {run_id} ExecutionRef attach lost the compare-and-set race"
                    )
                await self._append_event_conn(conn, event)
                updated = RunRecord(
                    run_id=current.run_id, work_id=current.work_id, status=current.status,
                    attempt_number=current.attempt_number, execution_ref=ref,
                    created_at=current.created_at, updated_at=utc_now(),
                    terminal_at=current.terminal_at,
                )
                _set_run_revision(updated, int(newrow[0]))
        return updated

    async def transition_run_status(
        self,
        run_id: RunId,
        target: RunStatus,
        expected_revision: int,
        event: SemanticEvent,
        *,
        execution_ref: ExecutionRef | None = None,
    ) -> RunRecord:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """
                    SELECT run_id, work_id, semantic_status, attempt_number,
                           execution_backend, execution_id, execution_version,
                           revision, created_at, updated_at, terminal_at
                    FROM runs_semantic WHERE run_id = %s FOR UPDATE
                    """,
                    (run_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise NotFoundError(f"run not found: {run_id}")
                current = _run_from_row(row)
                _check_revision(_run_revision(current), expected_revision, "run", run_id)
                updated = transition_run(current, target, execution_ref)
                new_ref = updated.execution_ref
                res = await conn.execute(
                    """
                    UPDATE runs_semantic
                    SET semantic_status = %s, execution_backend = %s, execution_id = %s,
                        execution_version = %s, revision = revision + 1, updated_at = %s,
                        terminal_at = %s
                    WHERE run_id = %s AND revision = %s
                    RETURNING revision
                    """,
                    (
                        updated.status.value,
                        new_ref.backend if new_ref else None,
                        new_ref.execution_id if new_ref else None,
                        new_ref.execution_version if new_ref else None,
                        updated.updated_at, updated.terminal_at, run_id, expected_revision,
                    ),
                )
                newrow = await res.fetchone()
                if newrow is None:
                    raise StoreConflictError(f"run {run_id} revision conflict")
                await self._append_event_conn(conn, event)
                _set_run_revision(updated, int(newrow[0]))
        return updated

    async def find_reconciliation_candidates(self) -> list[RunRecord]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT run_id, work_id, semantic_status, attempt_number,
                       execution_backend, execution_id, execution_version,
                       revision, created_at, updated_at, terminal_at
                FROM runs_semantic
                WHERE semantic_status = 'STARTING' AND execution_backend IS NULL
                """
            )
            rows = await cur.fetchall()
        return [_run_from_row(r) for r in rows]

    # -- Events -------------------------------------------------------------
    async def _append_event_conn(self, conn: Any, event: SemanticEvent) -> None:
        await conn.execute(
            """
            INSERT INTO semantic_events
                (event_id, occurred_at, goal_id, work_id, run_id, trace_id,
                 external_ref, actor, type, payload, artifact_refs)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event.event_id, event.occurred_at, event.goal_id, event.work_id,
                event.run_id, event.trace_id, event.external_ref, event.actor,
                event.type, Jsonb(event.payload), Jsonb(list(event.artifact_refs)),
            ),
        )

    async def list_events(
        self,
        *,
        goal_id: GoalId | None = None,
        work_id: WorkId | None = None,
        run_id: RunId | None = None,
    ) -> list[SemanticEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if goal_id is not None:
            clauses.append("goal_id = %s")
            params.append(goal_id)
        if work_id is not None:
            clauses.append("work_id = %s")
            params.append(work_id)
        if run_id is not None:
            clauses.append("run_id = %s")
            params.append(run_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT event_id, occurred_at, goal_id, work_id, run_id, trace_id, "
                "external_ref, actor, type, payload, artifact_refs FROM semantic_events"
                + where + " ORDER BY occurred_at",
                tuple(params),
            )
            rows = await cur.fetchall()
        return [
            SemanticEvent(
                event_id=EventId(r[0]), occurred_at=r[1], goal_id=r[2], work_id=r[3],
                run_id=r[4], trace_id=r[5], external_ref=r[6], actor=r[7], type=r[8],
                payload=dict(r[9] or {}), artifact_refs=tuple(r[10] or ()),
            )
            for r in rows
        ]

    # -- Questions ----------------------------------------------------------
    async def create_question(self, question: QuestionRecordSemantic) -> QuestionRecordSemantic:
        async with self.pool.connection() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO questions_semantic
                        (question_id, work_id, run_id, prompt, status, answer_ref,
                         signal_correlation, revision, created_at, updated_at, answered_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        question.question_id, question.work_id, question.run_id,
                        question.prompt, question.status, question.answer_ref,
                        question.signal_correlation, question.revision,
                        question.created_at, question.updated_at, question.answered_at,
                    ),
                )
            except Exception as exc:  # one_pending_question_per_work
                if _is_unique_violation(exc):
                    raise PendingQuestionExistsError(
                        f"work {question.work_id} already has a PENDING question"
                    ) from exc
                raise
        return question

    async def get_question(self, question_id: QuestionId) -> QuestionRecordSemantic | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT question_id, work_id, run_id, prompt, status, answer_ref,
                       signal_correlation, revision, created_at, updated_at, answered_at
                FROM questions_semantic WHERE question_id = %s
                """,
                (question_id,),
            )
            row = await cur.fetchone()
        return _question_from_row(row) if row else None

    async def answer_question(
        self,
        question_id: QuestionId,
        expected_revision: int,
        answer_ref: str,
        signal_correlation: str,
    ) -> QuestionRecordSemantic:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """
                    SELECT question_id, work_id, run_id, prompt, status, answer_ref,
                           signal_correlation, revision, created_at, updated_at, answered_at
                    FROM questions_semantic WHERE question_id = %s FOR UPDATE
                    """,
                    (question_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise NotFoundError(f"question not found: {question_id}")
                current = _question_from_row(row)
                _check_revision(current.revision, expected_revision, "question", question_id)
                if current.status != _QUESTION_ACTIVE:
                    raise StoreConflictError(f"question {question_id} is not PENDING")
                now = utc_now()
                res = await conn.execute(
                    """
                    UPDATE questions_semantic
                    SET status = 'ANSWERED', answer_ref = %s, signal_correlation = %s,
                        revision = revision + 1, updated_at = %s, answered_at = %s
                    WHERE question_id = %s AND revision = %s AND status = 'PENDING'
                    RETURNING revision
                    """,
                    (answer_ref, signal_correlation, now, now, question_id, expected_revision),
                )
                newrow = await res.fetchone()
                if newrow is None:
                    raise StoreConflictError(f"question {question_id} revision conflict")
                # Atomic delivery signal: the answered fact and its correlation
                # commit in the same transaction (recorded on the question row via
                # signal_correlation). A separate outbox row would be inserted here
                # in the delivery-integrated build.
                updated = QuestionRecordSemantic(
                    question_id=current.question_id, prompt=current.prompt, status="ANSWERED",
                    work_id=current.work_id, run_id=current.run_id, answer_ref=answer_ref,
                    signal_correlation=signal_correlation, revision=int(newrow[0]),
                    created_at=current.created_at, updated_at=now, answered_at=now,
                )
        return updated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _check_revision(actual: int, expected: int, kind: str, ident: Any) -> None:
    if actual != expected:
        raise StoreConflictError(
            f"{kind} {ident} revision conflict: expected {expected}, found {actual}"
        )


def _same_ref(a: ExecutionRef, b: ExecutionRef) -> bool:
    return (
        a.backend == b.backend
        and a.execution_id == b.execution_id
        and a.execution_version == b.execution_version
    )


# RunRecord (domain) has no revision field; store revision out of band by RunId.
_RUN_REVISIONS: "dict[RunId, int]" = {}


def _run_revision(run: RunRecord) -> int:
    return _RUN_REVISIONS.get(run.run_id, 1)


def _set_run_revision(run: RunRecord, revision: int) -> None:
    _RUN_REVISIONS[run.run_id] = revision


def _is_unique_violation(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == "23505":
        return True
    return "unique" in str(exc).lower() or "duplicate" in str(exc).lower()


def _goal_from_row(row: Any) -> GoalRecord:
    return GoalRecord(
        goal_id=GoalId(row[0]), user_id=row[1], title=row[2], status=GoalStatus(row[3]),
        completion_policy_ref=row[4], priority=row[5], commitment=row[6],
        revision=row[7], created_at=row[8], updated_at=row[9], terminal_at=row[10],
    )


def _work_from_row(row: Any) -> WorkRecord:
    return WorkRecord(
        work_id=WorkId(row[0]), goal_id=GoalId(row[1]), title=row[2],
        status=WorkStatus(row[3]), priority=row[4], revision=row[5],
        created_at=row[6], updated_at=row[7], terminal_at=row[8],
    )


def _run_from_row(row: Any) -> RunRecord:
    ref: ExecutionRef | None = None
    if row[4] is not None and row[5] is not None:
        ref = ExecutionRef(backend=row[4], execution_id=row[5], execution_version=row[6] or 1)
    run = RunRecord(
        run_id=RunId(row[0]), work_id=WorkId(row[1]), status=RunStatus(row[2]),
        attempt_number=row[3], execution_ref=ref,
        created_at=row[8], updated_at=row[9], terminal_at=row[10],
    )
    _set_run_revision(run, int(row[7]))
    return run


def _question_from_row(row: Any) -> QuestionRecordSemantic:
    return QuestionRecordSemantic(
        question_id=QuestionId(row[0]),
        work_id=WorkId(row[1]) if row[1] is not None else None,
        run_id=RunId(row[2]) if row[2] is not None else None,
        prompt=row[3],
        status=row[4],
        answer_ref=row[5],
        signal_correlation=row[6],
        revision=row[7],
        created_at=row[8],
        updated_at=row[9],
        answered_at=row[10],
    )
