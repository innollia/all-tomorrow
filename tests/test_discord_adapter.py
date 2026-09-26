from __future__ import annotations

import sys
from typing import Any

import pytest

from all_tomorrow.adapters import (
    READ_ONLY_TOOLS,
    WRITE_TOOLS,
    DiscordErrorCode,
    DiscordReadAdapter,
    DiscordReadError,
    StdioMcpClient,
)
from all_tomorrow.adapters.mcp import McpError

FAKE_STDIO_SERVER = """
import json
import sys

TOOLS = [
    {"name": "discord_list_allowed_channels"},
    {"name": "discord_fetch_messages"},
    {"name": "discord_search_messages"},
    {"name": "discord_read_forum_thread"},
    {"name": "discord_post_thread_message"},
]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    message_id = message.get("id")
    if message_id is None:
        continue
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = message["params"]["name"]
        arguments = message["params"]["arguments"]
        if name == "discord_list_allowed_channels":
            result = {"content": [{"type": "text", "text": "- forum: show"}]}
        elif name == "discord_search_messages" and arguments.get("query") == "denied":
            result = {
                "content": [{"type": "text", "text": "ERROR: channel 1 is not allowlisted"}],
                "isError": True,
                "structuredContent": {"code": "DISCORD_ACCESS_DENIED"},
            }
        else:
            result = {
                "content": [
                    {"type": "text", "text": "turn=" + str(arguments.get("retrieval_turn_id"))}
                ],
                "structuredContent": {"budget": {"retrieval_turn_id": arguments.get("retrieval_turn_id"), "remaining_calls": 3}},
            }
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message_id, "result": result}) + "\\n")
    sys.stdout.flush()
"""


class FakeDiscordClient:
    def __init__(self, tools: list[dict[str, Any]] | None = None, result: Any = None, error: Exception | None = None) -> None:
        self.tools = tools if tools is not None else [{"name": name} for name in sorted(READ_ONLY_TOOLS)]
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[dict[str, Any]]:
        return self.tools

    async def call_tool_raw(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return {
            "content": [{"type": "text", "text": "hello"}],
            "structuredContent": {"budget": {"retrieval_turn_id": arguments.get("retrieval_turn_id"), "remaining_calls": 3}},
        }


def adapter(client: FakeDiscordClient, **kwargs: Any) -> DiscordReadAdapter:
    return DiscordReadAdapter(client, **kwargs)


def test_read_surface_matches_the_existing_discord_mcp_contract() -> None:
    assert READ_ONLY_TOOLS == {
        "discord_list_allowed_channels",
        "discord_fetch_messages",
        "discord_search_messages",
        "discord_read_forum_thread",
    }
    assert not (READ_ONLY_TOOLS & WRITE_TOOLS)


def test_turn_id_is_deterministic_and_within_the_source_limit() -> None:
    turn_id = DiscordReadAdapter.retrieval_turn_id("trace_abc", "search")
    assert turn_id == DiscordReadAdapter.retrieval_turn_id("trace_abc", "search")
    assert turn_id.startswith("at:trace_abc")
    long_turn_id = DiscordReadAdapter.retrieval_turn_id("t" * 200, "n" * 200)
    assert len(long_turn_id) <= 128
    assert long_turn_id != DiscordReadAdapter.retrieval_turn_id("t" * 200, "other")


@pytest.mark.asyncio
async def test_fetch_preserves_source_owner_and_propagates_trace_as_turn_id() -> None:
    client = FakeDiscordClient()
    turn_id = DiscordReadAdapter.retrieval_turn_id("trace_1", "search_messages")
    result = await adapter(client).fetch_messages(
        trace_id="trace_1",
        retrieval_turn_id=turn_id,
        channel_id="123",
        limit=5,
    )
    assert result.source_owner == "eve-scene-runtime"
    assert result.source_ref == "edge:discord"
    assert result.trace_id == "trace_1"
    assert result.retrieval_turn_id == turn_id
    assert result.text == "hello"
    assert result.budget["remaining_calls"] == 3
    name, arguments = client.calls[0]
    assert name == "discord_fetch_messages"
    assert arguments == {"channel_id": "123", "limit": 5, "retrieval_turn_id": turn_id}
    assert "trace_id" not in arguments


@pytest.mark.asyncio
async def test_allowed_channel_listing_does_not_consume_turn_budget() -> None:
    client = FakeDiscordClient()
    instance = adapter(client)
    for _ in range(5):
        await instance.list_allowed_channels(trace_id="trace_1")
    assert client.calls[0][1] == {}
    assert instance.calls_used("any-turn") == 0


@pytest.mark.asyncio
async def test_turn_budget_is_enforced_before_calling_the_source() -> None:
    client = FakeDiscordClient()
    instance = adapter(client)
    for _ in range(4):
        await instance.search_messages(
            trace_id="trace_1", retrieval_turn_id="turn_a", query="hello"
        )
    with pytest.raises(DiscordReadError) as caught:
        await instance.search_messages(
            trace_id="trace_1", retrieval_turn_id="turn_a", query="hello"
        )
    assert caught.value.code is DiscordErrorCode.BUDGET_EXCEEDED
    assert caught.value.details["max_calls"] == 4
    assert len(client.calls) == 4
    await instance.search_messages(trace_id="trace_1", retrieval_turn_id="turn_b", query="hi")
    assert len(client.calls) == 5


@pytest.mark.asyncio
async def test_source_access_denied_is_mapped_to_a_stable_code() -> None:
    client = FakeDiscordClient(
        result={
            "content": [{"type": "text", "text": "ERROR: channel 1 is not allowlisted"}],
            "isError": True,
            "structuredContent": {"code": "DISCORD_ACCESS_DENIED"},
        }
    )
    with pytest.raises(DiscordReadError) as caught:
        await adapter(client).search_messages(
            trace_id="trace_1", retrieval_turn_id="turn_a", query="hello"
        )
    assert caught.value.code is DiscordErrorCode.ACCESS_DENIED
    assert caught.value.tool == "discord_search_messages"
    assert caught.value.retrieval_turn_id == "turn_a"
    assert "not allowlisted" in str(caught.value)


@pytest.mark.asyncio
async def test_source_budget_error_is_mapped_and_structured_details_are_kept() -> None:
    client = FakeDiscordClient(
        result={
            "content": [{"type": "text", "text": "ERROR: tool-call budget exceeded"}],
            "isError": True,
            "structuredContent": {"code": "RETRIEVAL_BUDGET_EXCEEDED", "max_calls": 4},
        }
    )
    with pytest.raises(DiscordReadError) as caught:
        await adapter(client).fetch_messages(
            trace_id="trace_1", retrieval_turn_id="turn_a", channel_id="123"
        )
    assert caught.value.code is DiscordErrorCode.BUDGET_EXCEEDED
    assert caught.value.details["max_calls"] == 4


@pytest.mark.asyncio
async def test_unmapped_source_error_does_not_leak_a_caller_supplied_code() -> None:
    client = FakeDiscordClient(
        result={
            "content": [{"type": "text", "text": "ERROR: boom"}],
            "isError": True,
            "structuredContent": {"code": "SOMETHING_ELSE"},
        }
    )
    with pytest.raises(DiscordReadError) as caught:
        await adapter(client).read_forum_thread(
            trace_id="trace_1", retrieval_turn_id="turn_a", thread_id="t1"
        )
    assert caught.value.code is DiscordErrorCode.TOOL_ERROR


@pytest.mark.asyncio
async def test_transport_failure_is_reported_without_source_detail() -> None:
    client = FakeDiscordClient(error=RuntimeError("connection to 10.0.0.5 refused"))
    with pytest.raises(DiscordReadError) as caught:
        await adapter(client).search_messages(
            trace_id="trace_1", retrieval_turn_id="turn_a", query="hello"
        )
    assert caught.value.code is DiscordErrorCode.TRANSPORT
    assert "10.0.0.5" not in str(caught.value)


@pytest.mark.asyncio
async def test_result_without_text_content_is_a_contract_mismatch() -> None:
    client = FakeDiscordClient(result={"content": [{"type": "image"}]})
    with pytest.raises(DiscordReadError) as caught:
        await adapter(client).search_messages(
            trace_id="trace_1", retrieval_turn_id="turn_a", query="hello"
        )
    assert caught.value.code is DiscordErrorCode.CONTRACT_MISMATCH


@pytest.mark.asyncio
async def test_verify_contract_fails_closed_when_a_read_tool_is_missing() -> None:
    client = FakeDiscordClient(tools=[{"name": "discord_list_allowed_channels"}])
    with pytest.raises(DiscordReadError) as caught:
        await adapter(client).verify_contract()
    assert caught.value.code is DiscordErrorCode.CONTRACT_MISMATCH
    assert "discord_fetch_messages" in str(caught.value)


@pytest.mark.asyncio
async def test_verify_contract_passes_for_the_full_read_surface() -> None:
    client = FakeDiscordClient(tools=[{"name": name} for name in READ_ONLY_TOOLS | WRITE_TOOLS])
    await adapter(client).verify_contract()
    assert adapter(client).exposed_write_tools == WRITE_TOOLS


@pytest.mark.asyncio
async def test_write_tools_are_refused_even_if_a_caller_reaches_them() -> None:
    client = FakeDiscordClient()
    with pytest.raises(DiscordReadError) as caught:
        await adapter(client)._invoke(
            "discord_post_thread_message",
            {"channel_id": "1", "content": "hi"},
            trace_id="trace_1",
        )
    assert caught.value.code is DiscordErrorCode.CONTRACT_MISMATCH
    assert client.calls == []


@pytest.mark.parametrize("method", ["fetch_messages", "read_forum_thread"])
@pytest.mark.asyncio
async def test_cursors_and_limits_are_validated_before_any_call(method: str) -> None:
    client = FakeDiscordClient()
    instance = adapter(client)
    common = {"trace_id": "trace_1", "retrieval_turn_id": "turn_a"}
    if method == "fetch_messages":
        target = "channel_id"
    else:
        target = "thread_id"
    with pytest.raises(ValueError, match="at most one of before/after/around"):
        await getattr(instance, method)(**common, **{target: "x", "before": "1", "after": "2"})
    with pytest.raises(ValueError, match="between 1 and 50"):
        await getattr(instance, method)(**common, **{target: "x", "limit": 51})
    assert client.calls == []


@pytest.mark.asyncio
async def test_search_limit_is_capped_at_the_source_maximum() -> None:
    client = FakeDiscordClient()
    with pytest.raises(ValueError, match="between 1 and 10"):
        await adapter(client).search_messages(
            trace_id="trace_1", retrieval_turn_id="turn_a", query="hello", limit=11
        )
    assert client.calls == []


@pytest.mark.asyncio
async def test_budget_mirroring_can_be_disabled_for_long_running_turns() -> None:
    client = FakeDiscordClient()
    instance = adapter(client, max_calls_per_turn=None)
    for _ in range(6):
        await instance.search_messages(
            trace_id="trace_1", retrieval_turn_id="turn_a", query="hello"
        )
    assert len(client.calls) == 6


def test_stdio_client_rejects_a_server_script_outside_allowed_roots(tmp_path) -> None:
    outside = tmp_path / "outside.mjs"
    outside.write_text("//", encoding="utf-8")
    with pytest.raises(McpError, match="outside the allowed roots"):
        StdioMcpClient(
            interpreter="node",
            script=str(outside),
            script_roots=(str(tmp_path / "allowed"),),
        )
    with pytest.raises(McpError, match="script_roots must not be empty"):
        StdioMcpClient(interpreter="node", script=str(outside), script_roots=())


@pytest.mark.asyncio
async def test_read_adapter_works_over_the_stdio_transport(tmp_path) -> None:
    server = tmp_path / "fake_discord_mcp.py"
    server.write_text(FAKE_STDIO_SERVER, encoding="utf-8")
    client = StdioMcpClient(
        interpreter=sys.executable,
        script=str(server),
        script_roots=(str(tmp_path),),
        timeout_seconds=10.0,
    )
    instance = DiscordReadAdapter(client)
    try:
        await instance.verify_contract()
        turn_id = DiscordReadAdapter.retrieval_turn_id("trace_stdio", "search")
        found = await instance.search_messages(
            trace_id="trace_stdio", retrieval_turn_id=turn_id, query="hello"
        )
        assert found.text == f"turn={turn_id}"
        assert found.source_owner == "eve-scene-runtime"
        channels = await instance.list_allowed_channels(trace_id="trace_stdio")
        assert channels.text == "- forum: show"
        with pytest.raises(DiscordReadError) as caught:
            await instance.search_messages(
                trace_id="trace_stdio", retrieval_turn_id=turn_id, query="denied"
            )
        assert caught.value.code is DiscordErrorCode.ACCESS_DENIED
    finally:
        await client.aclose()
