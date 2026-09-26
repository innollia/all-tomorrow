"""Real LiteLLM model and MCP routes used by one structured PydanticAI run."""
import asyncio
import json
import os
import subprocess
import sys
from uuid import uuid4

import httpx
import pytest
import yaml

from tests.test_litellm_gateway_privacy import _free_port, _stop


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["agent", "durable_crash"])
async def test_agent_through_model_and_tool_gateway(tmp_path, monkeypatch, mode):
    executable = os.environ.get("AT_TEST_LITELLM_BIN")
    if not executable:
        pytest.skip("Set AT_TEST_LITELLM_BIN")
    if mode != "agent" and not os.environ.get("AT_TEST_POSTGRES_URL"):
        pytest.skip("Run durable combination inside the live lab")
    provider_port, tool_port, gateway_port = _free_port(), _free_port(), _free_port()
    key = f"sk-combined-local-{uuid4().hex}"
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
    config_path = tmp_path / "gateway.yaml"
    config_path.write_text(yaml.safe_dump(config))
    monkeypatch.setenv("AT_TEST_GATEWAY_KEY", key)
    monkeypatch.setenv("AT_TEST_MODEL_URL", f"http://127.0.0.1:{gateway_port}/v1")
    monkeypatch.setenv("AT_TEST_TOOL_URL", f"http://127.0.0.1:{gateway_port}/mcp")
    span_path = tmp_path / "spans.jsonl"
    monkeypatch.setenv("AT_TEST_OTEL_SPANS", str(span_path))
    commands = [
        [sys.executable, "-m", "uvicorn", "tests.support.model_provider:app", "--host", "127.0.0.1", "--port", str(provider_port)],
        [sys.executable, "-m", "tests.support.mcp_upstream", "alpha", str(tool_port)],
        [executable, "--config", str(config_path), "--port", str(gateway_port)],
    ]
    processes = []
    try:
        for index, command in enumerate(commands):
            with (tmp_path / f"process-{index}.log").open("wb") as log:
                processes.append(subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT))
        async with httpx.AsyncClient(timeout=2) as client:
            for _ in range(240):
                assert all(p.poll() is None for p in processes), [p.returncode for p in processes]
                try:
                    response = await client.get(f"http://127.0.0.1:{gateway_port}/health/liveliness")
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(.25)
            else:
                pytest.fail("Combined gateway failed readiness")
        from tests.support.gateway_agent import create_gateway_agent
        from pydantic_ai.messages import ToolReturnPart
        canary = f"combined-prompt-private-{uuid4().hex}"
        if mode == "agent":
            async with create_gateway_agent() as agent:
                result = await agent.run(canary)
            assert result.output.stock_confirmed == 42
            returns = [p for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
            assert any("identify" in p.tool_name and "alpha" in str(p.content) for p in returns)
        else:
            from tests.support.live_process_adapters import DBOSProcessAdapter
            from tests.test_live_common_d01 import _payload, _prepare_fixture, _assert_common_result
            from all_tomorrow.harness.types import FailPoint
            _prepare_fixture(os.environ["AT_TEST_FIXTURE_URL"])
            payload = _payload("combined", wait_for_signal=True, fail_point=FailPoint.AFTER_MUTATION_SIDE_EFFECT)
            payload["input"]["task_name"] = canary
            execution = DBOSProcessAdapter(payload, tmp_path)
            try:
                first = execution.start("crash")
                assert first.wait(timeout=60) == 77
                execution.start("start")
                execution.wait_span("_wait_started")
                execution.signal()
                result = execution.finish()
                _assert_common_result(execution.fixture_url, payload, result, expected_calls=2)
                assert execution.state() == "SUCCESS"
            finally:
                execution.close()
    finally:
        for process in reversed(processes):
            _stop(process)
    for path in tmp_path.glob("*.log"):
        log = path.read_text(errors="replace")
        assert key not in log
        assert canary not in log
    exported = span_path.read_text()
    assert key not in exported and canary not in exported
    spans = [json.loads(line) for line in exported.splitlines()]
    assert len({s["trace_id"] for s in spans}) == 1
    if mode == "agent":
        assert len([s for s in spans if s["parent_id"] is None]) == 1
    else:
        assert {s["trace_id"] for s in spans} == {payload["trace"]["trace_id"]}
        injected = next(s for s in spans if s["name"].startswith("injected_"))
        completed = next(s for s in spans if s["name"] == "common_completed")
        assert injected["pid"] != completed["pid"]
        assert any(s["name"] == "common_completed" for s in spans)
    assert len({s["span_id"] for s in spans}) == len(spans)
