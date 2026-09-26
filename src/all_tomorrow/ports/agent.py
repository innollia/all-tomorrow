from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from all_tomorrow.domain.errors import CanonicalError, ErrorCategory
from all_tomorrow.domain.ids import utc_now


@dataclass(frozen=True, slots=True)
class AgentUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    usage_known: bool = True
    """False when the provider/gateway reported no usage. Distinguishes a real
    zero-token call from 'usage unavailable', so unknown usage is never forged to
    0 (04A-04). When False, the token counts are placeholders, not measurements."""


@dataclass(frozen=True, slots=True)
class AgentExecutionRequest:
    model_route_ref: str
    toolset_ref: str
    prompt: str
    output_schema_ref: str | None = None
    system_instruction: str | None = None
    context_variables: dict[str, Any] = field(default_factory=dict)
    provenance_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_route_ref or not self.model_route_ref.strip():
            raise ValueError("AgentExecutionRequest.model_route_ref must be non-empty")
        if not self.toolset_ref or not self.toolset_ref.strip():
            raise ValueError("AgentExecutionRequest.toolset_ref must be non-empty")
        if not self.prompt or not self.prompt.strip():
            raise ValueError("AgentExecutionRequest.prompt must be non-empty")


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    success: bool
    output: Any = None
    structured_data: dict[str, Any] | None = None
    usage: AgentUsage = field(default_factory=AgentUsage)
    provenance_ref: str = ""
    completed_at: datetime = field(default_factory=utc_now)
    error: CanonicalError | None = None

    def __post_init__(self) -> None:
        if self.success and self.error is not None:
            raise ValueError("Successful agent result cannot contain an error")
        if not self.success and self.error is None:
            raise ValueError("Failed agent result must contain a CanonicalError")


class AgentExecutionPort(Protocol):
    """Port interface for agent/LLM executions."""

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Executes an agent call.

        Malformed structured output must NOT be coerced into success.
        """
        ...
