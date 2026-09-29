"""Stage 2.5A -- Executor loop.

Background loop that claims PENDING Work from the semantic store (via a DB-level
lock so two concurrent loops never claim the same Work), runs it through a
WorkerService adapter, and transitions it to its terminal or WAITING state.

No fake success: a Work whose worker is unavailable, whose execution raises, or
whose result is not a recognized shape becomes FAILED with the reason recorded
in the Run's completion evidence / a semantic Event, never SUCCEEDED.

Question handoff (S2-23C wiring): a worker result carrying a ``need_question``
key in its payload means the worker could not finish without user input. The
executor creates a Question, links it to the current Run, and moves the Work to
WAITING instead of terminalizing the Run as failed. When the question is later
answered (``WebControl.answer`` / ``GoalWorkRunStore.answer_question``), the Work
is moved back to RUNNING (new Run) by ``resume_answered_work``, called from the
same executor loop's next pass.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from all_tomorrow.contracts import Worker, WorkerRequest, WorkerResult, WorkerStatus
from all_tomorrow.domain.errors import DomainError, MissingCompletionEvidenceError
from all_tomorrow.domain.ids import QuestionId, new_event_id, new_question_id, new_run_id
from all_tomorrow.domain.outcomes import CompletionEvidence
from all_tomorrow.domain.state import RunStatus, WorkRecord, WorkStatus
from all_tomorrow.registry import WorkerService
from all_tomorrow.storage.semantic_store import (
    GoalWorkRunStore,
    QuestionRecordSemantic,
    SemanticEvent,
)

logger = logging.getLogger("all_tomorrow.executor")

DEFAULT_WORKER_ID = "kiro"
EVALUATOR_REF = "all_tomorrow.executor.worker_result"
EVALUATOR_VERSION = "1"


class NoWorkerAvailableError(DomainError):
    """Raised (and turned into a FAILED Work) when no configured worker can run it."""


def _evt(actor: str, type_: str, **kw) -> SemanticEvent:
    return SemanticEvent(event_id=new_event_id(), actor=actor, type=type_, **kw)


@dataclass(slots=True)
class ExecutorResult:
    work_id: str
    outcome: str  # "succeeded" | "failed" | "waiting"
    detail: str | None = None


class ExecutorLoop:
    """Claims Work, runs it through a worker, and records the outcome.

    ``worker_id`` selects which configured local worker executes claimed Work;
    callers that need per-Work worker selection should subclass and override
    ``_select_worker_id``.
    """

    def __init__(
        self,
        store: GoalWorkRunStore,
        worker_service: WorkerService,
        *,
        worker_id: str = DEFAULT_WORKER_ID,
        actor: str = "executor",
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.store = store
        self.worker_service = worker_service
        self.worker_id = worker_id
        self.actor = actor
        self.poll_interval_seconds = poll_interval_seconds

    def _select_worker_id(self, work: WorkRecord) -> str:
        return self.worker_id

    async def run_one_cycle(self, *, limit: int = 1) -> list[ExecutorResult]:
        """Claim up to ``limit`` PENDING Work and drive each one to completion.

        Safe to call concurrently from multiple processes/loops: the store's
        ``claim_pending_work`` uses a DB-level lock (or, for the in-memory store,
        an asyncio lock) so the same Work is never claimed twice.
        """
        claimed = await self.store.claim_pending_work(limit=limit)
        results: list[ExecutorResult] = []
        for work in claimed:
            results.append(await self._execute_claimed_work(work))
        return results

    async def run_forever(self, *, stop_event: asyncio.Event | None = None) -> None:
        """Poll indefinitely until ``stop_event`` is set (or forever if omitted)."""
        stop_event = stop_event or asyncio.Event()
        while not stop_event.is_set():
            try:
                await self.run_one_cycle()
            except Exception:  # a loop-level bug must not kill the background task
                logger.exception("executor cycle failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def _execute_claimed_work(self, work: WorkRecord) -> ExecutorResult:
        run = None
        try:
            run = await self._create_run_for(work)
            worker_id = self._select_worker_id(work)
            if not self.worker_service.has_worker(worker_id):
                raise NoWorkerAvailableError(f"no worker configured/available: {worker_id}")
            request = WorkerRequest(
                request_id=str(work.work_id),
                trace_id=str(run.run_id),
                project_id=None,
                capabilities=self.worker_service.get_adapter(worker_id).capabilities,
                payload={"task": work.title},
            )
            result = await self.worker_service.execute(worker_id, request)
        except Exception as exc:  # noqa: BLE001 -- any failure here is a real FAILED outcome
            return await self._fail(work, run, exc)

        if result.status is not WorkerStatus.SUCCESS:
            return await self._fail(work, run, RuntimeError(result.error or result.status.value))

        need_question = (result.payload or {}).get("need_question")
        if need_question:
            return await self._to_waiting(work, run, str(need_question))
        return await self._succeed(work, run, result)

    async def _create_run_for(self, work: WorkRecord):
        from all_tomorrow.domain.state import RunRecord, RunStatus as _RunStatus

        run = RunRecord(run_id=new_run_id(), work_id=work.work_id)
        created = await self.store.create_run(run, _evt(self.actor, "run.created", work_id=work.work_id))
        rev = await self.store.current_run_revision(created.run_id)
        # STARTING -> RUNNING before dispatch: RUN_TRANSITIONS only allows STARTING
        # to reach RUNNING/FAILED/CANCELLED, never SUCCEEDED/WAITING directly.
        return await self.store.transition_run_status(
            created.run_id, _RunStatus.RUNNING, rev,
            _evt(self.actor, "run.running", work_id=work.work_id, run_id=created.run_id),
        )

    async def _succeed(self, work: WorkRecord, run, result: WorkerResult) -> ExecutorResult:
        rev = await self.store.current_run_revision(run.run_id)
        await self.store.transition_run_status(
            run.run_id, RunStatus.SUCCEEDED, rev,
            _evt(self.actor, "run.succeeded", work_id=work.work_id, run_id=run.run_id),
        )
        evidence = CompletionEvidence(
            criterion_ref=f"work:{work.work_id}",
            evaluator_ref=EVALUATOR_REF,
            evaluator_version=EVALUATOR_VERSION,
            observed_values={"duration_ms": result.duration_ms},
        )
        work_cur = await self.store.get_work(work.work_id)
        await self.store.transition_work_status(
            work.work_id, WorkStatus.SUCCEEDED, work_cur.revision,
            _evt(self.actor, "work.succeeded", work_id=work.work_id), evidence=evidence,
        )
        return ExecutorResult(work_id=str(work.work_id), outcome="succeeded")

    async def _fail(self, work: WorkRecord, run, exc: Exception) -> ExecutorResult:
        reason = str(exc)
        if run is not None:
            try:
                rev = await self.store.current_run_revision(run.run_id)
                await self.store.transition_run_status(
                    run.run_id, RunStatus.FAILED, rev,
                    _evt(self.actor, "run.failed", work_id=work.work_id, run_id=run.run_id,
                         payload={"reason": reason}),
                )
            except DomainError:
                pass  # Run already terminal/conflicted; Work FAILED below is authoritative.
        work_cur = await self.store.get_work(work.work_id)
        try:
            await self.store.transition_work_status(
                work.work_id, WorkStatus.FAILED, work_cur.revision,
                _evt(self.actor, "work.failed", work_id=work.work_id, payload={"reason": reason}),
            )
        except DomainError:
            pass  # Work already moved on (e.g. cancelled concurrently).
        return ExecutorResult(work_id=str(work.work_id), outcome="failed", detail=reason)

    async def _to_waiting(self, work: WorkRecord, run, prompt: str) -> ExecutorResult:
        question = QuestionRecordSemantic(
            question_id=new_question_id(), work_id=work.work_id, run_id=run.run_id, prompt=prompt,
        )
        await self.store.create_question(question)
        work_cur = await self.store.get_work(work.work_id)
        # WAITING is only reachable from RUNNING per WORK_TRANSITIONS -- the claimed
        # Work is already RUNNING, so this is a legal single-step transition.
        await self.store.transition_work_status(
            work.work_id, WorkStatus.WAITING, work_cur.revision,
            _evt(self.actor, "work.waiting_on_question", work_id=work.work_id,
                 payload={"question_id": str(question.question_id)}),
        )
        try:
            rev = await self.store.current_run_revision(run.run_id)
            await self.store.transition_run_status(
                run.run_id, RunStatus.WAITING, rev,
                _evt(self.actor, "run.waiting_on_question", work_id=work.work_id, run_id=run.run_id),
            )
        except DomainError:
            pass
        return ExecutorResult(work_id=str(work.work_id), outcome="waiting",
                               detail=str(question.question_id))


async def resume_answered_work(store: GoalWorkRunStore, work_id, *, actor: str = "executor") -> bool:
    """Move a WAITING Work whose question was just answered back to RUNNING.

    The prior WAITING Run is closed out (CANCEL_REQUESTED -> CANCELLED) before a
    fresh Run is opened for the resumed attempt, since only one active Run per
    Work is ever allowed and WAITING counts as active. The closed Run's history
    is preserved as provenance (semantic Events), never deleted.

    Returns False as a no-op when the Work is not WAITING (e.g. a late/duplicate
    answer arriving after the Work already advanced) -- this must never create a
    second Run for the same answer.
    """
    work = await store.get_work(work_id)
    if work is None or work.status != WorkStatus.WAITING:
        return False
    from all_tomorrow.domain.state import RunRecord, RunStatus as _RunStatus

    prior_runs = [r for r in await store.list_runs(work_id) if r.is_active()]
    for prior in prior_runs:
        rev = await store.current_run_revision(prior.run_id)
        await store.transition_run_status(
            prior.run_id, _RunStatus.CANCEL_REQUESTED, rev,
            _evt(actor, "run.superseded_by_answer", work_id=work.work_id, run_id=prior.run_id),
        )
        rev2 = await store.current_run_revision(prior.run_id)
        await store.transition_run_status(
            prior.run_id, _RunStatus.CANCELLED, rev2,
            _evt(actor, "run.closed_after_answer", work_id=work.work_id, run_id=prior.run_id),
        )

    run = RunRecord(run_id=new_run_id(), work_id=work.work_id)
    await store.create_run(run, _evt(actor, "run.created", work_id=work.work_id))
    await store.transition_work_status(
        work.work_id, WorkStatus.RUNNING, work.revision,
        _evt(actor, "work.resumed_after_answer", work_id=work.work_id),
    )
    return True
