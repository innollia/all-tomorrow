from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Callable, Coroutine

from all_tomorrow.delivery import (
    DeliveryKind,
    DeliveryRecord,
    DeliveryReconciler,
    DeliveryStatus,
    format_idempotency_key,
    utc_now,
)
from all_tomorrow.domain.artifacts import ArtifactRef, compute_content_hash
from all_tomorrow.domain.errors import (
    ActiveRunLimitExceededError,
    CanonicalError,
    ErrorCategory,
    InvalidStateTransitionError,
    InvariantViolationError,
    MissingCompletionEvidenceError,
    TerminalReviveError,
)
from all_tomorrow.domain.events import EventRecord
from all_tomorrow.domain.ids import (
    ExecutionRef,
    GoalId,
    OutcomeId,
    ProjectId,
    QuestionId,
    RequestId,
    RunId,
    WorkId,
    new_delivery_id,
    new_event_id,
    new_goal_id,
    new_outcome_id,
    new_question_id,
    new_run_id,
    new_work_id,
)
from all_tomorrow.domain.outcomes import (
    CompletionEvidence,
    OutcomeRecord,
    OutcomeStatus,
    TargetType,
    verify_completion_evidence,
)
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
from all_tomorrow.ports.agent import (
    AgentExecutionPort,
    AgentExecutionRequest,
    AgentExecutionResult,
)
from all_tomorrow.ports.durable import (
    CancelOutcome,
    CancelResult,
    DurableExecutionPort,
    DurableExecutionState,
    ExecutionResult,
    ExecutionStatusResult,
    SignalOutcome,
    SignalResult,
)
from all_tomorrow.ports.tools import (
    SideEffectClass,
    ToolDescriptor,
    ToolExecutionPort,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from all_tomorrow.ports.workers import (
    WorkerDescriptor,
    WorkerExecutionPort,
    WorkerExecutionRequest,
    WorkerExecutionResult,
)
from all_tomorrow.storage.artifact_store import LocalArtifactStore
from all_tomorrow.storage.delivery_store import DeliveryStore


class WalkingSkeletonOrchestrator:
    """End-to-end Failure Walking Skeleton Orchestrator for 00C.
    
    Implements the complete canonical pipeline:
    user request
    → Goal/Work
    → Run STARTING commit
    → durable execution start + ExecutionRef attach
    → PydanticAI agent / model invocation
    → worker/tool call
    → durable NEED_USER wait
    → Question projection
    → user signal
    → resume
    → ArtifactRef/result 기록
    → Run/Work completion
    """

    def __init__(
        self,
        durable_port: DurableExecutionPort,
        agent_port: AgentExecutionPort,
        delivery_store: DeliveryStore,
        artifact_store: LocalArtifactStore,
        tool_port: ToolExecutionPort | None = None,
        worker_port: WorkerExecutionPort | None = None,
    ) -> None:
        self.durable_port = durable_port
        self.agent_port = agent_port
        self.delivery_store = delivery_store
        self.artifact_store = artifact_store
        self.tool_port = tool_port
        self.worker_port = worker_port
        self.reconciler = DeliveryReconciler(durable_port)

        # In-memory storage for active test orchestrations
        self.goals: dict[GoalId, GoalRecord] = {}
        self.works: dict[WorkId, WorkRecord] = {}
        self.runs: dict[RunId, RunRecord] = {}
        self.questions: dict[QuestionId, dict[str, Any]] = {}
        self.events: list[EventRecord] = []
        self.artifacts: dict[str, ArtifactRef] = {}

    async def initiate_goal_and_work(
        self,
        user_id: str,
        goal_title: str,
        work_title: str,
    ) -> tuple[GoalRecord, WorkRecord]:
        goal_id = new_goal_id()
        goal = GoalRecord(goal_id=goal_id, user_id=user_id, title=goal_title, status=GoalStatus.ACTIVE)
        self.goals[goal_id] = goal

        work_id = new_work_id()
        work = WorkRecord(work_id=work_id, goal_id=goal_id, title=work_title, status=WorkStatus.PENDING)
        self.works[work_id] = work
        return goal, work

    async def create_starting_run(
        self,
        work_id: WorkId,
        workflow_name: str = "walking_skeleton_workflow",
        workflow_payload: dict[str, Any] | None = None,
    ) -> tuple[RunRecord, DeliveryRecord]:
        work = self.works[work_id]
        if work.status == WorkStatus.PENDING:
            work = transition_work(work, WorkStatus.RUNNING)
            self.works[work_id] = work

        run_id = new_run_id()
        run = RunRecord(run_id=run_id, work_id=work_id, status=RunStatus.STARTING)
        assert_active_runs_invariant([run], max_active=1)

        idmp_key = format_idempotency_key("run", "start", str(run_id))
        intent = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": str(run_id), "work_id": str(work_id)},
            destination_adapter=getattr(self.durable_port, "backend_name", "durable"),
            idempotency_key=idmp_key,
            payload={
                "workflow_name": workflow_name,
                "workflow_payload": workflow_payload or {},
            },
        )

        async def _save_run() -> RunRecord:
            self.runs[run_id] = run
            return run

        saved_run, committed_intent = await self.delivery_store.atomic_app_transaction(intent, _save_run)
        return saved_run, committed_intent

    async def reconcile_run_start(self, run_id: RunId, intent: DeliveryRecord) -> tuple[RunRecord, ExecutionRef]:
        reconciled_delivery = await self.reconciler.reconcile(intent)
        if reconciled_delivery.status != DeliveryStatus.DELIVERED:
            raise RuntimeError(f"Delivery failed with status {reconciled_delivery.status}: {reconciled_delivery.last_error}")

        exec_ref = await self.durable_port.find_by_run_id(run_id)
        if exec_ref is None:
            raise RuntimeError(f"ExecutionRef not found for started run {run_id}")

        run = self.runs[run_id]
        running_run = transition_run(run, RunStatus.RUNNING, execution_ref=exec_ref)
        self.runs[run_id] = running_run
        return running_run, exec_ref

    async def execute_agent_step(
        self,
        run_id: RunId,
        prompt: str,
        model_route: str = "fixture",
        toolset: str = "all-tomorrow-tools",
    ) -> AgentExecutionResult:
        run = self.runs[run_id]
        if run.status != RunStatus.RUNNING:
            raise InvalidStateTransitionError(f"Run must be RUNNING to execute agent step, got {run.status}")

        req = AgentExecutionRequest(
            model_route_ref=model_route,
            toolset_ref=toolset,
            prompt=prompt,
        )
        return await self.agent_port.execute(req)

    async def suspend_need_user(
        self,
        run_id: RunId,
        question_text: str,
        options: list[str] | None = None,
    ) -> QuestionId:
        run = self.runs[run_id]
        work = self.works[run.work_id]

        waiting_run = transition_run(run, RunStatus.WAITING)
        self.runs[run_id] = waiting_run

        waiting_work = transition_work(work, WorkStatus.WAITING)
        self.works[run.work_id] = waiting_work

        q_id = new_question_id()
        self.questions[q_id] = {
            "question_id": q_id,
            "work_id": run.work_id,
            "run_id": run_id,
            "question": question_text,
            "options": options or [],
            "status": "PENDING",
            "created_at": utc_now(),
        }
        return q_id

    async def resume_with_user_signal(
        self,
        run_id: RunId,
        question_id: QuestionId,
        signal_id: str,
        answer_payload: dict[str, Any],
    ) -> RunRecord:
        run = self.runs[run_id]
        work = self.works[run.work_id]
        if run.execution_ref is None:
            raise RuntimeError(f"Run {run_id} missing execution_ref")

        # Project Question answered
        if question_id in self.questions:
            self.questions[question_id]["status"] = "ANSWERED"
            self.questions[question_id]["answer"] = answer_payload

        # Send durable signal
        sig_res = await self.durable_port.signal(
            ref=run.execution_ref,
            signal_name="user_response",
            signal_id=signal_id,
            payload=answer_payload,
        )
        if sig_res.outcome not in (SignalOutcome.DELIVERED, SignalOutcome.DUPLICATE_IGNORED):
            raise RuntimeError(f"Signal delivery failed: {sig_res.outcome}")

        # Transition back to RUNNING
        resumed_run = transition_run(run, RunStatus.RUNNING)
        self.runs[run_id] = resumed_run

        resumed_work = transition_work(work, WorkStatus.RUNNING)
        self.works[run.work_id] = resumed_work
        return resumed_run

    async def record_artifact(
        self,
        run_id: RunId,
        content: bytes | str,
        media_type: str = "application/json",
    ) -> ArtifactRef:
        ref = await self.artifact_store.store(content, media_type=media_type)
        self.artifacts[str(ref.artifact_id)] = ref
        return ref

    async def complete_run_and_work(
        self,
        run_id: RunId,
        result_payload: Any,
        completion_evidence: CompletionEvidence,
    ) -> tuple[RunRecord, WorkRecord]:
        run = self.runs[run_id]
        work = self.works[run.work_id]

        completed_run = transition_run(run, RunStatus.SUCCEEDED)
        self.runs[run_id] = completed_run

        completed_work = transition_work(work, WorkStatus.SUCCEEDED, evidence=completion_evidence)
        self.works[run.work_id] = completed_work
        return completed_run, completed_work
