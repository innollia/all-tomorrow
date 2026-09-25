from __future__ import annotations

import asyncio
import json
import os
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
from all_tomorrow.observability import CorrelationContext, TelemetryManager
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
from all_tomorrow.storage.run_store import RunConflictError


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
        database_url: str | None = None,
        tool_port: ToolExecutionPort | None = None,
        worker_port: WorkerExecutionPort | None = None,
        telemetry: TelemetryManager | None = None,
    ) -> None:
        self.durable_port = durable_port
        self.agent_port = agent_port
        self.delivery_store = delivery_store
        self.artifact_store = artifact_store
        self.database_url = database_url or os.environ.get("AT_TEST_POSTGRES_URL")
        self.tool_port = tool_port
        self.worker_port = worker_port
        self.reconciler = DeliveryReconciler(durable_port)
        self.telemetry = telemetry or (
            TelemetryManager.get_or_create(os.environ.get("AT_TEST_OTEL_SPANS"))
            if os.environ.get("AT_TEST_OTEL_SPANS")
            else None
        )
        self.active_spans: dict[RunId, Any] = {}
        self.correlation_contexts: dict[RunId, CorrelationContext] = {}

        # In-memory mirror for fast active test access
        self.goals: dict[GoalId, GoalRecord] = {}
        self.works: dict[WorkId, WorkRecord] = {}
        self.runs: dict[RunId, RunRecord] = {}
        self.questions: dict[QuestionId, dict[str, Any]] = {}
        self.events: list[EventRecord] = []
        self.artifacts: dict[str, ArtifactRef] = {}

        if self.database_url:
            self._init_postgres()

    def _get_connection(self):
        import psycopg
        if not self.database_url:
            raise RuntimeError("No database_url configured for orchestrator")
        return psycopg.connect(self.database_url)

    def _init_postgres(self) -> None:
        """Create application-owned domain tables in PostgreSQL.
        Maintains strict boundary: never touches dbos.* tables!
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.at_goals (
                        goal_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.at_works (
                        work_id TEXT PRIMARY KEY,
                        goal_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL,
                        evidence JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.at_runs (
                        run_id TEXT PRIMARY KEY,
                        work_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        execution_ref JSONB,
                        attempt_number INT NOT NULL DEFAULT 1,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.at_questions (
                        question_id TEXT PRIMARY KEY,
                        work_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        question TEXT NOT NULL,
                        options JSONB NOT NULL DEFAULT '[]'::jsonb,
                        status TEXT NOT NULL,
                        answer JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        answered_at TIMESTAMPTZ
                    )
                    """
                )
            conn.commit()

    def _persist_goal(self, goal: GoalRecord) -> None:
        if not self.database_url:
            return
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.at_goals (goal_id, user_id, title, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (goal_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (str(goal.goal_id), goal.user_id, goal.title, goal.status.value, goal.created_at, goal.updated_at),
                )
            conn.commit()

    def _persist_work(self, work: WorkRecord, evidence: CompletionEvidence | None = None) -> None:
        if not self.database_url:
            return
        import psycopg
        from dataclasses import asdict
        evidence_dict = asdict(evidence) if evidence else None
        if evidence and evidence.observed_values:
            evidence_dict.update(evidence.observed_values)
        evidence_data = json.loads(json.dumps(evidence_dict, default=str)) if evidence_dict else None
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.at_works (work_id, goal_id, title, status, evidence, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (work_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        evidence = COALESCE(EXCLUDED.evidence, at_works.evidence),
                        updated_at = EXCLUDED.updated_at
                    """,
                    (str(work.work_id), str(work.goal_id), work.title, work.status.value, psycopg.types.json.Jsonb(evidence_data) if evidence_data else None, work.created_at, work.updated_at),
                )
            conn.commit()

    def _persist_run(self, run: RunRecord) -> None:
        if not self.database_url:
            return
        import psycopg
        ref_json = None
        if run.execution_ref:
            ref_json = {
                "backend": run.execution_ref.backend,
                "execution_id": run.execution_ref.execution_id,
                "execution_version": run.execution_ref.execution_version,
                "attached_at": run.execution_ref.attached_at.isoformat() if run.execution_ref.attached_at else None,
                "metadata": run.execution_ref.metadata,
            }
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.at_runs (run_id, work_id, status, execution_ref, attempt_number, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        execution_ref = COALESCE(at_runs.execution_ref, EXCLUDED.execution_ref),
                        attempt_number = EXCLUDED.attempt_number,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (str(run.run_id), str(run.work_id), run.status.value, psycopg.types.json.Jsonb(ref_json) if ref_json else None, getattr(run, "attempt_number", 1), run.created_at, run.updated_at),
                )
            conn.commit()

    def _persist_question(self, q: dict[str, Any]) -> None:
        if not self.database_url:
            return
        import psycopg
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.at_questions (question_id, work_id, run_id, question, options, status, answer, created_at, answered_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (question_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        answer = EXCLUDED.answer,
                        answered_at = EXCLUDED.answered_at
                    """,
                    (
                        str(q["question_id"]), str(q["work_id"]), str(q["run_id"]),
                        q["question"], psycopg.types.json.Jsonb(q.get("options", [])),
                        q["status"], psycopg.types.json.Jsonb(q.get("answer")) if q.get("answer") else None,
                        q["created_at"], q.get("answered_at"),
                    ),
                )
            conn.commit()

    async def initiate_goal_and_work(
        self,
        user_id: str,
        goal_title: str,
        work_title: str,
    ) -> tuple[GoalRecord, WorkRecord]:
        goal_id = new_goal_id()
        goal = GoalRecord(goal_id=goal_id, user_id=user_id, title=goal_title, status=GoalStatus.ACTIVE)
        self.goals[goal_id] = goal
        self._persist_goal(goal)

        work_id = new_work_id()
        work = WorkRecord(work_id=work_id, goal_id=goal_id, title=work_title, status=WorkStatus.PENDING)
        self.works[work_id] = work
        self._persist_work(work)
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
            self._persist_work(work)

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
            self._persist_run(run)
            return run

        saved_run, committed_intent = await self.delivery_store.atomic_app_transaction(intent, _save_run)

        if self.telemetry:
            corr_ctx = CorrelationContext(
                goal_id=str(work.goal_id),
                work_id=str(work_id),
                run_id=str(run_id),
                trace_id=f"trace-{run_id}",
            )
            self.correlation_contexts[run_id] = corr_ctx
            root_span = self.telemetry.start_root_span(
                name="orchestrator_run",
                context=corr_ctx,
            )
            self.active_spans[run_id] = root_span

        return saved_run, committed_intent

    def cas_attach_execution_ref(self, run_id: RunId, exec_ref: ExecutionRef) -> bool:
        """S0-00B3-02 / C-09: Atomic Compare-And-Swap execution_ref attachment in PostgreSQL.

        Guarantees:
        - If execution_ref IS NULL, attaches exec_ref and transitions status to RUNNING.
        - If execution_ref already matches exec_ref.execution_id, converges idempotently (returns True).
        - If execution_ref is already attached to a DIFFERENT execution_id, strictly fails closed
          by raising RunConflictError, forbidding divergent execution attachment.
        """
        import psycopg
        from all_tomorrow.storage.run_store import RunConflictError

        ref_json = {
            "backend": exec_ref.backend,
            "execution_id": exec_ref.execution_id,
            "execution_version": exec_ref.execution_version,
            "attached_at": exec_ref.attached_at.isoformat() if exec_ref.attached_at else None,
            "metadata": exec_ref.metadata,
        }

        if not self.database_url:
            run = self.runs.get(run_id)
            if run is not None:
                if run.execution_ref is not None and run.execution_ref.execution_id != exec_ref.execution_id:
                    raise RunConflictError(
                        f"CAS conflict on run {run_id}: existing execution_id '{run.execution_ref.execution_id}' != '{exec_ref.execution_id}'"
                    )
                self.runs[run_id] = transition_run(run, RunStatus.RUNNING, execution_ref=exec_ref)
                if self.telemetry and run_id in self.correlation_contexts:
                    self.correlation_contexts[run_id].execution_id = exec_ref.execution_id
                    if run_id in self.active_spans:
                        self.active_spans[run_id].set_attribute("all_tomorrow.execution_id", exec_ref.execution_id)
                return True
            return False

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.at_runs
                    SET status = 'RUNNING',
                        execution_ref = %s,
                        updated_at = NOW()
                    WHERE run_id = %s
                      AND (execution_ref IS NULL OR (execution_ref->>'execution_id') = %s)
                    RETURNING run_id, execution_ref
                    """,
                    (psycopg.types.json.Jsonb(ref_json), str(run_id), exec_ref.execution_id),
                )
                row = cur.fetchone()
                conn.commit()

                if row is not None:
                    if run_id in self.runs:
                        self.runs[run_id] = transition_run(self.runs[run_id], RunStatus.RUNNING, execution_ref=exec_ref)
                    if self.telemetry and run_id in self.correlation_contexts:
                        self.correlation_contexts[run_id].execution_id = exec_ref.execution_id
                        if run_id in self.active_spans:
                            self.active_spans[run_id].set_attribute("all_tomorrow.execution_id", exec_ref.execution_id)
                    return True

                cur.execute("SELECT execution_ref FROM public.at_runs WHERE run_id = %s", (str(run_id),))
                existing_row = cur.fetchone()
                existing_ref = existing_row[0] if existing_row else None
                existing_exec_id = existing_ref.get("execution_id") if isinstance(existing_ref, dict) else None

                raise RunConflictError(
                    f"CAS conflict on run {run_id}: existing execution_id '{existing_exec_id}' conflicts with divergent '{exec_ref.execution_id}'"
                )

    async def reconcile_run_start(self, run_id: RunId, intent: DeliveryRecord) -> tuple[RunRecord, ExecutionRef]:
        reconciled_delivery = await self.reconciler.reconcile(intent)
        if reconciled_delivery.status != DeliveryStatus.DELIVERED:
            raise RuntimeError(f"Delivery failed with status {reconciled_delivery.status}: {reconciled_delivery.last_error}")

        exec_ref = await self.durable_port.find_by_run_id(run_id)
        if exec_ref is None:
            raise RuntimeError(f"ExecutionRef not found for started run {run_id}")

        self.cas_attach_execution_ref(run_id, exec_ref)
        run = self.runs.get(run_id)
        if run is None and self.database_url:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT run_id, work_id, status FROM public.at_runs WHERE run_id = %s", (str(run_id),))
                    row = cur.fetchone()
                    if row:
                        run = RunRecord(run_id=RunId(row[0]), work_id=WorkId(row[1]), status=RunStatus(row[2]), execution_ref=exec_ref)
                        self.runs[run_id] = run
        return run or self.runs[run_id], exec_ref

    async def supervise_worker_process(
        self,
        run_id: RunId,
        command: list[str],
        timeout_seconds: float = 1.0,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> tuple[int | None, bool]:
        """C-07: Product supervisor execution path with timeout, process cleanup, and failure evidence.

        Guarantees:
        - Monitors worker process execution subject to timeout deadline.
        - On timeout:
          1. Kills child worker process and reaps it (resource cleanup).
          2. Normalizes timeout exception to ErrorCategory.TIMEOUT.
          3. Transitions Run to FAILED and persists to PostgreSQL at_runs.
          4. Transitions Work to FAILED with CompletionEvidence and persists to PostgreSQL at_works.
          5. Preserves Goal in ACTIVE status (never cancelled or lost).
          6. Emits OTel span recording timeout event.
        - Returns (child_pid, completed_within_timeout).
        """
        import asyncio
        import os
        from all_tomorrow.error_normalization import normalize_exception

        run = self.runs.get(run_id)
        if run is None and self.database_url:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT run_id, work_id, status FROM public.at_runs WHERE run_id = %s", (str(run_id),))
                    row = cur.fetchone()
                    if row:
                        run = RunRecord(run_id=RunId(row[0]), work_id=WorkId(row[1]), status=RunStatus(row[2]))
                        self.runs[run_id] = run
        if run is None:
            raise RuntimeError(f"Run {run_id} not found for supervision")

        work = self.works.get(run.work_id)
        if work is None and self.database_url:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT work_id, goal_id, title, status FROM public.at_works WHERE work_id = %s", (str(run.work_id),))
                    row = cur.fetchone()
                    if row:
                        work = WorkRecord(work_id=WorkId(row[0]), goal_id=GoalId(row[1]), title=row[2], status=WorkStatus(row[3]))
                        self.works[run.work_id] = work
        if work is None:
            raise RuntimeError(f"Work {run.work_id} not found for supervision")

        exec_env = {**os.environ, **(env or {})}
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=exec_env,
            cwd=cwd,
        )
        child_pid = proc.pid

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
            return child_pid, True
        except asyncio.TimeoutError:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except (ProcessLookupError, OSError):
                pass

            canonical = normalize_exception(TimeoutError(f"Worker process {child_pid} timed out after {timeout_seconds}s deadline"))

            evidence = CompletionEvidence(
                criterion_ref="worker_deadline",
                evaluator_ref="supervisor",
                evaluator_version="1.0",
                observed_values={
                    "error_code": canonical.code,
                    "error_category": canonical.category.value,
                },
            )

            failed_run = transition_run(run, RunStatus.FAILED)
            self.runs[run_id] = failed_run
            self._persist_run(failed_run)

            failed_work = transition_work(work, WorkStatus.FAILED, evidence=evidence)
            self.works[work.work_id] = failed_work
            self._persist_work(failed_work, evidence=evidence)

            span_path = exec_env.get("AT_TEST_OTEL_SPANS") or os.environ.get("AT_TEST_OTEL_SPANS")
            if span_path:
                try:
                    from tests.support.otel_file_exporter import tracer_for
                    tracer = tracer_for(span_path)
                    with tracer.start_as_current_span("worker_timeout") as span:
                        span.set_attribute("error", True)
                        span.set_attribute("error.category", canonical.category.value)
                        span.set_attribute("all_tomorrow.run_id", str(run_id))
                        span.set_attribute("all_tomorrow.work_id", str(work.work_id))
                        span.set_attribute("all_tomorrow.worker_pid", child_pid)
                except Exception:
                    pass

            return child_pid, False

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

        agent_span = None
        if self.telemetry and run_id in self.active_spans:
            corr = self.correlation_contexts.get(run_id)
            agent_span = self.telemetry.start_child_span(
                name="agent_execution_step",
                parent_span=self.active_spans[run_id],
                context=corr,
                extra_attributes={
                    "all_tomorrow.model_route": model_route,
                    "all_tomorrow.toolset_ref": toolset,
                },
            )

        try:
            req = AgentExecutionRequest(
                model_route_ref=model_route,
                toolset_ref=toolset,
                prompt=prompt,
            )
            return await self.agent_port.execute(req)
        finally:
            if agent_span:
                agent_span.end()

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
        self._persist_run(waiting_run)

        waiting_work = transition_work(work, WorkStatus.WAITING)
        self.works[run.work_id] = waiting_work
        self._persist_work(waiting_work)

        q_id = new_question_id()
        q_record = {
            "question_id": q_id,
            "work_id": run.work_id,
            "run_id": run_id,
            "question": question_text,
            "options": options or [],
            "status": "PENDING",
            "created_at": utc_now(),
        }
        self.questions[q_id] = q_record
        self._persist_question(q_record)
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
            self.questions[question_id]["answered_at"] = utc_now()
            self._persist_question(self.questions[question_id])

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
        self._persist_run(resumed_run)

        resumed_work = transition_work(work, WorkStatus.RUNNING)
        self.works[run.work_id] = resumed_work
        self._persist_work(resumed_work)
        return resumed_run

    async def record_artifact(
        self,
        run_id: RunId,
        content: bytes | str,
        media_type: str = "application/json",
    ) -> ArtifactRef:
        ref = await self.artifact_store.store(content, media_type=media_type)
        self.artifacts[str(ref.artifact_id)] = ref

        if self.telemetry and run_id in self.active_spans:
            corr = self.correlation_contexts.get(run_id)
            if corr:
                corr.artifact_ref = str(ref.artifact_id)
            art_span = self.telemetry.start_child_span(
                name="record_artifact",
                parent_span=self.active_spans[run_id],
                context=corr,
                extra_attributes={
                    "all_tomorrow.artifact_id": str(ref.artifact_id),
                    "all_tomorrow.media_type": media_type,
                    "all_tomorrow.content_hash": ref.content_hash,
                },
            )
            art_span.end()

        return ref

    async def complete_run_and_work(
        self,
        run_id: RunId,
        result_payload: Any,
        completion_evidence: CompletionEvidence,
    ) -> tuple[RunRecord, WorkRecord]:
        run = self.runs[run_id]
        work = self.works[run.work_id]

        if self.telemetry and run_id in self.active_spans:
            corr = self.correlation_contexts.get(run_id)
            comp_span = self.telemetry.start_child_span(
                name="complete_run",
                parent_span=self.active_spans[run_id],
                context=corr,
                extra_attributes={
                    "all_tomorrow.outcome_status": "SUCCEEDED",
                    "all_tomorrow.criterion_ref": completion_evidence.criterion_ref,
                },
            )
            comp_span.end()
            root_span = self.active_spans.pop(run_id, None)
            if root_span:
                root_span.end()

        completed_run = transition_run(run, RunStatus.SUCCEEDED)
        self.runs[run_id] = completed_run
        self._persist_run(completed_run)

        completed_work = transition_work(work, WorkStatus.SUCCEEDED, evidence=completion_evidence)
        self.works[run.work_id] = completed_work
        self._persist_work(completed_work, evidence=completion_evidence)
        return completed_run, completed_work
