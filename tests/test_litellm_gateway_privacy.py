"""Isolated live gateway canary probe; requires the separate LiteLLM executable."""

import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import yaml


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_gateway_does_not_log_master_key_or_tool_payload(tmp_path: Path) -> None:
    litellm_bin = os.environ.get("AT_TEST_LITELLM_BIN")
    if not litellm_bin:
        pytest.skip("Set AT_TEST_LITELLM_BIN for isolated gateway canary probe")
    from fastmcp import Client

    upstream_port, gateway_port = _free_port(), _free_port()
    master_key = f"sk-secret-canary-{uuid4().hex}"
    payload = f"tool-payload-canary-{uuid4().hex}"
    config = {
        "model_list": [],
        "general_settings": {
            "master_key": "os.environ/AT_TEST_GATEWAY_MASTER_KEY",
            "store_prompts_in_spend_logs": False,
            "turn_off_message_logging": True,
        },
        "litellm_settings": {"callbacks": []},
        "mcp_servers": {
            "canary": {
                "url": f"http://127.0.0.1:{upstream_port}/mcp",
                "transport": "http",
                "allow_all_keys": True,
            }
        },
    }
    config_path = tmp_path / "gateway.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert master_key not in config_path.read_text(encoding="utf-8")
    gateway_env = os.environ.copy()
    gateway_env["AT_TEST_GATEWAY_MASTER_KEY"] = master_key
    upstream_log, gateway_log = tmp_path / "upstream.log", tmp_path / "gateway.log"
    with upstream_log.open("wb") as upstream_out, gateway_log.open("wb") as gateway_out:
        upstream = subprocess.Popen(
            [sys.executable, "-m", "tests.support.mcp_upstream", "canary", str(upstream_port)],
            stdout=upstream_out, stderr=subprocess.STDOUT,
        )
        gateway = subprocess.Popen(
            [litellm_bin, "--config", str(config_path), "--port", str(gateway_port)],
            stdout=gateway_out, stderr=subprocess.STDOUT, env=gateway_env,
        )
        try:
            for _ in range(120):
                assert upstream.poll() is None, "Canary upstream exited"
                assert gateway.poll() is None, "Canary gateway exited"
                try:
                    async with Client(f"http://127.0.0.1:{gateway_port}/mcp", auth=master_key) as client:
                        tools = await client.list_tools()
                        name = next(tool.name for tool in tools if "echo_canary" in tool.name)
                        result = await client.call_tool(name, {"value": payload})
                        assert not result.is_error
                        assert any(payload == getattr(item, "text", "") for item in result.content)
                        break
                except (OSError, RuntimeError, StopIteration):
                    await asyncio.sleep(0.25)
            else:
                pytest.fail("Canary tool was unavailable through the gateway")
        finally:
            _stop(gateway)
            _stop(upstream)
    for log_path in (gateway_log, upstream_log):
        log = log_path.read_text(encoding="utf-8", errors="replace")
        assert master_key not in log, f"Gateway credential appeared in {log_path.name}"
        assert payload not in log, f"Tool payload appeared in {log_path.name}"


@pytest.mark.asyncio
async def test_gateway_server_allowlist_filters_tool_listing_and_call(tmp_path: Path) -> None:
    litellm_bin = os.environ.get("AT_TEST_LITELLM_BIN")
    if not litellm_bin:
        pytest.skip("Set AT_TEST_LITELLM_BIN for isolated gateway allowlist probe")
    from fastmcp import Client

    upstream_port, gateway_port = _free_port(), _free_port()
    config = {
        "model_list": [],
        "general_settings": {"master_key": "sk-local-filter-probe"},
        "mcp_servers": {
            "filtered": {
                "url": f"http://127.0.0.1:{upstream_port}/mcp",
                "transport": "http",
                "allow_all_keys": True,
                "allowed_tools": ["identify"],
            }
        },
    }
    config_path = tmp_path / "filtered.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with (tmp_path / "upstream.log").open("wb") as upstream_out, (tmp_path / "gateway.log").open("wb") as gateway_out:
        upstream = subprocess.Popen(
            [sys.executable, "-m", "tests.support.mcp_upstream", "filtered", str(upstream_port)],
            stdout=upstream_out, stderr=subprocess.STDOUT,
        )
        gateway = subprocess.Popen(
            [litellm_bin, "--config", str(config_path), "--port", str(gateway_port)],
            stdout=gateway_out, stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(120):
                assert upstream.poll() is None, "Filtered upstream exited"
                assert gateway.poll() is None, "Filtered gateway exited"
                try:
                    async with Client(f"http://127.0.0.1:{gateway_port}/mcp", auth="sk-local-filter-probe") as client:
                        names = [tool.name for tool in await client.list_tools()]
                        assert any("identify" in name for name in names)
                        assert not any("echo_canary" in name for name in names)
                        allowed = next(name for name in names if "identify" in name)
                        result = await client.call_tool(allowed, {})
                        assert not result.is_error
                        assert any("filtered" in getattr(item, "text", "") for item in result.content)
                        blocked = allowed.replace("identify", "echo_canary")
                        from fastmcp.exceptions import ToolError
                        from mcp.shared.exceptions import MCPError
                        with pytest.raises((ToolError, MCPError), match="(?i)(not found|not allowed|denied|unknown tool)"):
                            await client.call_tool(blocked, {"value": "must-not-dispatch"})
                        break
                except (OSError, RuntimeError, StopIteration):
                    await asyncio.sleep(0.25)
            else:
                pytest.fail("Allowed tool was unavailable through the filtered gateway")
        finally:
            _stop(gateway)
            _stop(upstream)
