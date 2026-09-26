import asyncio
import os
import subprocess
import sys
from pathlib import Path
import httpx

from all_tomorrow.domain.errors import ErrorCategory
from all_tomorrow.ports.agent import AgentExecutionRequest
from all_tomorrow.adapters.pydantic_ai import PydanticAIGatewayAdapter
from all_tomorrow.adapters.fake_adapters import FakeDurableAdapter
from all_tomorrow.domain.ids import ExecutionRef
from all_tomorrow.storage.delivery_store import DeliveryStore
from all_tomorrow.storage.artifact_store import LocalArtifactStore
from all_tomorrow.orchestration.walking_skeleton import WalkingSkeletonOrchestrator
from tests.test_walking_skeleton_c01_c10 import _free_port, _stop_process

async def main():
    root = Path(__file__).resolve().parent
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}:{root / 'src'}"
    env["PYTHONUNBUFFERED"] = "1"

    provider_port, tool_port = _free_port(), _free_port()
    key = "test-c10-gateway-key"
    model_url = f"http://127.0.0.1:{provider_port}/v1"
    tool_url = f"http://127.0.0.1:{tool_port}/mcp"

    provider_cmd = [
        sys.executable, "-u", "-m", "uvicorn", "tests.support.model_provider:app",
        "--host", "127.0.0.1", "--port", str(provider_port),
    ]
    tool_cmd = [
        sys.executable, "-u", "-m", "tests.support.mcp_upstream", "alpha", str(tool_port),
    ]

    p_log_file = root / "c10_provider.log"
    t_log_file = root / "c10_tool.log"

    p_log = open(p_log_file, "wb", buffering=0)
    t_log = open(t_log_file, "wb", buffering=0)

    provider_proc = subprocess.Popen(provider_cmd, stdout=p_log, stderr=subprocess.STDOUT, env=env)
    tool_proc = subprocess.Popen(tool_cmd, stdout=t_log, stderr=subprocess.STDOUT, env=env)

    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            for i in range(80):
                assert provider_proc.poll() is None, f"Provider crashed: {p_log_file.read_text()}"
                assert tool_proc.poll() is None, f"Tool crashed: {t_log_file.read_text()}"
                try:
                    r1 = await client.get(f"http://127.0.0.1:{provider_port}/health")
                    r2 = await client.get(f"http://127.0.0.1:{tool_port}/mcp")
                    if r1.status_code == 200:
                        print(f"Readiness achieved in iteration {i}")
                        break
                except Exception:
                    await asyncio.sleep(0.25)
            else:
                print("READINESS FAILED:")
                print("Provider log:", p_log_file.read_text())
                print("Tool log:", t_log_file.read_text())
                return

        adapter = PydanticAIGatewayAdapter(model_url=model_url, tool_url=tool_url, gateway_key=key)
        durable_port = FakeDurableAdapter()
        delivery_store = DeliveryStore()
        artifact_store = LocalArtifactStore(root / "artifacts_c10_debug")
        orch = WalkingSkeletonOrchestrator(
            durable_port=durable_port,
            agent_port=adapter,
            delivery_store=delivery_store,
            artifact_store=artifact_store,
        )
        g, w = await orch.initiate_goal_and_work(user_id="user_c10", goal_title="C10 Outage Goal", work_title="C10 Work")
        run_rec, _ = await orch.create_starting_run(w.work_id)
        orch.cas_attach_execution_ref(run_rec.run_id, ExecutionRef(backend="fake_durable", execution_id="c10_run_exec"))

        req = AgentExecutionRequest(model_route_ref="fixture", toolset_ref="all-tomorrow-tools", prompt="Inventory audit probe")

        # 1. Normal state
        res_normal = await adapter.execute(req)
        print("NORMAL ADAPTER RESULT:", res_normal.success, res_normal.structured_data, res_normal.error)
        assert res_normal.success is True
        assert res_normal.structured_data.get("stock_confirmed") == 42

        orch_normal = await orch.execute_agent_step(run_rec.run_id, prompt="Inventory audit probe")
        print("NORMAL ORCH RESULT:", orch_normal.success, orch_normal.structured_data, orch_normal.error)
        assert orch_normal.success is True
        assert orch_normal.structured_data.get("stock_confirmed") == 42

        # 2. DOWN tool process
        print("DOWNING TOOL PROCESS...")
        _stop_process(tool_proc)
        assert tool_proc.poll() is not None

        res_down = await adapter.execute(req)
        print("DOWN ADAPTER RESULT:", res_down.success, res_down.error)
        assert res_down.success is False
        assert res_down.error.category == ErrorCategory.UNAVAILABLE
        assert res_down.output is None
        assert res_down.structured_data is None

        orch_down = await orch.execute_agent_step(run_rec.run_id, prompt="Inventory audit probe")
        print("DOWN ORCH RESULT:", orch_down.success, orch_down.error)
        assert orch_down.success is False
        assert orch_down.error.category == ErrorCategory.UNAVAILABLE
        assert orch_down.output is None
        assert orch_down.structured_data is None

        # 3. RECOVER tool process
        print("RECOVERING TOOL PROCESS...")
        with t_log_file.open("ab") as t_stream:
            tool_proc = subprocess.Popen(tool_cmd, stdout=t_stream, stderr=subprocess.STDOUT, env=env)

        async with httpx.AsyncClient(timeout=1.0) as client:
            for _ in range(80):
                assert tool_proc.poll() is None
                try:
                    r = await client.get(f"http://127.0.0.1:{tool_port}/mcp")
                    break
                except Exception:
                    await asyncio.sleep(0.25)
            else:
                print("Tool failed to recover. Tool log:", t_log_file.read_text())
                return

        res_rec = await adapter.execute(req)
        print("RECOVERED ADAPTER RESULT:", res_rec.success, res_rec.structured_data, res_rec.error)
        assert res_rec.success is True
        assert res_rec.structured_data.get("stock_confirmed") == 42

        orch_rec = await orch.execute_agent_step(run_rec.run_id, prompt="Inventory audit probe")
        print("RECOVERED ORCH RESULT:", orch_rec.success, orch_rec.structured_data, orch_rec.error)
        assert orch_rec.success is True
        assert orch_rec.structured_data.get("stock_confirmed") == 42

        print("\nALL PHASES (ADAPTER + ORCHESTRATOR) SUCCEEDED DIRECTLY!")
    finally:
        _stop_process(tool_proc)
        _stop_process(provider_proc)
        try:
            p_log.close()
        except Exception:
            pass
        try:
            t_log.close()
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
