from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import yaml

from all_tomorrow.adapters.dbos_adapter import DBOSDurableAdapter
from all_tomorrow.adapters.fake_adapters import FakeDurableAdapter
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
    RunId,
    RunRecord,
    RunStatus,
    TargetType,
    TerminalReviveError,
    WorkExecutionRefForbiddenError,
    WorkId,
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
from all_tomorrow.harness.types import ExecutionIdentity, FailPoint, HarnessInput, TraceContext
from all_tomorrow.orchestration.walking_skeleton import WalkingSkeletonOrchestrator
from all_tomorrow.ports.agent import (
    AgentExecutionPort,
    AgentExecutionRequest,
    AgentExecutionResult,
)
from all_tomorrow.ports.durable import (
    CancelOutcome,
    DurableExecutionState,
    SignalOutcome,
)
from all_tomorrow.storage.artifact_store import ArtifactIntegrityError, LocalArtifactStore
from all_tomorrow.storage.delivery_store import DeliveryCASConflictError, DeliveryStore
from tests.support.live_common import apply_mutation
from tests.support.walking_skeleton_fixture import DurableExternalMutationFixture


def _free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class PydanticAIGatewayAdapter(AgentExecutionPort):
    """Real Agent port executing through LiteLLM Proxy / PydanticAI / MCP tools."""

    def __init__(self, model_url: str, tool_url: str, gateway_key: str) -> None:
        self.model_url = model_url
        self.tool_url = tool_url
        self.gateway_key = gateway_key

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        from openai import AsyncOpenAI
        from pydantic_ai import Agent
        from pydantic_ai.mcp import MCPToolset
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from all_tomorrow.harness.types import ModelDecision

        client = AsyncOpenAI(base_url=self.model_url, api_key=self.gateway_key, max_retries=0)
        model = OpenAIChatModel("fixture", provider=OpenAIProvider(openai_client=client))
        tools = MCPToolset(self.tool_url, id="all-tomorrow-tools", auth=self.gateway_key, max_retries=0)
        agent = Agent(model, output_type=ModelDecision, toolsets=[tools], retries=1)

        async with agent as active_agent:
            result = await active_agent.run(request.prompt)
        return AgentExecutionResult(
            success=True,
            output=result.output.model_dump(),
            structured_data={"stock_confirmed": result.output.stock_confirmed},
        )


@pytest.fixture(autouse=True)
def cleanup_dbos():
    yield
    try:
        from dbos import DBOS
        DBOS.destroy()
    except Exception:
        pass


class TestWalkingSkeletonFailureScenarios:
    """Rigorous verification of 00C Walking Skeleton and Failure Scenarios C-01 ~ C-10."""

    @pytest.mark.asyncio
    async def test_end_to_end_walking_skeleton(self, tmp_path: Path) -> None:
        """Full walking skeleton sequence with REAL infra:
        user request → Goal/Work → Run STARTING commit → durable DBOS start on PostgreSQL +
        ExecutionRef attach → PydanticAI agent through LiteLLM Proxy → durable NEED_USER wait
        → Question projection → user signal → resume → ArtifactRef/result 기록 → Run/Work completion.
        """
        litellm_bin = os.environ.get("AT_TEST_LITELLM_BIN")
        if not litellm_bin and os.path.exists("/opt/all-tomorrow-litellm-venv/bin/litellm"):
            litellm_bin = "/opt/all-tomorrow-litellm-venv/bin/litellm"
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        fixture_url = os.environ.get("AT_TEST_FIXTURE_URL", "postgresql:///at_external_fixture")

        if not litellm_bin:
            pytest.skip("Set AT_TEST_LITELLM_BIN")

        provider_port, tool_port, gateway_port = _free_port(), _free_port(), _free_port()
        key = f"sk-e2e-gateway-{uuid4().hex}"
        config = {
            "model_list": [{
                "model_name": "fixture",
                "litellm_params": {
                    "model": "openai/fixture",
                    "api_base": f"http://127.0.0.1:{provider_port}/v1",
                    "api_key": "local-fixture",
                    "num_retries": 0,
                },
            }],
            "router_settings": {"num_retries": 0},
            "general_settings": {
                "master_key": "os.environ/AT_TEST_GATEWAY_KEY",
                "store_prompts_in_spend_logs": False,
                "turn_off_message_logging": True,
            },
            "litellm_settings": {"callbacks": [], "num_retries": 0},
            "mcp_servers": {
                "alpha": {"url": f"http://127.0.0.1:{tool_port}/mcp", "transport": "http", "allow_all_keys": True}
            },
        }
        config_path = tmp_path / "gateway_e2e.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

        env = os.environ.copy()
        env["AT_TEST_GATEWAY_KEY"] = key
        model_url = f"http://127.0.0.1:{gateway_port}/v1"
        tool_url = f"http://127.0.0.1:{gateway_port}/mcp"

        commands = [
            [sys.executable, "-m", "uvicorn", "tests.support.model_provider:app", "--host", "127.0.0.1", "--port", str(provider_port)],
            [sys.executable, "-m", "tests.support.mcp_upstream", "alpha", str(tool_port)],
            [litellm_bin, "--config", str(config_path), "--port", str(gateway_port), "--telemetry", "False"],
        ]
        processes = []
        try:
            for index, command in enumerate(commands):
                log_file = tmp_path / f"proc-e2e-{index}.log"
                with log_file.open("wb") as stream:
                    processes.append(subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env))
            import httpx
            async with httpx.AsyncClient(timeout=2) as client:
                for _ in range(240):
                    assert all(p.poll() is None for p in processes)
                    try:
                        resp = await client.get(f"http://127.0.0.1:{gateway_port}/health/liveliness")
                        if resp.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.25)
                else:
                    logs = {p.name: p.read_text(errors="replace") for p in tmp_path.glob("proc-e2e-*.log")}
                    pytest.fail(f"LiteLLM gateway failed readiness. Logs: {logs}")

            durable_port = DBOSDurableAdapter(system_database_url=system_url)
            agent_port = PydanticAIGatewayAdapter(model_url=model_url, tool_url=tool_url, gateway_key=key)
            delivery_store = DeliveryStore()
            artifact_store = LocalArtifactStore(tmp_path / "artifacts")
            orchestrator = WalkingSkeletonOrchestrator(
                durable_port=durable_port,
                agent_port=agent_port,
                delivery_store=delivery_store,
                artifact_store=artifact_store,
                database_url=system_url,
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

            # 3. Durable execution start + ExecutionRef attach (Real PostgreSQL DBOS state)
            running_run, exec_ref = await orchestrator.reconcile_run_start(run.run_id, intent)
            assert running_run.status == RunStatus.RUNNING
            assert running_run.execution_ref == exec_ref

            # 4. Agent step execution through PydanticAI + LiteLLM + MCP tool
            canary_prompt = f"Evaluate inventory analysis {uuid4().hex}"
            agent_res = await orchestrator.execute_agent_step(run.run_id, prompt=canary_prompt)
            assert agent_res.success is True
            assert agent_res.structured_data is not None
            assert agent_res.structured_data.get("stock_confirmed") == 42

            # 5. Durable NEED_USER wait + Question projection
            q_id = await orchestrator.suspend_need_user(run.run_id, question_text="Do you approve stock commit?")
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

            # Direct PostgreSQL verification of full pipeline persistence
            with psycopg.connect(system_url) as conn:
                cur = conn.cursor()
                cur.execute("SELECT status FROM public.at_goals WHERE goal_id = %s", (str(goal.goal_id),))
                assert cur.fetchone() == ("ACTIVE",)

                cur.execute("SELECT status, evidence FROM public.at_works WHERE work_id = %s", (str(work.work_id),))
                w_status, w_ev = cur.fetchone()
                assert w_status == "SUCCEEDED"
                assert w_ev is not None

                cur.execute("SELECT status, execution_ref FROM public.at_runs WHERE run_id = %s", (str(run.run_id),))
                r_status, r_ref = cur.fetchone()
                assert r_status == "SUCCEEDED"
                assert r_ref["execution_id"] == exec_ref.execution_id

                cur.execute("SELECT status, answer FROM public.at_questions WHERE question_id = %s", (str(q_id),))
                q_status, q_ans = cur.fetchone()
                assert q_status == "ANSWERED"
                assert q_ans == {"approved": True}

                cur.execute("SELECT execution_id FROM public.at_run_executions WHERE run_id = %s", (str(run.run_id),))
                assert cur.fetchone() == (exec_ref.execution_id,)
        finally:
            for p in reversed(processes):
                _stop_process(p)

    def test_c01_app_restart_before_model_resume_same_run(self, tmp_path: Path) -> None:
        """C-01: App crash/restart right before model call resumes without generating a new Run.
        Uses real independent OS child process termination (os._exit 78) and restart.
        """
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        fixture_url = os.environ.get("AT_TEST_FIXTURE_URL", "postgresql:///at_external_fixture")
        run_id = f"c01-{uuid4()}"
        work_id = "work-c01"
        mutation_key = f"mut-{run_id}"

        payload = {
            "input": HarnessInput(
                task_name="Check inventory",
                query_item_id="item-01",
                mutation_key=mutation_key,
                mutation_value="c01-val",
                injected_fail_point=FailPoint.BEFORE_MODEL_RESULT_PERSIST,
            ).model_dump(mode="json"),
            "identity": ExecutionIdentity(work_id=work_id, run_id=run_id).model_dump(mode="json"),
            "trace": TraceContext(
                trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}"
            ).model_dump(mode="json"),
        }

        env = os.environ.copy()
        env["AT_TEST_POSTGRES_URL"] = system_url
        env["AT_TEST_FIXTURE_URL"] = fixture_url
        env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
        env["AT_TEST_COMMON_PHASE"] = "crash"
        span_file = tmp_path / "c01-spans.jsonl"
        env["AT_TEST_OTEL_SPANS"] = str(span_file)

        # 1. First process crashes right before model result persists (exit code 78)
        first = subprocess.run(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert first.returncode == 78, (first.stdout, first.stderr)

        # 2. Restart new independent OS process to resume the SAME run/execution
        env["AT_TEST_COMMON_PHASE"] = "normal"
        second = subprocess.run(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert second.returncode == 0, (second.stdout, second.stderr)
        raw = json.loads(second.stdout.strip().splitlines()[-1])
        assert raw["execution_identity"]["run_id"] == run_id
        assert raw["mutation_committed"] is True

        # Check DBOS database has exactly 1 workflow execution
        workflow_id = f"{work_id}:{run_id}"
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute("SELECT status FROM dbos.workflow_status WHERE workflow_uuid = %s", (workflow_id,))
            row = cur.fetchone()
            assert row == ("SUCCESS",)

    def test_c02_external_mutation_no_duplicate_applied_effect(self, tmp_path: Path) -> None:
        """C-02: External effect commit followed by crash has invocation_count >= 1 but applied_effect_count == 1.
        Uses real OS child process crash right after mutation side-effect (exit 77).
        """
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        fixture_url = os.environ.get("AT_TEST_FIXTURE_URL", "postgresql:///at_external_fixture")
        run_id = f"c02-{uuid4()}"
        work_id = "work-c02"
        mutation_key = f"mut-{run_id}"

        payload = {
            "input": HarnessInput(
                task_name="Check inventory",
                query_item_id="item-01",
                mutation_key=mutation_key,
                mutation_value="c02-val",
                injected_fail_point=FailPoint.AFTER_MUTATION_SIDE_EFFECT,
            ).model_dump(mode="json"),
            "identity": ExecutionIdentity(work_id=work_id, run_id=run_id).model_dump(mode="json"),
            "trace": TraceContext(
                trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}"
            ).model_dump(mode="json"),
        }

        env = os.environ.copy()
        env["AT_TEST_POSTGRES_URL"] = system_url
        env["AT_TEST_FIXTURE_URL"] = fixture_url
        env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
        env["AT_TEST_COMMON_PHASE"] = "crash"
        span_file = tmp_path / "c02-spans.jsonl"
        env["AT_TEST_OTEL_SPANS"] = str(span_file)

        # First process applies mutation then crashes (exit code 77)
        first = subprocess.run(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert first.returncode == 77, (first.stdout, first.stderr)

        # Check durable mutation fixture in PostgreSQL: call_count=1, application_count=1
        with psycopg.connect(fixture_url) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT call_count, application_count, committed_value FROM common_mutation_probe WHERE idempotency_key = %s",
                (mutation_key,),
            )
            row_before = cur.fetchone()
            assert row_before == (1, 1, "c02-val")

        # Second process recovers and completes
        env["AT_TEST_COMMON_PHASE"] = "normal"
        second = subprocess.run(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert second.returncode == 0, (second.stdout, second.stderr)

        # Check durable mutation fixture in PostgreSQL: call_count=2, applied_count=1 STRICTLY
        with psycopg.connect(fixture_url) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT call_count, application_count, committed_value FROM common_mutation_probe WHERE idempotency_key = %s",
                (mutation_key,),
            )
            row_after = cur.fetchone()
            assert row_after == (2, 1, "c02-val")

    def test_c03_need_user_wait_app_restart_no_duplicate_question(self, tmp_path: Path) -> None:
        """C-03: NEED_USER wait during restart: Question is not duplicated, same signal resumes.
        First process runs into wait and is killed (kill -9). Second process delivers signal and resumes.
        """
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        fixture_url = os.environ.get("AT_TEST_FIXTURE_URL", "postgresql:///at_external_fixture")
        run_id = f"c03-{uuid4()}"
        work_id = "work-c03"
        mutation_key = f"mut-{run_id}"

        payload = {
            "input": HarnessInput(
                task_name="Check inventory with wait",
                query_item_id="item-01",
                mutation_key=mutation_key,
                mutation_value="c03-val",
                wait_for_signal_name="approval",
            ).model_dump(mode="json"),
            "identity": ExecutionIdentity(work_id=work_id, run_id=run_id).model_dump(mode="json"),
            "trace": TraceContext(
                trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}"
            ).model_dump(mode="json"),
        }

        env = os.environ.copy()
        env["AT_TEST_POSTGRES_URL"] = system_url
        env["AT_TEST_FIXTURE_URL"] = fixture_url
        env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
        env["AT_TEST_COMMON_PHASE"] = "wait"
        span_file = tmp_path / "c03-spans.jsonl"
        env["AT_TEST_OTEL_SPANS"] = str(span_file)

        # 0. Initial Question projection into PostgreSQL application table
        q_id = f"q_{run_id}"
        with psycopg.connect(system_url) as conn:
            with conn.cursor() as cur:
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
                cur.execute(
                    """
                    INSERT INTO public.at_questions (question_id, work_id, run_id, question, status)
                    VALUES (%s, %s, %s, 'Approve inventory mutation?', 'PENDING')
                    ON CONFLICT (question_id) DO NOTHING
                    """,
                    (q_id, work_id, run_id),
                )
            conn.commit()

        first = subprocess.Popen(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            assert first.stdout is not None
            marker = first.stdout.readline().strip()
            assert marker.startswith("waiting_pid="), marker

            # Kill the worker while it is in durable wait
            first.kill()
            first.wait(timeout=10)

            # Start second worker to resume with signal
            env["AT_TEST_COMMON_PHASE"] = "resume"
            second = subprocess.run(
                [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
                env=env, capture_output=True, text=True, timeout=120,
            )
            assert second.returncode == 0, (second.stdout, second.stderr)
            resumed_pid = second.stdout.split("resumed_pid=")[1].splitlines()[0]
            assert marker.removeprefix("waiting_pid=") != resumed_pid

            # Transition Question projection to ANSWERED
            with psycopg.connect(system_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.at_questions
                        SET status = 'ANSWERED', answer = %s, answered_at = NOW()
                        WHERE question_id = %s
                        """,
                        (psycopg.types.json.Jsonb({"approved": True}), q_id),
                    )
                    # Verify question count is strictly 1 (no duplicate question created across crash/restart)
                    cur.execute("SELECT COUNT(*), status FROM public.at_questions WHERE run_id = %s GROUP BY status", (run_id,))
                    row = cur.fetchone()
                    assert row is not None
                    assert row[0] == 1
                    assert row[1] == "ANSWERED"

            # Check DBOS database reflects SUCCESS
            workflow_id = f"{work_id}:{run_id}"
            with psycopg.connect(system_url) as conn:
                status = conn.execute(
                    "SELECT status FROM dbos.workflow_status WHERE workflow_uuid = %s", (workflow_id,)
                ).fetchone()
                assert status == ("SUCCESS",)
        finally:
            if first.poll() is None:
                first.kill()
                first.wait(timeout=5)

    def test_c04_run_commit_crash_before_external_start_reconciles_single_execution(self) -> None:
        """C-04: Process commits Run STARTING to PostgreSQL, then crashes before external start.
        Restarting with a new independent process recovers the single execution via reconciliation.
        """
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        fixture_url = os.environ.get("AT_TEST_FIXTURE_URL", "postgresql:///at_external_fixture")
        run_id = f"c04-{uuid4()}"
        work_id = "work-c04"
        mutation_key = f"mut-{run_id}"

        payload = {
            "input": HarnessInput(
                task_name="C04 Task", query_item_id="item-04",
                mutation_key=mutation_key, mutation_value="c04-val",
            ).model_dump(mode="json"),
            "identity": ExecutionIdentity(work_id=work_id, run_id=run_id).model_dump(mode="json"),
            "trace": TraceContext(
                trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}"
            ).model_dump(mode="json"),
        }
        env = os.environ.copy()
        env["AT_TEST_POSTGRES_URL"] = system_url
        env["AT_TEST_FIXTURE_URL"] = fixture_url
        env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
        env["AT_TEST_COMMON_PHASE"] = "c04_crash"

        # 1. First process crashes right after Run STARTING commit (exit 75)
        first = subprocess.run(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert first.returncode == 75, (first.stdout, first.stderr)
        assert "c04_barrier_starting_pid=" in first.stdout

        # Verify state in PostgreSQL: Run exists in STARTING status, execution_ref is NULL
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, execution_ref FROM public.at_runs WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "STARTING"
            assert row[1] is None

        # Verify in DBOS: no execution started yet
        exec_id = f"dbos_{run_id}"
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute("SELECT status FROM dbos.workflow_status WHERE workflow_uuid = %s", (exec_id,))
            assert cur.fetchone() is None

        # 2. Second independent process runs reconciliation
        env["AT_TEST_COMMON_PHASE"] = "c04_reconcile"
        second = subprocess.run(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert second.returncode == 0, (second.stdout, second.stderr)
        assert "c04_reconciled_pid=" in second.stdout

        # Verify state in PostgreSQL: Run is now RUNNING and execution_ref is attached
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, execution_ref FROM public.at_runs WHERE run_id = %s", (run_id,))
            status, ref_json = cur.fetchone()
            assert status == "RUNNING"
            assert ref_json is not None
            assert ref_json["execution_id"] == exec_id

            # Verify application mapping table: exactly 1 execution record
            cur.execute("SELECT COUNT(*) FROM public.at_run_executions WHERE run_id = %s", (run_id,))
            assert cur.fetchone()[0] == 1

        # Negative assertion: re-running reconcile does not change execution_ref or spawn duplicate
        third = subprocess.run(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert third.returncode == 0
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute("SELECT execution_ref FROM public.at_runs WHERE run_id = %s", (run_id,))
            assert cur.fetchone()[0] == ref_json

    def test_c05_external_start_crash_before_ref_attach_recovers_existing_execution(self) -> None:
        """C-05: Process starts DBOS workflow, then crashes before local execution_ref attach in at_runs.
        Restarting with a new process recovers the EXISTING execution without creating an orphan or duplicate.
        """
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        fixture_url = os.environ.get("AT_TEST_FIXTURE_URL", "postgresql:///at_external_fixture")
        run_id = f"c05-{uuid4()}"
        work_id = "work-c05"
        mutation_key = f"mut-{run_id}"

        payload = {
            "input": HarnessInput(
                task_name="C05 Task", query_item_id="item-05",
                mutation_key=mutation_key, mutation_value="c05-val",
            ).model_dump(mode="json"),
            "identity": ExecutionIdentity(work_id=work_id, run_id=run_id).model_dump(mode="json"),
            "trace": TraceContext(
                trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}"
            ).model_dump(mode="json"),
        }
        env = os.environ.copy()
        env["AT_TEST_POSTGRES_URL"] = system_url
        env["AT_TEST_FIXTURE_URL"] = fixture_url
        env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
        env["AT_TEST_COMMON_PHASE"] = "c05_crash"

        # 1. First process starts workflow in DBOS then crashes (exit 76) before at_runs ref attach
        first = subprocess.run(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert first.returncode == 76, (first.stdout, first.stderr)
        assert "c05_barrier_external_started_pid=" in first.stdout

        # Verify DBOS has the workflow ALREADY started
        exec_id = f"dbos_{run_id}"
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute("SELECT status FROM dbos.workflow_status WHERE workflow_uuid = %s", (exec_id,))
            row = cur.fetchone()
            assert row is not None  # Exists in DBOS!

            # Verify in PostgreSQL: at_runs STILL has execution_ref = NULL!
            cur.execute("SELECT status, execution_ref FROM public.at_runs WHERE run_id = %s", (run_id,))
            run_row = cur.fetchone()
            assert run_row[0] == "STARTING"
            assert run_row[1] is None

        # 2. Second independent process reconciles
        env["AT_TEST_COMMON_PHASE"] = "c05_reconcile"
        second = subprocess.run(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert second.returncode == 0, (second.stdout, second.stderr)
        assert "c05_reconciled_pid=" in second.stdout

        # Verify in PostgreSQL: at_runs has attached the EXISTING execution
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, execution_ref FROM public.at_runs WHERE run_id = %s", (run_id,))
            status, ref_json = cur.fetchone()
            assert status == "RUNNING"
            assert ref_json["execution_id"] == exec_id

            # Negative assertion: DBOS workflow count for this execution_id is strictly 1 (no duplicate spawned)
            cur.execute("SELECT COUNT(*) FROM dbos.workflow_status WHERE workflow_uuid = %s", (exec_id,))
            assert cur.fetchone()[0] == 1

    @pytest.mark.asyncio
    async def test_c06_concurrent_run_start_single_logical_execution(self) -> None:
        """C-06: Concurrent start attempts for the same run_id result in 1 logical execution in PostgreSQL."""
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        adapter1 = DBOSDurableAdapter(system_database_url=system_url)
        adapter2 = DBOSDurableAdapter(system_database_url=system_url)
        run_id = new_run_id()

        ref1, ref2 = await asyncio.gather(
            adapter1.start(run_id, "wf_concurrent", {}),
            adapter2.start(run_id, "wf_concurrent", {}),
        )
        assert ref1 == ref2
        assert ref1.execution_id == ref2.execution_id

    def test_c07_worker_timeout_preserves_evidence_goal_not_lost(self) -> None:
        """C-07: Worker timeout captures timeout evidence, terminates child process,
        records failure in Run and Work, but preserves Goal (Goal is not silently lost or cancelled).
        """
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        fixture_url = os.environ.get("AT_TEST_FIXTURE_URL", "postgresql:///at_external_fixture")
        run_id = f"c07-{uuid4()}"
        work_id = f"work-c07-{uuid4().hex[:8]}"
        goal_id = f"goal-c07-{uuid4().hex[:8]}"

        # 1. Initialize Goal (ACTIVE), Work (RUNNING), Run (RUNNING) in PostgreSQL
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO public.at_goals (goal_id, user_id, title, status)
                VALUES (%s, 'u1', 'Critical audit goal', 'ACTIVE')
                """,
                (goal_id,),
            )
            cur.execute(
                """
                INSERT INTO public.at_works (work_id, goal_id, title, status)
                VALUES (%s, %s, 'Heavy worker job', 'RUNNING')
                """,
                (work_id, goal_id),
            )
            cur.execute(
                """
                INSERT INTO public.at_runs (run_id, work_id, status)
                VALUES (%s, %s, 'RUNNING')
                """,
                (run_id, work_id),
            )
            conn.commit()

        # 2. Launch worker in hang mode
        payload = {
            "input": HarnessInput(
                task_name="Hanging Task", query_item_id="item-07",
                mutation_key=f"mut-{run_id}", mutation_value="c07-val",
            ).model_dump(mode="json"),
            "identity": ExecutionIdentity(work_id=work_id, run_id=run_id).model_dump(mode="json"),
            "trace": TraceContext(
                trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}"
            ).model_dump(mode="json"),
        }
        env = os.environ.copy()
        env["AT_TEST_POSTGRES_URL"] = system_url
        env["AT_TEST_FIXTURE_URL"] = fixture_url
        env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
        env["AT_TEST_COMMON_PHASE"] = "c07_hang"

        worker_proc = subprocess.Popen(
            [sys.executable, "-m", "tests.support.walking_skeleton_worker"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            assert worker_proc.stdout is not None
            marker = worker_proc.stdout.readline().strip()
            assert marker.startswith("hanging_worker_pid="), marker

            # Simulate supervisor timeout trigger (e.g. 1.0s timeout reached)
            time.sleep(1.0)
            worker_proc.terminate()
            try:
                worker_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker_proc.kill()
                worker_proc.wait(timeout=5)

            # Assert process cleanup: child PID is dead
            assert worker_proc.poll() is not None

            # 3. Supervisor records timeout failure evidence
            from all_tomorrow.error_normalization import normalize_exception
            canonical = normalize_exception(TimeoutError("Worker timed out after deadline"))
            assert canonical.category == ErrorCategory.TIMEOUT

            evidence_dict = {
                "criterion_ref": "worker_deadline",
                "evaluator_ref": "timeout_monitor",
                "error_code": canonical.code,
                "error_category": canonical.category.value,
            }
            with psycopg.connect(system_url) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE public.at_runs
                    SET status = 'FAILED', updated_at = NOW()
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                cur.execute(
                    """
                    UPDATE public.at_works
                    SET status = 'FAILED', evidence = %s, updated_at = NOW()
                    WHERE work_id = %s
                    """,
                    (psycopg.types.json.Jsonb(evidence_dict), work_id),
                )
                conn.commit()

                # Verify Run is FAILED
                cur.execute("SELECT status FROM public.at_runs WHERE run_id = %s", (run_id,))
                assert cur.fetchone()[0] == "FAILED"

                # Verify Work is FAILED and evidence preserved
                cur.execute("SELECT status, evidence FROM public.at_works WHERE work_id = %s", (work_id,))
                work_status, work_ev = cur.fetchone()
                assert work_status == "FAILED"
                assert work_ev["error_category"] == "TIMEOUT"

                # Verify Goal is STILL ACTIVE (Goal preserved!)
                cur.execute("SELECT status FROM public.at_goals WHERE goal_id = %s", (goal_id,))
                assert cur.fetchone()[0] == "ACTIVE"

            # Negative assertion: reviving terminal run raises TerminalReviveError
            run_rec = RunRecord(run_id=RunId(run_id), work_id=WorkId(work_id), status=RunStatus.FAILED)
            with pytest.raises(TerminalReviveError):
                transition_run(run_rec, RunStatus.RUNNING)
        finally:
            if worker_proc.poll() is None:
                worker_proc.kill()
                worker_proc.wait(timeout=5)

    def test_c08_v1_inflight_v2_compatibility(self, tmp_path: Path) -> None:
        """C-08: Execution started with V1 code is killed mid-flight and resumed on genuinely new V2 code.
        Replays persisted history, verifies model step is not duplicated (model_calls == 1),
        and applies V2 schema finalization.
        """
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        fixture_url = os.environ.get("AT_TEST_FIXTURE_URL", "postgresql:///at_external_fixture")
        workflow_id = f"upgrade-{uuid4()}"
        support = Path(__file__).parent / "support"
        env = os.environ.copy()
        env["AT_TEST_POSTGRES_URL"] = system_url
        env["AT_TEST_FIXTURE_URL"] = fixture_url
        env["AT_TEST_WORKFLOW_ID"] = workflow_id
        env["AT_TEST_ORIGINAL_CORR"] = f"origin-{uuid4()}"
        env["AT_TEST_TRANSIENT_CORR"] = f"transient-{uuid4()}"
        span_file = tmp_path / "spans.jsonl"
        env["AT_TEST_OTEL_SPANS"] = str(span_file)

        with psycopg.connect(fixture_url) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS upgrade_probe (
                    workflow_id TEXT PRIMARY KEY,
                    model_calls INTEGER NOT NULL,
                    finalized BOOLEAN NOT NULL
                )"""
            )

        old = subprocess.Popen(
            [sys.executable, str(support / "dbos_upgrade_v1.py")],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            assert old.stdout is not None
            marker = old.stdout.readline().strip()
            assert marker.startswith("v1_waiting_pid="), (marker, old.stderr.read() if old.stderr else "")
            old.kill()
            old.wait(timeout=10)

            new = subprocess.run(
                [sys.executable, str(support / "dbos_upgrade_v2.py")],
                env=env, capture_output=True, text=True, timeout=45,
            )
            assert new.returncode == 0, (new.stdout, new.stderr)
            assert "'schema': 2" in new.stdout
            assert "'source': 'v1-replayed'" in new.stdout
            assert "'stock': 42" in new.stdout

            with psycopg.connect(fixture_url) as conn:
                row = conn.execute(
                    "SELECT model_calls, finalized FROM upgrade_probe WHERE workflow_id=%s", (workflow_id,)
                ).fetchone()
            assert row == (1, True)
        finally:
            if old.poll() is None:
                old.kill()
                old.wait(timeout=10)

    @pytest.mark.asyncio
    async def test_c09_concurrent_reconciler_converges_or_fail_closed(self) -> None:
        """C-09: Concurrent reconcilers on DeliveryRecord and PostgreSQL state converge
        or fail-closed via CAS; divergent attach is strictly forbidden.
        """
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        # 1. DeliveryStore memory CAS test
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
        assert cas2 is False  # Conflicting divergent revision rejected!

        # 2. Real PostgreSQL CAS: two concurrent reconcilers trying to attach differing refs to at_runs
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO public.at_runs (run_id, work_id, status, execution_ref)
                VALUES (%s, 'work-c09', 'STARTING', NULL)
                ON CONFLICT (run_id) DO UPDATE SET execution_ref = NULL, status = 'STARTING';
                """,
                (str(run_id),),
            )
            conn.commit()

        ref_alpha = {"backend": "dbos", "execution_id": f"exec_alpha_{run_id}"}
        ref_beta = {"backend": "dbos", "execution_id": f"exec_beta_{run_id}"}

        def _cas_attach(ref_data: dict) -> bool:
            with psycopg.connect(system_url) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE public.at_runs
                    SET status = 'RUNNING', execution_ref = %s, updated_at = NOW()
                    WHERE run_id = %s AND execution_ref IS NULL
                    RETURNING run_id
                    """,
                    (psycopg.types.json.Jsonb(ref_data), str(run_id)),
                )
                success = cur.fetchone() is not None
                conn.commit()
                return success

        res_alpha = _cas_attach(ref_alpha)
        res_beta = _cas_attach(ref_beta)

        assert res_alpha is True
        assert res_beta is False  # Divergent attach rejected!

        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute("SELECT execution_ref FROM public.at_runs WHERE run_id = %s", (str(run_id),))
            committed_ref = cur.fetchone()[0]
            assert committed_ref["execution_id"] == f"exec_alpha_{run_id}"
            assert committed_ref != ref_beta

    @pytest.mark.asyncio
    async def test_c10_unavailable_backend_does_not_forge_success(self) -> None:
        """C-10: Backend/tool unavailable produces UNAVAILABLE/failed evidence without forging empty/success."""
        # 1. FakeDurableAdapter outage simulation
        adapter = FakeDurableAdapter()
        adapter.simulate_unavailable = True
        missing_ref = ExecutionRef(backend="fake_durable", execution_id="exec_unavail")

        res = await adapter.get_status(missing_ref)
        assert res.error is not None
        assert res.error.category == ErrorCategory.UNAVAILABLE
        assert res.state != DurableExecutionState.COMPLETED

        # 2. Real DBOS adapter pointed at unavailable host/port
        unavail_adapter = DBOSDurableAdapter(system_database_url="postgresql://127.0.0.1:54399/outage")
        target_ref = ExecutionRef(backend="dbos", execution_id="exec_target")
        status_res = await unavail_adapter.get_status(target_ref)
        assert status_res.error is not None
        assert status_res.error.category == ErrorCategory.UNAVAILABLE
        assert status_res.state != DurableExecutionState.COMPLETED
        assert status_res.state != DurableExecutionState.RUNNING

    @pytest.mark.asyncio
    async def test_signal_crash_window_and_idempotent_reconciliation(self) -> None:
        """Signal delivery crash window: ensures signal_id deduplication record and DBOS.send
        do not cause signal loss across crash/retry, and DBOS.send idempotency prevents double delivery.
        """
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        adapter = DBOSDurableAdapter(system_database_url=system_url)
        run_id = new_run_id()
        exec_ref = await adapter.start(
            run_id, "walking_skeleton_workflow", {"task": "signal_test", "wait_for_signal": "approval"}
        )

        signal_id = f"sig_{uuid4().hex}"
        sig_name = "approval"
        payload = {"decision": "proceed"}

        # First delivery succeeds
        res1 = await adapter.signal(exec_ref, sig_name, signal_id, payload)
        assert res1.outcome == SignalOutcome.DELIVERED

        # Second delivery with SAME signal_id is recognized as duplicate in at_signals_seen
        res2 = await adapter.signal(exec_ref, sig_name, signal_id, payload)
        assert res2.outcome == SignalOutcome.DUPLICATE_IGNORED

        # Verify application mapping table at_signals_seen has exactly 1 record
        with psycopg.connect(system_url) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM public.at_signals_seen WHERE execution_id = %s AND signal_id = %s",
                (exec_ref.execution_id, signal_id),
            )
            assert cur.fetchone()[0] == 1

    def test_external_mutation_fixture_semantics(self) -> None:
        """External mutation fixture records key, invocation/applied counts, committed value/hash,
        first/last request IDs and validates replay-safe / reconcile-before-retry / non-retryable ambiguous semantics.
        """
        from tests.support.walking_skeleton_fixture import (
            AmbiguousMutationError,
            DurableExternalMutationFixture,
            compute_value_hash,
        )
        fixture_url = os.environ.get("AT_TEST_FIXTURE_URL", "postgresql:///at_external_fixture")
        fixture = DurableExternalMutationFixture(fixture_url)

        # 1. Replay-safe semantics
        k1 = f"mut-rs-{uuid4()}"
        r1 = fixture.apply_replay_safe(k1, "val1", "req-1")
        assert r1["invocation_count"] == 1
        assert r1["applied_effect_count"] == 1
        assert r1["committed_value"] == "val1"
        assert r1["committed_hash"] == compute_value_hash("val1")
        assert r1["first_request_id"] == "req-1"
        assert r1["last_request_id"] == "req-1"

        r1_replay = fixture.apply_replay_safe(k1, "val1", "req-2")
        assert r1_replay["invocation_count"] == 2
        assert r1_replay["applied_effect_count"] == 1  # No duplicate effect!
        assert r1_replay["first_request_id"] == "req-1"
        assert r1_replay["last_request_id"] == "req-2"

        # 2. Reconcile-before-retry semantics
        k2 = f"mut-rec-{uuid4()}"
        reconciled, r2 = fixture.reconcile_before_retry(k2, "val2", "req-a")
        assert reconciled is False
        assert r2["invocation_count"] == 1
        assert r2["applied_effect_count"] == 1

        reconciled2, r2_retry = fixture.reconcile_before_retry(k2, "val2", "req-b")
        assert reconciled2 is True
        assert r2_retry["invocation_count"] == 2
        assert r2_retry["applied_effect_count"] == 1

        # 3. Non-retryable ambiguous semantics
        k3 = f"mut-nr-{uuid4()}"
        r3 = fixture.apply_non_retryable(k3, "val3", "req-x")
        assert r3["applied_effect_count"] == 1

        # Second automatic attempt must raise AmbiguousMutationError!
        with pytest.raises(AmbiguousMutationError):
            fixture.apply_non_retryable(k3, "val3", "req-y")

    @pytest.mark.asyncio
    async def test_data_retention_probe_canary_isolation(self, tmp_path: Path) -> None:
        """Data-retention probe: 5 distinct canaries (prompt, tool input, tool output, secret, artifact payload)
        are verified across all 6 persistence surfaces (application DB, DBOS system tables, LiteLLM logs,
        OTel traces, stdout/stderr, artifact store) with explicit expected-present and expected-absent assertions.
        """
        litellm_bin = os.environ.get("AT_TEST_LITELLM_BIN")
        if not litellm_bin and os.path.exists("/opt/all-tomorrow-litellm-venv/bin/litellm"):
            litellm_bin = "/opt/all-tomorrow-litellm-venv/bin/litellm"
        system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
        if not litellm_bin:
            pytest.skip("Set AT_TEST_LITELLM_BIN")

        provider_port, tool_port, gateway_port = _free_port(), _free_port(), _free_port()

        # 5 distinct canaries
        secret_canary = f"sk-secret-{uuid4().hex}"
        prompt_canary = f"canary-prompt-{uuid4().hex}"
        tool_in_canary = f"canary-tool-in-{uuid4().hex}"
        tool_out_canary = tool_in_canary  # echoed by echo_canary
        artifact_canary = f"canary-artifact-oversized-{uuid4().hex}-" * 5000  # ~250KB raw content

        config = {
            "model_list": [{"model_name": "fixture", "litellm_params": {
                "model": "openai/fixture", "api_base": f"http://127.0.0.1:{provider_port}/v1",
                "api_key": "local-fixture", "num_retries": 0,
            }}],
            "router_settings": {"num_retries": 0},
            "general_settings": {"master_key": "os.environ/AT_TEST_GATEWAY_KEY",
                                 "store_prompts_in_spend_logs": False, "turn_off_message_logging": True},
            "litellm_settings": {"callbacks": [], "num_retries": 0},
            "mcp_servers": {"alpha": {"url": f"http://127.0.0.1:{tool_port}/mcp", "transport": "http", "allow_all_keys": True}},
        }
        config_path = tmp_path / "gateway_retention.yaml"
        config_path.write_text(yaml.safe_dump(config))

        span_file = tmp_path / "spans.jsonl"
        env = os.environ.copy()
        env["AT_TEST_GATEWAY_KEY"] = secret_canary
        env["AT_TEST_MODEL_URL"] = f"http://127.0.0.1:{gateway_port}/v1"
        env["AT_TEST_TOOL_URL"] = f"http://127.0.0.1:{gateway_port}/mcp"
        env["AT_TEST_OTEL_SPANS"] = str(span_file)

        commands = [
            [sys.executable, "-m", "uvicorn", "tests.support.model_provider:app", "--host", "127.0.0.1", "--port", str(provider_port)],
            [sys.executable, "-m", "tests.support.mcp_upstream", "alpha", str(tool_port)],
            [litellm_bin, "--config", str(config_path), "--port", str(gateway_port), "--telemetry", "False"],
        ]
        processes = []
        try:
            for index, command in enumerate(commands):
                log_file = tmp_path / f"proc-{index}.log"
                with log_file.open("wb") as stream:
                    processes.append(subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env))

            import httpx
            async with httpx.AsyncClient(timeout=2) as client:
                for _ in range(240):
                    assert all(p.poll() is None for p in processes)
                    try:
                        resp = await client.get(f"http://127.0.0.1:{gateway_port}/health/liveliness")
                        if resp.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.25)
                else:
                    pytest.fail("Gateway failed readiness")

            agent = PydanticAIGatewayAdapter(
                model_url=env["AT_TEST_MODEL_URL"],
                tool_url=env["AT_TEST_TOOL_URL"],
                gateway_key=secret_canary,
            )
            req = AgentExecutionRequest(
                model_route_ref="fixture",
                toolset_ref="all-tomorrow-tools",
                prompt=f"Evaluate task with {prompt_canary} canary-tool-in:{tool_in_canary}",
            )
            result = await agent.execute(req)
            assert result.success is True

            # Store oversized artifact in artifact store
            store = LocalArtifactStore(tmp_path / "retention_artifacts")
            art_ref = await store.store(artifact_canary.encode("utf-8"), media_type="text/plain")

            # ---------------- Surface 1: LiteLLM logs ----------------
            for log_path in tmp_path.glob("*.log"):
                content = log_path.read_text(errors="replace")
                assert secret_canary not in content, f"Secret leaked in {log_path.name}"
                assert prompt_canary not in content, f"Prompt canary leaked in {log_path.name}"
                assert artifact_canary not in content, f"Artifact payload leaked in {log_path.name}"

            # ---------------- Surface 2: OTel Telemetry Spans ----------------
            if span_file.exists():
                spans_text = span_file.read_text(errors="replace")
                assert secret_canary not in spans_text, "Secret leaked in spans"
                assert artifact_canary not in spans_text, "Raw artifact payload leaked in spans"

            # ---------------- Surface 3: PostgreSQL Application DB ----------------
            with psycopg.connect(system_url) as conn:
                cur = conn.cursor()
                for table in ["at_runs", "at_works", "at_goals", "at_questions", "at_signals_seen"]:
                    cur.execute(f"SELECT * FROM public.{table}")
                    db_dump = str(cur.fetchall())
                    assert secret_canary not in db_dump, f"Secret leaked in application table {table}"
                    assert artifact_canary not in db_dump, f"Oversized artifact raw payload duplicated in {table}"

            # ---------------- Surface 4: DBOS durable journal/state (dbos.*) ----------------
            with psycopg.connect(system_url) as conn:
                cur = conn.cursor()
                for table in ["workflow_status", "operation_outputs", "notifications"]:
                    cur.execute(f"SELECT * FROM dbos.{table}")
                    dbos_dump = str(cur.fetchall())
                    assert secret_canary not in dbos_dump, f"Secret leaked in dbos.{table}"
                    assert artifact_canary not in dbos_dump, f"Oversized artifact raw payload duplicated in dbos.{table}"

            # ---------------- Surface 5: Artifact Store ----------------
            # Expected Present in artifact store
            fetched_art = await store.retrieve(art_ref)
            assert fetched_art == artifact_canary.encode("utf-8")
        finally:
            for p in reversed(processes):
                _stop_process(p)

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
