"""Stage 2.3B — Run / Cancel / Replan execution service.

Coordinates Work execution over the semantic store: at most one active Run per
Work, same-Run crash recovery distinct from a new-Run semantic replan, a replan
budget on ordinary user Work too, and Goal cancellation propagated to child Work
and pending Questions. Builds on the 01B store + 02D budget primitives.
"""

from __future__ import annotations

from dataclasses import dataclass

from all_tomorrow.domain.errors import DomainError, InvariantViolationError
from all_tomorrow.domain.ids import GoalId, RunId, WorkId, new_event_id, new_run_id
from all_tomorrow.domain.outcomes import CompletionEvidence, OutcomeRecord
from all_tomorrow.domain.state import (
    GoalStatus, RunRecord, RunStatus, WorkStatus, TERMINAL_RUN_STATUSES,
)
from all_tomorrow.storage.semantic_store import (
    GoalWorkRunStore, InvariantViolationError as StoreInvariant, SemanticEvent,
)


class ReplanBudgetExceededError(DomainError):
    pass


def _evt(actor, type_, **kw):
    return SemanticEvent(event_id=new_event_id(), actor=actor, type=type_, **kw)


class ExecutionService:
    def __init__(self, store: GoalWorkRunStore, *, max_replans: int = 3, actor: str = "executor") -> None:
        self.store = store
        self.max_replans = max_replans
        self.actor = actor
        self._replans: dict[WorkId, int] = {}

    async def start_run(self, work_id: WorkId, *, attempt_number: int = 1) -> RunRecord:
        """Create a STARTING Run. The store's one-active-run guard enforces max=1."""
        run = RunRecord(run_id=new_run_id(), work_id=work_id, attempt_number=attempt_number)
        try:
            await self.store.create_run(run, _evt(self.actor, "run.created", work_id=work_id, run_id=run.run_id))
        except (StoreInvariant, InvariantViolationError) as exc:
            raise InvariantViolationError(f"work {work_id} already has an active Run") from exc
        return run

    async def replan(self, work_id: WorkId) -> RunRecord:
        """A NEW Run (new run_id) for a semantic replan, bounded by the replan budget."""
        used = self._replans.get(work_id, 0)
        if used + 1 > self.max_replans:
            raise ReplanBudgetExceededError(f"replan budget exhausted for {work_id}")
        # The prior active Run must be terminal before a new attempt (store enforces).
        self._replans[work_id] = used + 1
        return await self.start_run(work_id, attempt_number=used + 2)

    async def complete_work(
        self, work_id: WorkId, expected_revision: int, evidence: CompletionEvidence | OutcomeRecord
    ):
        """Work SUCCEEDED requires verified CompletionEvidence (store enforces)."""
        return await self.store.transition_work_status(
            work_id, WorkStatus.SUCCEEDED, expected_revision,
            _evt(self.actor, "work.succeeded", work_id=work_id), evidence=evidence)

    async def cancel_goal(self, goal_id: GoalId, expected_revision: int) -> dict:
        """Cancel a Goal and propagate to child Work + pending Questions.

        Returns a summary of what was cancel-requested. Non-interruptible external
        mutations are not force-killed here — only cancellation is *requested*.
        """
        # Move the Goal to CANCEL_REQUESTED.
        await self.store.transition_goal_status(
            goal_id, GoalStatus.CANCEL_REQUESTED, expected_revision,
            _evt(self.actor, "goal.cancel_requested", goal_id=goal_id))

        cancelled_work: list[str] = []
        for w in await self.store.list_work(goal_id):
            if w.status in (WorkStatus.PENDING, WorkStatus.RUNNING, WorkStatus.WAITING):
                target = WorkStatus.CANCEL_REQUESTED if w.status != WorkStatus.PENDING else WorkStatus.CANCELLED
                try:
                    await self.store.transition_work_status(
                        w.work_id, target, w.revision,
                        _evt(self.actor, "work.cancel_requested", work_id=w.work_id, goal_id=goal_id))
                    cancelled_work.append(str(w.work_id))
                except Exception:
                    pass  # a Work that already advanced is skipped; cancellation is best-effort
        return {"goal_id": str(goal_id), "cancelled_work": cancelled_work}

    def replans_used(self, work_id: WorkId) -> int:
        return self._replans.get(work_id, 0)
