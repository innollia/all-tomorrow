"""Live LiteLLM MCP gateway probe with two upstream fixtures."""

import os
import json
import hashlib
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_pydantic_agent_uses_stable_toolset_and_captures_contract(tmp_path: Path) -> None:
    gateway = os.environ.get("AT_TEST_LITELLM_MCP_URL")
    if not gateway:
        pytest.skip("Set AT_TEST_LITELLM_MCP_URL")
    from pydantic_ai import Agent
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.messages import ToolReturnPart

    toolset = MCPToolset(gateway, id="all-tomorrow-tools", auth="sk-local-gateway-probe", max_retries=0)
    assert toolset.id == "all-tomorrow-tools"
    async with toolset:
        definitions = sorted((t.model_dump(mode="json") for t in await toolset.list_tools()), key=lambda t: t["name"])
        names = [t["name"] for t in definitions if "identify" in t["name"]]
        assert len(names) >= 2
        contract = json.dumps(definitions, sort_keys=True, separators=(",", ":"))
        artifact = {"toolset_id": toolset.id, "definition_sha256": hashlib.sha256(contract.encode()).hexdigest(), "definitions": definitions}
        path = tmp_path / "tool-contract.json"
        path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
        agent = Agent(TestModel(call_tools=names), toolsets=[toolset], retries=0)
        result = await agent.run("Identify the connected upstreams")
        returns = [p for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
        assert {p.tool_name for p in returns} == set(names)
        assert any("alpha" in str(p.content) for p in returns)
        assert any("beta" in str(p.content) for p in returns)
    # New agent/run re-discovers, then can validate its contract against a saved run.
    async with MCPToolset(gateway, id="all-tomorrow-tools", auth="sk-local-gateway-probe") as fresh:
        repeated = sorted((t.model_dump(mode="json") for t in await fresh.list_tools()), key=lambda t: t["name"])
    assert repeated == json.loads(path.read_text(encoding="utf-8"))["definitions"]


@pytest.mark.asyncio
async def test_fixed_gateway_aggregates_colliding_upstream_tools() -> None:
    gateway = os.environ.get("AT_TEST_LITELLM_MCP_URL")
    if not gateway:
        pytest.skip("Set AT_TEST_LITELLM_MCP_URL for the live gateway probe")

    from fastmcp import Client

    async with Client(gateway, auth="sk-local-gateway-probe") as client:
        tools = await client.list_tools()
        names = [tool.name for tool in tools]
        assert len(names) == len(set(names)), names
        assert any("alpha" in name and "identify" in name for name in names), names
        assert any("beta" in name and "identify" in name for name in names), names
        for upstream in ("alpha", "beta"):
            tool_name = next(name for name in names if upstream in name and "identify" in name)
            result = await client.call_tool(tool_name, {})
            assert not result.is_error
            assert any(upstream in getattr(item, "text", "") for item in result.content)


@pytest.mark.asyncio
async def test_gateway_rejects_wrong_key() -> None:
    gateway = os.environ.get("AT_TEST_LITELLM_MCP_URL")
    if not gateway:
        pytest.skip("Set AT_TEST_LITELLM_MCP_URL for the live gateway probe")

    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            gateway,
            headers={"Authorization": "Bearer sk-wrong-key", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    # The no-DB probe fails closed, but LiteLLM returns 400 rather than an auth
    # status because validation of non-master keys attempts a DB lookup.
    assert response.status_code == 400, response.text
    assert "No connected db" in response.text


@pytest.mark.asyncio
async def test_new_run_discovers_added_upstream_and_captures_definition(tmp_path: Path) -> None:
    gateway = os.environ.get("AT_TEST_LITELLM_MCP_URL")
    if not gateway or os.environ.get("AT_TEST_GATEWAY_EXPECT_GAMMA") != "1":
        pytest.skip("Run after restarting gateway with litellm_mcp_probe_added.yaml and gamma upstream")

    from fastmcp import Client

    async with Client(gateway, auth="sk-local-gateway-probe") as first:
        tools = await first.list_tools()
        gamma = next(tool for tool in tools if "gamma" in tool.name and "identify" in tool.name)
        captured = gamma.model_dump(mode="json")
        result = await first.call_tool(gamma.name, {})
        assert not result.is_error
        assert any("gamma" in getattr(item, "text", "") for item in result.content)

    artifact = tmp_path / "gamma-tool-definition.json"
    artifact.write_text(json.dumps(captured, sort_keys=True, indent=2), encoding="utf-8")
    async with Client(gateway, auth="sk-local-gateway-probe") as second:
        repeated = next(tool for tool in await second.list_tools() if tool.name == gamma.name)
    assert repeated.model_dump(mode="json") == json.loads(artifact.read_text(encoding="utf-8"))
