from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable

from all_tomorrow.domain.errors import (
    ActiveRunLimitExceededError,
    InvalidStateTransitionError,
    TerminalReviveError,
    WorkExecutionRefForbiddenError,
)
from all_tomorrow.domain.ids import ExecutionRef, GoalId, RunId, WorkId, utc_now
from all_tomorrow.domain.outcomes import (
    CompletionEvidence,
    OutcomeRecord,
    TargetType,
    verify_completion_evidence,
)


class GoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class WorkStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class RunStatus(StrEnum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


TERMINAL_GOAL_STATUSES: frozenset[GoalStatus] = frozenset({
    GoalStatus.SUCCEEDED,
    GoalStatus.FAILED,
    GoalStatus.CANCELLED,
})

TERMINAL_WORK_STATUSES: frozenset[WorkStatus] = frozenset({
    WorkStatus.SUCCEEDED,
    WorkStatus.FAILED,
    WorkStatus.CANCELLED,
})

TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset({
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
})

ACTIVE_RUN_STATUSES: frozenset[RunStatus] = frozenset({
    RunStatus.STARTING,
    RunStatus.RUNNING,
    RunStatus.WAITING,
    RunStatus.CANCEL_REQUESTED,
})

# Canonical state transition maps
GOAL_TRANSITIONS: dict[GoalStatus, frozenset[GoalStatus]] = {
    GoalStatus.ACTIVE: frozenset({
        GoalStatus.WAITING,
        GoalStatus.SUCCEEDED,
        GoalStatus.FAILED,
        GoalStatus.CANCEL_REQUESTED,
        GoalStatus.CANCELLED,
    }),
    GoalStatus.WAITING: frozenset({
        GoalStatus.ACTIVE,
        GoalStatus.SUCCEEDED,
        GoalStatus.FAILED,
        GoalStatus.CANCEL_REQUESTED,
        GoalStatus.CANCELLED,
    }),
    GoalStatus.CANCEL_REQUESTED: frozenset({
        GoalStatus.CANCELLED,
    }),
    GoalStatus.SUCCEEDED: frozenset(),
    GoalStatus.FAILED: frozenset(),
    GoalStatus.CANCELLED: frozenset(),
}

WORK_TRANSITIONS: dict[WorkStatus, frozenset[WorkStatus]] = {
    WorkStatus.PENDING: frozenset({
        WorkStatus.RUNNING,
        WorkStatus.CANCELLED,
    }),
    WorkStatus.RUNNING: frozenset({
        WorkStatus.WAITING,
        WorkStatus.SUCCEEDED,
        WorkStatus.FAILED,
        WorkStatus.CANCEL_REQUESTED,
        WorkStatus.CANCELLED,
    }),
    WorkStatus.WAITING: frozenset({
        WorkStatus.RUNNING,
        WorkStatus.CANCEL_REQUESTED,
        WorkStatus.CANCELLED,
    }),
    WorkStatus.CANCEL_REQUESTED: frozenset({
        WorkStatus.CANCELLED,
    }),
    WorkStatus.SUCCEEDED: frozenset(),
    WorkStatus.FAILED: frozenset(),
    WorkStatus.CANCELLED: frozenset(),
}

RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.STARTING: frozenset({
        RunStatus.RUNNING,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }),
    RunStatus.RUNNING: frozenset({
        RunStatus.WAITING,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCEL_REQUESTED,
        RunStatus.CANCELLED,
    }),
    RunStatus.WAITING: frozenset({
        RunStatus.RUNNING,
        RunStatus.CANCEL_REQUESTED,
        RunStatus.CANCELLED,
    }),
    RunStatus.CANCEL_REQUESTED: frozenset({
        RunStatus.CANCELLED,
    }),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class GoalRecord:
    goal_id: GoalId
    user_id: str
    title: str
    status: GoalStatus = GoalStatus.ACTIVE
    completion_policy_ref: str | None = None
    priority: int = 0
    commitment: str = "default"
    revision: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    terminal_at: datetime | None = None

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_GOAL_STATUSES


@dataclass(frozen=True, slots=True)
class WorkRecord:
    """Work semantic unit.

    CRITICAL INVARIANT: Work must NOT possess an execution_ref,
    execution_backend, or execution_id. External durable execution
    linkage is strictly owned by RunRecord.
    """
    work_id: WorkId
    goal_id: GoalId
    title: str
    status: WorkStatus = WorkStatus.PENDING
    priority: int = 0
    revision: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    terminal_at: datetime | None = None

    def __init__(
        self,
        work_id: WorkId,
        goal_id: GoalId,
        title: str,
        status: WorkStatus = WorkStatus.PENDING,
        priority: int = 0,
        revision: int = 1,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        terminal_at: datetime | None = None,
        **extra: Any,
    ) -> None:
        forbidden = {"execution_ref", "execution_backend", "execution_id"} & set(extra.keys())
        if forbidden:
            raise WorkExecutionRefForbiddenError(
                f"Work records must not contain external execution references: {forbidden}. ExecutionRef belongs strictly to RunRecord."
            )
        if extra:
            raise TypeError(f"Unexpected arguments for WorkRecord: {list(extra.keys())}")
        object.__setattr__(self, "work_id", work_id)
        object.__setattr__(self, "goal_id", goal_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "created_at", created_at or utc_now())
        object.__setattr__(self, "updated_at", updated_at or utc_now())
        object.__setattr__(self, "terminal_at", terminal_at)

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_WORK_STATUSES


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Run logical attempt.

    Work 1:N Run. Each Run owns its optional ExecutionRef.
    """
    run_id: RunId
    work_id: WorkId
    status: RunStatus = RunStatus.STARTING
    attempt_number: int = 1
    execution_ref: ExecutionRef | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    terminal_at: datetime | None = None

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    def is_active(self) -> bool:
        return self.status in ACTIVE_RUN_STATUSES


def assert_active_runs_invariant(
    runs: Iterable[RunRecord],
    max_active: int = 1,
) -> None:
    """Verifies that the number of active runs does not exceed max_active."""
    active_runs = [r for r in runs if r.is_active()]
    if len(active_runs) > max_active:
        active_ids = [str(r.run_id) for r in active_runs]
        raise ActiveRunLimitExceededError(
            f"Active run limit exceeded: max allowed={max_active}, found {len(active_runs)} ({active_ids})"
        )


def transition_goal(
    goal: GoalRecord,
    target: GoalStatus,
    evidence: CompletionEvidence | OutcomeRecord | None = None,
) -> GoalRecord:
    if goal.is_terminal():
        raise TerminalReviveError(
            f"Cannot transition terminal Goal '{goal.goal_id}' (status={goal.status.value}) to '{target.value}'"
        )
    allowed = GOAL_TRANSITIONS.get(goal.status, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal Goal transition from '{goal.status.value}' to '{target.value}'"
        )
    if target == GoalStatus.SUCCEEDED:
        verify_completion_evidence(TargetType.GOAL, str(goal.goal_id), evidence)

    now = utc_now()
    terminal_at = now if target in TERMINAL_GOAL_STATUSES else None
    return GoalRecord(
        goal_id=goal.goal_id,
        user_id=goal.user_id,
        title=goal.title,
        status=target,
        completion_policy_ref=goal.completion_policy_ref,
        priority=goal.priority,
        commitment=goal.commitment,
        revision=goal.revision + 1,
        created_at=goal.created_at,
        updated_at=now,
        terminal_at=terminal_at,
    )


def transition_work(
    work: WorkRecord,
    target: WorkStatus,
    evidence: CompletionEvidence | OutcomeRecord | None = None,
) -> WorkRecord:
    if work.is_terminal():
        raise TerminalReviveError(
            f"Cannot transition terminal Work '{work.work_id}' (status={work.status.value}) to '{target.value}'"
        )
    allowed = WORK_TRANSITIONS.get(work.status, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal Work transition from '{work.status.value}' to '{target.value}'"
        )
    if target == WorkStatus.SUCCEEDED:
        verify_completion_evidence(TargetType.WORK, str(work.work_id), evidence)

    now = utc_now()
    terminal_at = now if target in TERMINAL_WORK_STATUSES else None
    return WorkRecord(
        work_id=work.work_id,
        goal_id=work.goal_id,
        title=work.title,
        status=target,
        priority=work.priority,
        revision=work.revision + 1,
        created_at=work.created_at,
        updated_at=now,
        terminal_at=terminal_at,
    )


def transition_run(
    run: RunRecord,
    target: RunStatus,
    execution_ref: ExecutionRef | None = None,
) -> RunRecord:
    if run.is_terminal():
        raise TerminalReviveError(
            f"Cannot transition terminal Run '{run.run_id}' (status={run.status.value}) to '{target.value}'"
        )
    allowed = RUN_TRANSITIONS.get(run.status, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal Run transition from '{run.status.value}' to '{target.value}'"
        )

    now = utc_now()
    terminal_at = now if target in TERMINAL_RUN_STATUSES else None
    new_ref = execution_ref if execution_ref is not None else run.execution_ref
    return RunRecord(
        run_id=run.run_id,
        work_id=run.work_id,
        status=target,
        attempt_number=run.attempt_number,
        execution_ref=new_ref,
        created_at=run.created_at,
        updated_at=now,
        terminal_at=terminal_at,
    )
