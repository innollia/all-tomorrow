"""02A — Observation Snapshot.

Lets the researcher read a bounded, reproducible slice of state instead of
dumping the whole DB into a prompt. A snapshot fixes an immutable Event range
``(lower_cursor exclusive, upper_cursor inclusive)`` ordered by
``(occurred_at, event_id)`` so same-timestamp events are never dropped, and the
same cursor reproduces the same range.

No raw prompt/output/secret is copied into snapshot metadata — only refs, ids,
counts, and cursors (OPERATIONAL_METADATA).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import GoalId, RunId, WorkId, new_id, utc_now
from all_tomorrow.domain.state import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_WORK_STATUSES,
    GoalStatus,
    WorkStatus,
)
from all_tomorrow.storage.semantic_store import GoalWorkRunStore, SemanticEvent


PROJECTION_VERSION = "1"


class CursorConflictError(DomainError):
    """Cursor advance lost the expected-revision CAS (another wake advanced it)."""


@dataclass(frozen=True, slots=True)
class EventCursor:
    """Ordering position in the Event stream: (occurred_at, event_id)."""
    last_event_at: datetime | None
    last_event_id: str | None
    revision: int = 1

    def is_before(self, event: SemanticEvent) -> bool:
        """True if ``event`` is strictly after this cursor (belongs to next range)."""
        if self.last_event_at is None:
            return True
        if event.occurred_at > self.last_event_at:
            return True
        if event.occurred_at == self.last_event_at:
            return (self.last_event_id or "") < event.event_id
        return False


@dataclass(frozen=True, slots=True)
class ObservationSnapshot:
    snapshot_id: str
    created_at: datetime
    observer_id: str
    user_id: str
    project_id: str | None
    active_goal_refs: tuple[GoalId, ...]
    open_work_refs: tuple[WorkId, ...]
    recent_run_refs: tuple[RunId, ...]
    lower_cursor: EventCursor
    upper_cursor: EventCursor
    event_refs: tuple[str, ...]
    pending_question_refs: tuple[str, ...]
    projection_version: str = PROJECTION_VERSION


@dataclass(slots=True)
class _CursorRow:
    observer_id: str
    user_id: str
    cursor: EventCursor


class ObservationBuilder:
    """Builds bounded snapshots and advances the observer cursor via CAS.

    ``recent_limit`` bounds terminal Work/Run history (config-versioned). The
    in-memory store is used directly; a Postgres implementation would issue the
    same bounded queries + an advisory lock around the wake.
    """

    def __init__(self, store: GoalWorkRunStore, *, recent_limit: int = 20) -> None:
        self.store = store
        self.recent_limit = recent_limit
        self._cursors: dict[tuple[str, str], EventCursor] = {}

    def get_cursor(self, observer_id: str, user_id: str) -> EventCursor:
        return self._cursors.get((observer_id, user_id), EventCursor(None, None, 0))

    async def build(
        self,
        observer_id: str,
        user_id: str,
        *,
        project_id: str | None = None,
        trigger_origin: str = "wake",
    ) -> ObservationSnapshot:
        lower = self.get_cursor(observer_id, user_id)

        goals = await self.store.list_goals(user_id=user_id)
        active_goals = [g for g in goals if g.status in (GoalStatus.ACTIVE, GoalStatus.WAITING)]

        open_work: list[WorkId] = []
        recent_runs: list[RunId] = []
        all_events: list[SemanticEvent] = []
        pending_q: list[str] = []

        for g in active_goals:
            works = await self.store.list_work(g.goal_id)
            for w in works:
                if w.status in (WorkStatus.PENDING, WorkStatus.RUNNING, WorkStatus.WAITING):
                    open_work.append(w.work_id)
                runs = await self.store.list_runs(w.work_id)
                # bounded recent runs
                for r in runs[: self.recent_limit]:
                    recent_runs.append(r.run_id)
            evs = await self.store.list_events(goal_id=g.goal_id)
            all_events.extend(evs)

        # Bounded, ordered event range strictly after the lower cursor.
        ranged = [e for e in all_events if lower.is_before(e)]
        ranged.sort(key=lambda e: (e.occurred_at, e.event_id))
        # upper bound = the max visible event at snapshot time (inclusive).
        if ranged:
            upper = EventCursor(
                last_event_at=ranged[-1].occurred_at,
                last_event_id=ranged[-1].event_id,
                revision=lower.revision + 1,
            )
        else:
            upper = lower

        return ObservationSnapshot(
            snapshot_id=new_id("snap"),
            created_at=utc_now(),
            observer_id=observer_id,
            user_id=user_id,
            project_id=project_id,
            active_goal_refs=tuple(g.goal_id for g in active_goals),
            open_work_refs=tuple(open_work),
            recent_run_refs=tuple(recent_runs),
            lower_cursor=lower,
            upper_cursor=upper,
            event_refs=tuple(e.event_id for e in ranged),
            pending_question_refs=tuple(pending_q),
        )

    def advance_cursor(
        self, observer_id: str, user_id: str, to: EventCursor, expected_revision: int
    ) -> EventCursor:
        """Advance the cursor with an expected-revision CAS (last line of defense)."""
        key = (observer_id, user_id)
        current = self._cursors.get(key, EventCursor(None, None, 0))
        if current.revision != expected_revision:
            raise CursorConflictError(
                f"cursor revision conflict for {key}: expected {expected_revision}, found {current.revision}"
            )
        self._cursors[key] = to
        return to
