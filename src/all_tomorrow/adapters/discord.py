from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from all_tomorrow.contracts import require_text

SOURCE_OWNER = "eve-scene-runtime"
SOURCE_ENTRYPOINT = "src/discord/discord-mcp-server.mjs"
DEFAULT_SOURCE_REF = "edge:discord"

LIST_ALLOWED_CHANNELS = "discord_list_allowed_channels"
FETCH_MESSAGES = "discord_fetch_messages"
SEARCH_MESSAGES = "discord_search_messages"
READ_FORUM_THREAD = "discord_read_forum_thread"

READ_ONLY_TOOLS = frozenset(
    {
        LIST_ALLOWED_CHANNELS,
        FETCH_MESSAGES,
        SEARCH_MESSAGES,
        READ_FORUM_THREAD,
    }
)

WRITE_TOOLS = frozenset(
    {
        "discord_create_sho_post",
        "discord_edit_sho_post",
        "discord_post_thread_message",
        "discord_edit_thread_message",
    }
)

SOURCE_MAX_CALLS_PER_TURN = 4
MAX_TURN_ID_LENGTH = 128
_SOURCE_ERROR_TEXT_LIMIT = 200


class DiscordErrorCode(StrEnum):
    ACCESS_DENIED = "DISCORD_ACCESS_DENIED"
    BUDGET_EXCEEDED = "RETRIEVAL_BUDGET_EXCEEDED"
    TOOL_ERROR = "DISCORD_TOOL_ERROR"
    CONTRACT_MISMATCH = "DISCORD_CONTRACT_MISMATCH"
    TRANSPORT = "DISCORD_TRANSPORT"


class DiscordReadError(RuntimeError):
    """Failure of a Discord read; the source stays the owner of Discord state."""

    def __init__(
        self,
        code: DiscordErrorCode,
        summary: str,
        *,
        tool: str | None = None,
        retrieval_turn_id: str | None = None,
        details: Mapping[str, Any] | None = None,
        source_text: str | None = None,
    ) -> None:
        super().__init__(summary)
        self.code = code
        self.tool = tool
        self.retrieval_turn_id = retrieval_turn_id
        self.details = dict(details or {})
        self.source_text = source_text


@dataclass(frozen=True, slots=True)
class DiscordReadResult:
    source_owner: str
    source_ref: str
    tool: str
    trace_id: str
    text: str
    structured: dict[str, Any] = field(default_factory=dict)
    retrieval_turn_id: str | None = None
    duration_ms: int = 0

    @property
    def budget(self) -> dict[str, Any]:
        budget = self.structured.get("budget")
        return dict(budget) if isinstance(budget, dict) else {}


class DiscordToolClient(Protocol):
    """Transport surface the adapter needs; both MCP clients satisfy it."""

    async def list_tools(self) -> list[dict[str, Any]]: ...

    async def call_tool_raw(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class DiscordReadAdapter:
    """Read-only boundary for the existing DiscordService MCP surface.

    Discord keeps ownership of the gateway, ACL, message cache, and forum
    threads. This adapter only calls the read tools that already exist in
    `eve-scene-runtime` and never promotes their output into central
    project/task state.

    Guarantees:

    - **source owner**: every result and error carries `eve-scene-runtime`.
    - **read only**: write tools of the same server are known but never called.
    - **timeout / transport**: enforced by the injected MCP client.
    - **idempotency**: read tools are side-effect free, so a retry is safe for
      Discord; it is *not* free for the source retrieval budget, so each call
      is counted per `retrieval_turn_id` before it is sent.
    - **trace propagation**: the source schemas reject unknown properties, so
      the trace travels as the retrieval turn id, never as an extra argument.
    """

    def __init__(
        self,
        client: DiscordToolClient,
        *,
        source_ref: str = DEFAULT_SOURCE_REF,
        max_calls_per_turn: int | None = SOURCE_MAX_CALLS_PER_TURN,
    ) -> None:
        self._client = client
        self.source_owner = SOURCE_OWNER
        self.source_ref = require_text(source_ref, "discord.source_ref")
        if max_calls_per_turn is not None and max_calls_per_turn < 1:
            raise ValueError("max_calls_per_turn must be >= 1 or None")
        self._max_calls_per_turn = max_calls_per_turn
        self._calls: dict[str, int] = {}

    @property
    def max_calls_per_turn(self) -> int | None:
        return self._max_calls_per_turn

    def calls_used(self, retrieval_turn_id: str) -> int:
        return self._calls.get(retrieval_turn_id, 0)

    @staticmethod
    def retrieval_turn_id(trace_id: str, node_id: str) -> str:
        """Derive the source retrieval turn id used for budget and trace correlation."""
        trace = require_text(trace_id, "discord.trace_id")
        node = require_text(node_id, "discord.node_id")
        turn_id = f"at:{trace}:{node}"
        if len(turn_id) <= MAX_TURN_ID_LENGTH:
            return turn_id
        digest = hashlib.sha256(turn_id.encode("utf-8")).hexdigest()[:32]
        return f"at:{trace[:64]}:{digest}"

    async def verify_contract(self) -> None:
        tools = await self._client.list_tools()
        names = {tool.get("name") for tool in tools if isinstance(tool, Mapping)}
        missing = sorted(name for name in READ_ONLY_TOOLS if name not in names)
        if missing:
            raise DiscordReadError(
                DiscordErrorCode.CONTRACT_MISMATCH,
                f"Discord MCP is missing read tools: {', '.join(missing)}",
                details={"missing": missing},
            )

    @property
    def exposed_write_tools(self) -> frozenset[str]:
        """Write tools the source server exposes but this adapter never calls."""
        return WRITE_TOOLS

    async def list_allowed_channels(self, *, trace_id: str) -> DiscordReadResult:
        return await self._invoke(LIST_ALLOWED_CHANNELS, {}, trace_id=trace_id)

    async def fetch_messages(
        self,
        *,
        trace_id: str,
        retrieval_turn_id: str,
        channel_id: str,
        limit: int | None = None,
        before: str | None = None,
        after: str | None = None,
        around: str | None = None,
    ) -> DiscordReadResult:
        arguments = _cursor_arguments(before=before, after=after, around=around)
        arguments["channel_id"] = require_text(channel_id, "discord.channel_id")
        _apply_limit(arguments, limit, maximum=50)
        return await self._invoke(
            FETCH_MESSAGES, arguments, trace_id=trace_id, retrieval_turn_id=retrieval_turn_id
        )

    async def search_messages(
        self,
        *,
        trace_id: str,
        retrieval_turn_id: str,
        query: str,
        channel_id: str | None = None,
        limit: int | None = None,
    ) -> DiscordReadResult:
        arguments: dict[str, Any] = {"query": require_text(query, "discord.query")}
        if channel_id is not None:
            arguments["channel_id"] = require_text(channel_id, "discord.channel_id")
        _apply_limit(arguments, limit, maximum=10)
        return await self._invoke(
            SEARCH_MESSAGES, arguments, trace_id=trace_id, retrieval_turn_id=retrieval_turn_id
        )

    async def read_forum_thread(
        self,
        *,
        trace_id: str,
        retrieval_turn_id: str,
        thread_id: str,
        limit: int | None = None,
        before: str | None = None,
        after: str | None = None,
        around: str | None = None,
    ) -> DiscordReadResult:
        arguments = _cursor_arguments(before=before, after=after, around=around)
        arguments["thread_id"] = require_text(thread_id, "discord.thread_id")
        _apply_limit(arguments, limit, maximum=50)
        return await self._invoke(
            READ_FORUM_THREAD, arguments, trace_id=trace_id, retrieval_turn_id=retrieval_turn_id
        )

    async def _invoke(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        trace_id: str,
        retrieval_turn_id: str | None = None,
    ) -> DiscordReadResult:
        if tool not in READ_ONLY_TOOLS:
            raise DiscordReadError(
                DiscordErrorCode.CONTRACT_MISMATCH,
                f"{tool} is not part of the Discord read surface",
                tool=tool,
            )
        trace = require_text(trace_id, "discord.trace_id")
        payload = dict(arguments)
        if retrieval_turn_id is not None:
            turn_id = require_text(retrieval_turn_id, "discord.retrieval_turn_id")
            if len(turn_id) > MAX_TURN_ID_LENGTH:
                raise ValueError(f"discord.retrieval_turn_id must be <= {MAX_TURN_ID_LENGTH} characters")
            payload.setdefault("retrieval_turn_id", turn_id)
            self._reserve_call(turn_id, tool)
        started = time.perf_counter()
        try:
            result = await self._client.call_tool_raw(tool, payload)
        except Exception as error:
            duration_ms = int((time.perf_counter() - started) * 1000)
            raise DiscordReadError(
                DiscordErrorCode.TRANSPORT,
                f"Discord MCP transport failed: {type(error).__name__}",
                tool=tool,
                retrieval_turn_id=retrieval_turn_id,
            ) from error
        duration_ms = int((time.perf_counter() - started) * 1000)
        text, structured = self._read_result(tool, result, retrieval_turn_id=retrieval_turn_id)
        return DiscordReadResult(
            source_owner=self.source_owner,
            source_ref=self.source_ref,
            tool=tool,
            trace_id=trace,
            text=text,
            structured=structured,
            retrieval_turn_id=retrieval_turn_id,
            duration_ms=duration_ms,
        )

    def _reserve_call(self, retrieval_turn_id: str, tool: str) -> None:
        used = self._calls.get(retrieval_turn_id, 0)
        if self._max_calls_per_turn is not None and used >= self._max_calls_per_turn:
            raise DiscordReadError(
                DiscordErrorCode.BUDGET_EXCEEDED,
                f"local retrieval budget exhausted for turn {retrieval_turn_id}",
                tool=tool,
                retrieval_turn_id=retrieval_turn_id,
                details={
                    "retrieval_turn_id": retrieval_turn_id,
                    "max_calls": self._max_calls_per_turn,
                    "current_calls": used,
                },
            )
        self._calls[retrieval_turn_id] = used + 1

    def _read_result(
        self,
        tool: str,
        result: Any,
        *,
        retrieval_turn_id: str | None,
    ) -> tuple[str, dict[str, Any]]:
        if not isinstance(result, Mapping):
            raise DiscordReadError(
                DiscordErrorCode.CONTRACT_MISMATCH,
                "Discord MCP returned a non-object result",
                tool=tool,
                retrieval_turn_id=retrieval_turn_id,
            )
        structured = result.get("structuredContent")
        structured_dict = dict(structured) if isinstance(structured, Mapping) else {}
        text = _result_text(result, tool=tool, retrieval_turn_id=retrieval_turn_id)
        if result.get("isError"):
            raise _map_tool_error(
                tool,
                text,
                structured_dict,
                retrieval_turn_id=retrieval_turn_id,
            )
        return text, structured_dict


def _cursor_arguments(
    *,
    before: str | None,
    after: str | None,
    around: str | None,
) -> dict[str, Any]:
    cursors = {
        name: value
        for name, value in (("before", before), ("after", after), ("around", around))
        if value is not None
    }
    if len(cursors) > 1:
        raise ValueError("discord cursors must use at most one of before/after/around")
    return {
        name: require_text(value, f"discord.{name}")
        for name, value in cursors.items()
    }


def _apply_limit(arguments: dict[str, Any], limit: int | None, *, maximum: int) -> None:
    if limit is None:
        return
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise ValueError(f"discord.limit must be an integer between 1 and {maximum}")
    arguments["limit"] = limit


def _result_text(
    result: Mapping[str, Any],
    *,
    tool: str,
    retrieval_turn_id: str | None,
) -> str:
    content = result.get("content")
    if not isinstance(content, list):
        raise DiscordReadError(
            DiscordErrorCode.CONTRACT_MISMATCH,
            "Discord MCP result has no content array",
            tool=tool,
            retrieval_turn_id=retrieval_turn_id,
        )
    parts = [
        item["text"]
        for item in content
        if isinstance(item, Mapping)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    ]
    if not parts:
        raise DiscordReadError(
            DiscordErrorCode.CONTRACT_MISMATCH,
            "Discord MCP result has no text content",
            tool=tool,
            retrieval_turn_id=retrieval_turn_id,
        )
    return "\n".join(parts)


def _map_tool_error(
    tool: str,
    text: str,
    structured: dict[str, Any],
    *,
    retrieval_turn_id: str | None,
) -> DiscordReadError:
    source_code = structured.get("code")
    if source_code == DiscordErrorCode.ACCESS_DENIED:
        code = DiscordErrorCode.ACCESS_DENIED
    elif source_code == DiscordErrorCode.BUDGET_EXCEEDED:
        code = DiscordErrorCode.BUDGET_EXCEEDED
    else:
        code = DiscordErrorCode.TOOL_ERROR
    detail = text.strip()
    if len(detail) > _SOURCE_ERROR_TEXT_LIMIT:
        detail = f"{detail[:_SOURCE_ERROR_TEXT_LIMIT]}..."
    return DiscordReadError(
        code,
        f"{tool} failed at source owner {SOURCE_OWNER}: {detail}" if detail else f"{tool} failed",
        tool=tool,
        retrieval_turn_id=retrieval_turn_id,
        details=structured,
        source_text=detail or None,
    )
