from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from all_tomorrow.domain.errors import CanonicalError


class SideEffectClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    RECONCILE_BEFORE_RETRY = "RECONCILE_BEFORE_RETRY"
    NON_RETRYABLE_AMBIGUOUS = "NON_RETRYABLE_AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    tool_id: str
    version: str
    source_owner: str
    capabilities: frozenset[str]
    side_effect_class: SideEffectClass
    required_authority: str
    input_schema_ref: str = ""
    output_schema_ref: str = ""
    timeout_seconds: float = 30.0
    supports_idempotency_key: bool = False
    supports_cancellation: bool = False
    provenance_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_id or not self.tool_id.strip():
            raise ValueError("ToolDescriptor.tool_id must be non-empty")
        if not self.version or not self.version.strip():
            raise ValueError("ToolDescriptor.version must be non-empty")
        if not self.source_owner or not self.source_owner.strip():
            raise ValueError("ToolDescriptor.source_owner must be non-empty")
        if not self.required_authority or not self.required_authority.strip():
            raise ValueError("ToolDescriptor.required_authority must be non-empty")


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    tool_id: str
    tool_version: str
    arguments: dict[str, Any]
    idempotency_key: str | None = None
    caller_actor_ref: str = ""
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_id: str
    success: bool
    output: Any = None
    duration_ms: int = 0
    error: CanonicalError | None = None


class ToolExecutionPort(Protocol):
    """Port interface for executing tools."""

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        ...
