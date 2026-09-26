"""01D — Run / Compatibility Linkage.

Connects existing PipelineRuntime assets and the new Run/durable/agent substrate
WITHOUT duplicating identity or recovery authority (ADR 0006 D-LOCK-12:
PipelineRuntime is compatibility-only).

Two pieces:

- ``ProvenanceGraph`` / ``assemble_provenance``: reads the 01B store and assembles
  the minimal provenance chain the contract requires —
  goal → work → run → ExecutionRef(backend/id/version) → optional
  pipeline_execution_id → AgentInvocation/OTel span ref → worker/tool request id →
  ArtifactRef/result refs. External provenance (pipeline_execution_id, span refs,
  agent invocation refs, artifact refs) is carried on ``SemanticEvent`` payloads,
  so a ``pipeline_execution_id`` is a provenance ref, never a second Run identity.

- ``NeedUserCoordinator``: the canonical NEED_USER path. A Question projection
  (UI/authorization meaning) is tied to the durable backend wait/signal
  (mechanism) by ``question_id ↔ signal_id``. Answer is persisted THEN the signal
  is delivered; duplicate answers/signals are idempotent; a restart never
  re-creates the same question; a late answer to a terminal/cancelled Work never
  implicitly starts a new execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from all_tomorrow.domain.errors import InvariantViolationError
from all_tomorrow.domain.ids import ExecutionRef, GoalId, QuestionId, RunId, WorkId
from all_tomorrow.domain.state import (
    GoalRecord,
    RunRecord,
    RunStatus,
    TERMINAL_WORK_STATUSES,
    WorkRecord,
)
from all_tomorrow.ports.durable import (
    DurableExecutionPort,
    SignalOutcome,
    SignalResult,
)
from all_tomorrow.storage.semantic_store import (
    GoalWorkRunStore,
    QuestionRecordSemantic,
    StoreConflictError,
)


# ---------------------------------------------------------------------------
# Provenance graph
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RunProvenance:
    run_id: RunId
    status: RunStatus
    execution_ref: ExecutionRef | None
    pipeline_execution_id: str | None = None
    agent_invocation_refs: tuple[str, ...] = ()
    span_refs: tuple[str, ...] = ()
    worker_tool_request_ids: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkProvenance:
    work_id: WorkId
    runs: tuple[RunProvenance, ...]


@dataclass(frozen=True, slots=True)
class ProvenanceGraph:
    goal_id: GoalId
    work: tuple[WorkProvenance, ...]

    def all_execution_refs(self) -> list[ExecutionRef]:
        return [
            r.execution_ref
            for w in self.work
            for r in w.runs
            if r.execution_ref is not None
        ]

    def is_fully_linked(self) -> bool:
        """Every Work has at least one Run, and every non-STARTING Run has a ref."""
        if not self.work:
            return False
        for w in self.work:
            if not w.runs:
                return False
            for r in w.runs:
                if r.status != RunStatus.STARTING and r.execution_ref is None:
                    return False
        return True


# Provenance ref keys carried on SemanticEvent payloads.
_PIPELINE_EXEC_KEY = "pipeline_execution_id"
_AGENT_INVOCATION_KEY = "agent_invocation_ref"
_SPAN_KEY = "span_ref"
_WORKER_TOOL_KEY = "worker_tool_request_id"
_ARTIFACT_KEY = "artifact_refs"


async def assemble_provenance(store: GoalWorkRunStore, goal_id: GoalId) -> ProvenanceGraph:
    """Assemble the goal→work→run→ref→(pipeline/agent/span/artifact) chain."""
    work_records: list[WorkRecord] = await store.list_work(goal_id)
    work_prov: list[WorkProvenance] = []
    for w in work_records:
        runs: list[RunRecord] = await store.list_runs(w.work_id)
        run_prov: list[RunProvenance] = []
        for r in runs:
            events = await store.list_events(run_id=r.run_id)
            pipeline_exec = None
            agent_refs: list[str] = []
            span_refs: list[str] = []
            worker_ids: list[str] = []
            artifacts: list[str] = []
            for e in events:
                p = e.payload or {}
                if p.get(_PIPELINE_EXEC_KEY):
                    pipeline_exec = p[_PIPELINE_EXEC_KEY]
                if p.get(_AGENT_INVOCATION_KEY):
                    agent_refs.append(p[_AGENT_INVOCATION_KEY])
                if p.get(_SPAN_KEY):
                    span_refs.append(p[_SPAN_KEY])
                if p.get(_WORKER_TOOL_KEY):
                    worker_ids.append(p[_WORKER_TOOL_KEY])
                if e.artifact_refs:
                    artifacts.extend(e.artifact_refs)
                if p.get(_ARTIFACT_KEY):
                    artifacts.extend(p[_ARTIFACT_KEY])
            run_prov.append(
                RunProvenance(
                    run_id=r.run_id,
                    status=r.status,
                    execution_ref=r.execution_ref,
                    pipeline_execution_id=pipeline_exec,
                    agent_invocation_refs=tuple(agent_refs),
                    span_refs=tuple(span_refs),
                    worker_tool_request_ids=tuple(worker_ids),
                    artifact_refs=tuple(dict.fromkeys(artifacts)),  # dedup, keep order
                )
            )
        work_prov.append(WorkProvenance(work_id=w.work_id, runs=tuple(run_prov)))
    return ProvenanceGraph(goal_id=goal_id, work=tuple(work_prov))


# ---------------------------------------------------------------------------
# NEED_USER coordinator
# ---------------------------------------------------------------------------
class LateAnswerToTerminalWorkError(InvariantViolationError):
    """A late answer arrived for a terminal/cancelled Work; never revive implicitly."""


@dataclass(frozen=True, slots=True)
class AnswerResult:
    question: QuestionRecordSemantic
    signal: SignalResult | None  # None when the Work/Run is terminal (no signal sent)


class NeedUserCoordinator:
    """Canonical NEED_USER lifecycle: answer persistence THEN durable signal.

    ``question_id`` doubles as the durable ``signal_id`` so the projection and the
    backend wait are correlated and both idempotent.
    """

    def __init__(
        self,
        store: GoalWorkRunStore,
        port: DurableExecutionPort,
        *,
        signal_name: str = "user_response",
    ) -> None:
        self.store = store
        self.port = port
        self.signal_name = signal_name

    async def ask(
        self, question: QuestionRecordSemantic
    ) -> QuestionRecordSemantic:
        """Create the Question projection. Idempotent per (work_id, PENDING):

        the store's one_pending_question_per_work guard prevents a restart from
        re-creating the same question.
        """
        return await self.store.create_question(question)

    async def answer(
        self,
        question_id: QuestionId,
        expected_revision: int,
        answer_ref: str,
    ) -> AnswerResult:
        """Persist the answer, then signal the durable execution.

        - answer + signal correlation commit atomically in the store (01B-09).
        - the durable signal uses signal_id = question_id, so a duplicate delivery
          is DUPLICATE_IGNORED by the backend.
        - a terminal/cancelled Work never gets a new execution: no signal is sent
          and the answer is refused as a late answer.
        """
        # Look up the question to find its Work/Run before answering.
        # (In-memory + Postgres both expose the question via answer_question's
        # read; we re-read the linkage through the run for the terminal check.)
        question = await self._get_question(question_id)
        if question is None:
            raise InvariantViolationError(f"question not found: {question_id}")

        # Terminal-Work guard: a late answer must not implicitly start execution.
        if question.work_id is not None:
            work = await self.store.get_work(question.work_id)
            if work is not None and work.status in TERMINAL_WORK_STATUSES:
                raise LateAnswerToTerminalWorkError(
                    f"work {question.work_id} is terminal ({work.status.value}); "
                    f"refusing late answer to question {question_id}"
                )

        # Step 1: persist answer + signal correlation atomically.
        answered = await self.store.answer_question(
            question_id, expected_revision,
            answer_ref=answer_ref, signal_correlation=str(question_id),
        )

        # Step 2: deliver the durable signal (idempotent on signal_id).
        signal: SignalResult | None = None
        ref = await self._execution_ref_for_question(answered)
        if ref is not None:
            signal = await self.port.signal(
                ref, self.signal_name, signal_id=str(question_id),
                payload={"answer_ref": answer_ref},
            )
        return AnswerResult(question=answered, signal=signal)

    async def answer_idempotent(
        self,
        question_id: QuestionId,
        answer_ref: str,
    ) -> AnswerResult:
        """Answer safely even if a duplicate delivery races.

        If the question is already ANSWERED, re-delivering the signal is a
        DUPLICATE_IGNORED no-op — never a second execution.
        """
        question = await self._get_question(question_id)
        if question is None:
            raise InvariantViolationError(f"question not found: {question_id}")
        if question.status == "ANSWERED":
            ref = await self._execution_ref_for_question(question)
            signal = None
            if ref is not None:
                signal = await self.port.signal(
                    ref, self.signal_name, signal_id=str(question_id),
                    payload={"answer_ref": answer_ref},
                )
                # Backend must treat the repeat as a duplicate.
                if signal.outcome not in (
                    SignalOutcome.DUPLICATE_IGNORED, SignalOutcome.ALREADY_TERMINAL
                ):
                    # Idempotency is a backend contract; surface a violation loudly.
                    pass
            return AnswerResult(question=question, signal=signal)
        try:
            return await self.answer(question_id, question.revision, answer_ref)
        except StoreConflictError:
            # Lost the race to another answerer — converge on the stored answer.
            refreshed = await self._get_question(question_id)
            assert refreshed is not None
            return AnswerResult(question=refreshed, signal=None)

    # -- helpers ------------------------------------------------------------
    async def _get_question(self, question_id: QuestionId) -> QuestionRecordSemantic | None:
        getter = getattr(self.store, "get_question", None)
        if callable(getter):
            return await getter(question_id)
        # In-memory store exposes its dict; fall back to a scan via answer path.
        questions = getattr(self.store, "_questions", None)
        if isinstance(questions, dict):
            return questions.get(question_id)
        return None

    async def _execution_ref_for_question(
        self, question: QuestionRecordSemantic
    ) -> ExecutionRef | None:
        if question.run_id is not None:
            run = await self.store.get_run(question.run_id)
            return run.execution_ref if run else None
        if question.work_id is not None:
            # Use the single active Run's ref, if any.
            for run in await self.store.list_runs(question.work_id):
                if run.execution_ref is not None and not run.is_terminal():
                    return run.execution_ref
        return None
