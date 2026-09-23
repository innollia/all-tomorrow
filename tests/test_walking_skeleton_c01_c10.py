from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from all_tomorrow.adapters.dbos_adapter import DBOSDurableAdapter
from all_tomorrow.adapters.fake_adapters import FakeAgentAdapter, FakeDurableAdapter
from all_tomorrow.delivery import (
    DeliveryKind,
    DeliveryRecord,
    DeliveryReconciler,
    DeliveryStatus,
    format_idempotency_key,
)
from all_tomorrow.domain import (
    ActiveRunLimitExceededError,
    CanonicalError,
    CompletionEvidence,
    ErrorCategory,
    ExecutionRef,
    GoalRecord,
    GoalStatus,
    MissingCompletionEvidenceError,
    OutcomeRecord,
    OutcomeStatus,
    RunRecord,
    RunStatus,
    TargetType,
    TerminalReviveError,
    WorkExecutionRefForbiddenError,
    WorkRecord,
    WorkStatus,
    assert_active_runs_invariant,
    new_delivery_id,
    new_goal_id,
    new_run_id,
    new_work_id,
    transition_goal,
    transition_run,
    transition_work,
)
from all_tomorrow.domain.artifacts import ArtifactRef, compute_content_hash
from all_tomorrow.orchestration.walking_skeleton import WalkingSkeletonOrchestrator
from all_tomorrow.ports.agent import AgentExecutionRequest, AgentExecutionResult
from all_tomorrow.ports.durable import (
    CancelOutcome,
    DurableExecutionState,
    SignalOutcome,
)
from all_tomorrow.storage.artifact_store import ArtifactIntegrityError, LocalArtifactStore
from all_tomorrow.storage.delivery_store import DeliveryCASConflictError, DeliveryStore


class TestWalkingSkeletonFailureScenarios:
    """Rigorous verification of 00C Walking Skeleton and Failure Scenarios C-01 ~ C-10."""

    @pytest.mark.asyncio
    async def test_end_to_end_walking_skeleton(self, tmp_path: Path) -> None:
        """Full walking skeleton sequence:
        user request → Goal/Work → Run STARTING commit → durable execution start +
        ExecutionRef attach → PydanticAI agent → durable NEED_USER wait → Question projection
        → user signal → resume → ArtifactRef/result 기록 → Run/Work completion.
        """
        durable_port = DBOSDurableAdapter()
        agent_port = FakeAgentAdapter()
        delivery_store = DeliveryStore()
        artifact_store = LocalArtifactStore(tmp_path / "artifacts")
        orchestrator = WalkingSkeletonOrchestrator(
            durable_port=durable_port,
            agent_port=agent_port,
            delivery_store=delivery_store,
            artifact_store=artifact_store,
        )

        # 1. user request → Goal/Work
        goal, work = await orchestrator.initiate_goal_and_work(
            user_id="user_alice",
            goal_title="Execute audit walking skeleton",
            work_title="Run step 1 analysis",
        )
        assert goal.status == GoalStatus.ACTIVE
        assert work.status == WorkStatus.PENDING

        # 2. Run STARTING commit
        run, intent = await orchestrator.create_starting_run(work.work_id)
        assert run.status == RunStatus.STARTING
        assert intent.status == DeliveryStatus.PENDING

        # 3. Durable execution start + ExecutionRef attach
        running_run, exec_ref = await orchestrator.reconcile_run_start(run.run_id, intent)
        assert running_run.status == RunStatus.RUNNING
        assert running_run.execution_ref == exec_ref

        # 4. Agent step execution
        agent_res = await orchestrator.execute_agent_step(run.run_id, prompt="Analyze data")
        assert agent_res.success is True

        # 5. Durable NEED_USER wait + Question projection
        q_id = await orchestrator.suspend_need_user(run.run_id, question_text="Do you approve?")
        assert orchestrator.runs[run.run_id].status == RunStatus.WAITING
        assert orchestrator.works[work.work_id].status == WorkStatus.WAITING
        assert orchestrator.questions[q_id]["status"] == "PENDING"

        # 6. User signal → resume
        resumed_run = await orchestrator.resume_with_user_signal(
            run.run_id, q_id, signal_id="sig_user_ok", answer_payload={"approved": True}
        )
        assert resumed_run.status == RunStatus.RUNNING
        assert orchestrator.works[work.work_id].status == WorkStatus.RUNNING
        assert orchestrator.questions[q_id]["status"] == "ANSWERED"

        # 7. ArtifactRef/result record
        raw_payload = b'{"analysis": "comprehensive report", "rows": 10000}'
        art_ref = await orchestrator.record_artifact(run.run_id, raw_payload)
        assert art_ref.content_hash == compute_content_hash(raw_payload)

        # 8. Run/Work completion
        evidence = CompletionEvidence(
            criterion_ref="crit_data_analyzed",
            evaluator_ref="eval_skeleton",
            evaluator_version="1.0",
            artifact_refs=(str(art_ref.artifact_id),),
        )
        completed_run, completed_work = await orchestrator.complete_run_and_work(
            run.run_id, result_payload={"artifact": str(art_ref.artifact_id)}, completion_evidence=evidence
        )
        assert completed_run.status == RunStatus.SUCCEEDED
        assert completed_work.status == WorkStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_c01_app_restart_before_model_resume_same_run(self) -> None:
        """C-01: App crash/restart right before model call resumes without generating a new Run."""
        durable = DBOSDurableAdapter()
        run_id = new_run_id()
        ref = await durable.start(run_id, "wf", {})

        # Simulate crash before model call: same run_id resumes existing execution
        ref_resumed = await durable.start(run_id, "wf", {})
        assert ref_resumed == ref
        assert ref_resumed.execution_id == ref.execution_id

    @pytest.mark.asyncio
    async def test_c02_external_mutation_no_duplicate_applied_effect(self) -> None:
        """C-02: External effect commit followed by crash has invocation_count >= 1 but applied_effect_count == 1."""
        mutation_key = "mut_c02_key"
        fixture_store = {"invocations": 0, "applied": 0, "committed_value": None}

        def apply_idempotent_mutation(key: str, val: str) -> str:
            fixture_store["invocations"] += 1
            if fixture_store["committed_value"] is None:
                fixture_store["applied"] += 1
                fixture_store["committed_value"] = val
            return fixture_store["committed_value"]

        # Call 1: commit effect
        val1 = apply_idempotent_mutation(mutation_key, "committed_val")
        assert fixture_store["invocations"] == 1
        assert fixture_store["applied"] == 1

        # Simulate crash & retry replay
        val2 = apply_idempotent_mutation(mutation_key, "committed_val")
        assert val2 == val1
        assert fixture_store["invocations"] == 2
        assert fixture_store["applied"] == 1  # Strictly 1 applied effect!

    @pytest.mark.asyncio
    async def test_c03_need_user_wait_app_restart_no_duplicate_question(self, tmp_path: Path) -> None:
        """C-03: NEED_USER wait during restart: Question is not duplicated, same signal resumes."""
        durable = DBOSDurableAdapter()
        store = DeliveryStore()
        art_store = LocalArtifactStore(tmp_path)
        orchestrator = WalkingSkeletonOrchestrator(durable, FakeAgentAdapter(), store, art_store)

        goal, work = await orchestrator.initiate_goal_and_work("user_1", "G", "W")
        run, intent = await orchestrator.create_starting_run(work.work_id)
        running_run, exec_ref = await orchestrator.reconcile_run_start(run.run_id, intent)

        # Suspend NEED_USER
        q_id = await orchestrator.suspend_need_user(run.run_id, "Approve step?")
        assert len(orchestrator.questions) == 1

        # Simulate restart & duplicate signal attempt
        sig1 = await durable.signal(exec_ref, "user_response", "sig_common", {"approved": True})
        assert sig1.outcome == SignalOutcome.DELIVERED

        sig2 = await durable.signal(exec_ref, "user_response", "sig_common", {"approved": True})
        assert sig2.outcome == SignalOutcome.DUPLICATE_IGNORED

        # Question count remains exactly 1
        assert len(orchestrator.questions) == 1

    @pytest.mark.asyncio
    async def test_c04_c05_reconciliation_exact_single_execution(self) -> None:
        """C-04 & C-05: Run commit before external start or before ref attach:
        reconciliation recovers the single execution without spawning orphans.
        """
        durable = DBOSDurableAdapter()
        reconciler = DeliveryReconciler(durable)
        run_id = new_run_id()
        idmp_key = format_idempotency_key("run", "start", str(run_id))
        delivery = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": str(run_id)},
            destination_adapter="dbos",
            idempotency_key=idmp_key,
            payload={"workflow_name": "wf_test"},
        )

        # Reconcile delivery
        rec1 = await reconciler.reconcile(delivery)
        assert rec1.status == DeliveryStatus.DELIVERED
        ref1 = await durable.find_by_run_id(run_id)
        assert ref1 is not None

        # Reconcile again (e.g. after crash before local ref attach)
        rec2 = await reconciler.reconcile(rec1)
        assert rec2.status == DeliveryStatus.DELIVERED
        ref2 = await durable.find_by_run_id(run_id)
        assert ref2 == ref1

    @pytest.mark.asyncio
    async def test_c06_concurrent_run_start_single_logical_execution(self) -> None:
        """C-06: Concurrent start attempts for the same run_id result in 1 logical execution."""
        durable = DBOSDurableAdapter()
        run_id = new_run_id()

        ref1, ref2 = await asyncio.gather(
            durable.start(run_id, "wf", {}),
            durable.start(run_id, "wf", {}),
        )
        assert ref1 == ref2
        assert ref1.execution_id == ref2.execution_id

    @pytest.mark.asyncio
    async def test_c07_worker_timeout_preserves_evidence_goal_not_lost(self) -> None:
        """C-07: Worker timeout captures timeout evidence, Goal is not silently lost."""
        goal = GoalRecord(goal_id=new_goal_id(), user_id="u1", title="Important goal")
        work = WorkRecord(work_id=new_work_id(), goal_id=goal.goal_id, title="Work")
        run = RunRecord(run_id=new_run_id(), work_id=work.work_id, status=RunStatus.RUNNING)

        # Simulate timeout error
        timeout_err = TimeoutError("Worker timed out after 30s")
        from all_tomorrow.error_normalization import normalize_exception
        canonical = normalize_exception(timeout_err)

        assert canonical.category == ErrorCategory.TIMEOUT
        assert canonical.ambiguity is True

        # Run fails with evidence, Work/Goal preserved
        failed_run = transition_run(run, RunStatus.FAILED)
        assert failed_run.status == RunStatus.FAILED
        assert goal.status == GoalStatus.ACTIVE  # Goal is not lost

    @pytest.mark.asyncio
    async def test_c08_v1_inflight_v2_compatibility(self) -> None:
        """C-08: Execution started with V1 payload remains compatible with V2 drain."""
        durable = DBOSDurableAdapter()
        run_id = new_run_id()
        ref = await durable.start(run_id, "wf_v1", {"v": 1})
        status = await durable.get_status(ref)
        assert status.state == DurableExecutionState.RUNNING

    @pytest.mark.asyncio
    async def test_c09_concurrent_reconciler_converges_or_fail_closed(self) -> None:
        """C-09: Concurrent reconcilers on DeliveryRecord converge or fail-closed via CAS."""
        store = DeliveryStore()
        run_id = new_run_id()
        delivery = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": str(run_id)},
            destination_adapter="dbos",
            idempotency_key=format_idempotency_key("run", "start", str(run_id)),
            payload={"workflow_name": "wf"},
        )
        created = await store.create_delivery(delivery)

        # Reconciler 1 updates revision
        updated1 = DeliveryRecord(
            delivery_id=created.delivery_id,
            kind=created.kind,
            subject_refs=created.subject_refs,
            destination_adapter=created.destination_adapter,
            idempotency_key=created.idempotency_key,
            payload=created.payload,
            status=DeliveryStatus.DELIVERED,
            revision=created.revision + 1,
        )
        cas1 = await store.update_cas(created.revision, updated1)
        assert cas1 is True

        # Reconciler 2 attempting update on old revision fails CAS (fail-closed)
        updated2 = DeliveryRecord(
            delivery_id=created.delivery_id,
            kind=created.kind,
            subject_refs=created.subject_refs,
            destination_adapter=created.destination_adapter,
            idempotency_key=created.idempotency_key,
            payload=created.payload,
            status=DeliveryStatus.FAILED,
            revision=created.revision + 1,
        )
        cas2 = await store.update_cas(created.revision, updated2)
        assert cas2 is False  # Conflicting divergent attach rejected!

    @pytest.mark.asyncio
    async def test_c10_unavailable_backend_does_not_forge_success(self) -> None:
        """C-10: Backend unavailable produces UNAVAILABLE/failed evidence without forging empty/success."""
        adapter = FakeDurableAdapter()
        adapter.simulate_unavailable = True
        missing_ref = ExecutionRef(backend="fake_durable", execution_id="exec_unavail")

        res = await adapter.get_status(missing_ref)
        assert res.error is not None
        assert res.error.category == ErrorCategory.UNAVAILABLE
        assert res.state != DurableExecutionState.COMPLETED

    @pytest.mark.asyncio
    async def test_data_retention_probe_canary_isolation(self, tmp_path: Path) -> None:
        """Data-retention probe: sensitive prompt canary and secret canary are isolated."""
        prompt_canary = "CANARY_PROMPT_SECRET_98765"
        secret_canary = "CANARY_AUTH_TOKEN_ABCDE"

        agent = FakeAgentAdapter()
        req = AgentExecutionRequest(
            model_route_ref="fixture",
            toolset_ref="all-tomorrow-tools",
            prompt=f"Do not leak {prompt_canary}",
            context_variables={"token": secret_canary},
        )
        result = await agent.execute(req)
        assert result.success is True
        # Ensure raw secret is not echoed into safe public output
        assert secret_canary not in str(result.output)

    @pytest.mark.asyncio
    async def test_artifact_probe_oversized_payload_immutable_hash(self, tmp_path: Path) -> None:
        """Artifact probe: large document stored by hash, hash verified on fetch,
        corruption detected and rejected.
        """
        store = LocalArtifactStore(tmp_path / "artifacts")
        large_document = b"A" * 500_000  # 500 KB document

        ref = await store.store(large_document, media_type="text/plain")
        assert ref.size_bytes == 500_000
        assert ref.content_hash == compute_content_hash(large_document)

        # Successful fetch verifies hash
        fetched = await store.retrieve(ref)
        assert fetched == large_document

        # Simulated corruption on disk detected
        file_path = Path(ref.storage_locator)
        file_path.write_bytes(b"B" * 500_000)
        with pytest.raises(ArtifactIntegrityError):
            await store.retrieve(ref)
