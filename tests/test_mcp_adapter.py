import httpx
import pytest

from all_tomorrow.adapters import EveReadAdapter, McpClient, McpError


def rpc_response(request: httpx.Request, result: dict) -> httpx.Response:
    payload = __import__("json").loads(request.content)
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})


@pytest.mark.asyncio
async def test_eve_adapter_verifies_read_only_contract_and_preserves_owner() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        if payload["method"] == "tools/list":
            return rpc_response(
                request,
                {
                    "tools": [
                        {
                            "name": "scene_status",
                            "annotations": {"readOnlyHint": True},
                        }
                    ]
                },
            )
        assert payload["params"]["name"] == "scene_status"
        return rpc_response(request, {"content": [{"type": "text", "text": "OPEN"}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = EveReadAdapter(McpClient("https://eve.example/mcp", client=http))
    await adapter.verify_contract()
    status = await adapter.status()
    assert status.source_owner == "eve-scene-runtime"
    assert status.source_ref == "project:eve"
    assert status.data["content"][0]["text"] == "OPEN"
    await http.aclose()


@pytest.mark.asyncio
async def test_eve_adapter_fails_closed_if_status_is_not_read_only() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return rpc_response(
            request,
            {"tools": [{"name": "scene_status", "annotations": {"readOnlyHint": False}}]},
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = EveReadAdapter(McpClient("https://eve.example/mcp", client=http))
    with pytest.raises(McpError, match="not marked read-only"):
        await adapter.verify_contract()
    await http.aclose()


@pytest.mark.asyncio
async def test_mcp_error_does_not_leak_bearer_token() -> None:
    secret = "super-secret-token"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {secret}"
        return httpx.Response(500, text=secret)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"authorization": f"Bearer {secret}"},
    )
    client = McpClient("https://eve.example/mcp", bearer_token=secret, client=http)
    with pytest.raises(McpError) as caught:
        await client.list_tools()
    assert secret not in str(caught.value)
    await http.aclose()

