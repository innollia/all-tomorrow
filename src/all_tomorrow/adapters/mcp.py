from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx


class McpError(RuntimeError):
    pass


class McpClient:
    """Small HTTP JSON-RPC MCP client; it does not own tool/domain state."""

    def __init__(
        self,
        endpoint: str,
        *,
        bearer_token: str | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = endpoint
        self._owns_client = client is None
        headers = {"accept": "application/json"}
        if bearer_token:
            headers["authorization"] = f"Bearer {bearer_token}"
        self._client = client or httpx.AsyncClient(headers=headers, timeout=timeout_seconds)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._rpc("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise McpError("MCP tools/list returned no tools array")
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise McpError(f"MCP tool {name} returned isError")
        return result

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid4())
        try:
            response = await self._client.post(
                self.endpoint,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise McpError(f"MCP request failed: {type(error).__name__}") from error
        if not isinstance(payload, dict) or payload.get("id") != request_id:
            raise McpError("MCP response id mismatch")
        if "error" in payload:
            error = payload["error"]
            code = error.get("code") if isinstance(error, dict) else None
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise McpError(f"MCP error {code}: {message}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise McpError("MCP response has no result object")
        return result

