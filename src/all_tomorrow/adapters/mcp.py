from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
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
        result = await self.call_tool_raw(name, arguments)
        if result.get("isError"):
            raise McpError(f"MCP tool {name} returned isError")
        return result

    async def call_tool_raw(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return the raw tool result so callers can inspect structured error details."""
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})

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


_STDIO_LINE_LIMIT_BYTES = 1024 * 1024


def _resolve_script(script: str, script_roots: tuple[str, ...]) -> Path:
    """Validate an MCP server script against the configured roots."""
    if not script.strip():
        raise McpError("MCP server script must not be empty")
    if not script_roots:
        raise McpError("script_roots must not be empty")
    resolved = Path(script).resolve()
    for root in script_roots:
        try:
            resolved.relative_to(Path(root).resolve())
        except ValueError:
            continue
        if not resolved.is_file():
            raise McpError("MCP server script does not exist")
        return resolved
    raise McpError("MCP server script is outside the allowed roots")


class StdioMcpClient:
    """Newline-delimited JSON-RPC MCP client over a stdio subprocess.

    Transport only: it owns no tool or domain state. The server script is
    validated against `script_roots`, requests are serialized, and stderr is
    discarded so server-side secrets never reach a control-plane error.
    """

    PROTOCOL_VERSION = "2024-11-05"
    CLIENT_NAME = "all-tomorrow"
    CLIENT_VERSION = "0.1.0"

    def __init__(
        self,
        *,
        interpreter: str,
        script: str,
        script_roots: tuple[str, ...],
        args: Sequence[str] = (),
        cwd: str | None = None,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> None:
        if not interpreter.strip():
            raise McpError("MCP interpreter must not be empty")
        if timeout_seconds <= 0:
            raise McpError("timeout_seconds must be > 0")
        self._argv = [interpreter, str(_resolve_script(script, script_roots)), *args]
        self._cwd = cwd
        self._timeout_seconds = timeout_seconds
        self._env = env or {}
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    @property
    def argv(self) -> tuple[str, ...]:
        return tuple(self._argv)

    async def start(self) -> None:
        async with self._lock:
            await self._ensure_started()

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._rpc("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise McpError("MCP tools/list returned no tools array")
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self.call_tool_raw(name, arguments)
        if result.get("isError"):
            raise McpError(f"MCP tool {name} returned isError")
        return result

    async def call_tool_raw(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return the raw tool result so callers can inspect structured error details."""
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})

    async def aclose(self) -> None:
        async with self._lock:
            process, self._process = self._process, None
            if process is None:
                return
            if process.stdin is not None and not process.stdin.is_closing():
                with contextlib.suppress(ProcessLookupError, BrokenPipeError, RuntimeError):
                    process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=self._timeout_seconds)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=self._timeout_seconds)

    async def _ensure_started(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._argv,
                cwd=self._cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={**os.environ, **self._env},
                limit=_STDIO_LINE_LIMIT_BYTES,
            )
        except OSError as error:
            self._process = None
            raise McpError(f"MCP stdio process failed to start: {type(error).__name__}") from error
        await self._request(
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self.CLIENT_NAME, "version": self.CLIENT_VERSION},
            },
        )
        await self._notify("notifications/initialized")

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            await self._ensure_started()
            return await self._request(method, params)

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid4())
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return await self._read_result(request_id)

    async def _notify(self, method: str) -> None:
        await self._write({"jsonrpc": "2.0", "method": method})

    async def _write(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise McpError("MCP stdio process is not running")
        process.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
        await process.stdin.drain()

    async def _read_result(self, request_id: str) -> dict[str, Any]:
        while True:
            line = await self._read_line()
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                code = error.get("code") if isinstance(error, dict) else None
                detail = error.get("message") if isinstance(error, dict) else str(error)
                raise McpError(f"MCP error {code}: {detail}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise McpError("MCP response has no result object")
            return result

    async def _read_line(self) -> str:
        process = self._process
        if process is None or process.stdout is None:
            raise McpError("MCP stdio process is not running")
        try:
            raw = await asyncio.wait_for(process.stdout.readline(), timeout=self._timeout_seconds)
        except asyncio.TimeoutError:
            raise McpError(f"MCP stdio request timed out after {self._timeout_seconds}s") from None
        if not raw:
            raise McpError("MCP stdio process closed its output stream")
        return raw.decode("utf-8", errors="replace").strip()

