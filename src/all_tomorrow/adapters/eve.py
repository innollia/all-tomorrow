from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .mcp import McpClient, McpError


@dataclass(frozen=True, slots=True)
class EveStatus:
    source_owner: str
    source_ref: str
    data: Any


class EveReadAdapter:
    """Read-only boundary for Eve's existing frozen MCP contract."""

    EXPECTED_TOOL = "scene_status"

    def __init__(self, client: McpClient, *, source_ref: str = "project:eve") -> None:
        self.client = client
        self.source_ref = source_ref

    async def verify_contract(self) -> None:
        tools = await self.client.list_tools()
        status_tools = [tool for tool in tools if tool.get("name") == self.EXPECTED_TOOL]
        if len(status_tools) != 1:
            raise McpError("Eve MCP must expose exactly one scene_status tool")
        annotations = status_tools[0].get("annotations", {})
        if annotations.get("readOnlyHint") is not True:
            raise McpError("Eve scene_status is not marked read-only")

    async def status(self, arguments: dict[str, Any] | None = None) -> EveStatus:
        result = await self.client.call_tool(self.EXPECTED_TOOL, arguments or {})
        return EveStatus(
            source_owner="eve-scene-runtime",
            source_ref=self.source_ref,
            data=result,
        )

