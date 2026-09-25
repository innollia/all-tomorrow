from __future__ import annotations

from typing import Any, Type
from pydantic import BaseModel

from all_tomorrow.domain.errors import CanonicalError
from all_tomorrow.error_normalization import normalize_exception
from all_tomorrow.ports.agent import (
    AgentExecutionPort,
    AgentExecutionRequest,
    AgentExecutionResult,
)


class PydanticAIGatewayAdapter(AgentExecutionPort):
    """Production AgentExecutionPort adapter executing through LiteLLM Gateway and MCP tools via PydanticAI.

    Guarantees:
    - Never forges success or synthetic output during upstream outages.
    - All network/tool failures are normalized into CanonicalError via normalize_exception.
    - Preserves typed structured output on success.
    """

    def __init__(
        self,
        model_url: str,
        tool_url: str,
        gateway_key: str,
        output_type: Type[BaseModel] | None = None,
        max_retries: int = 0,
        agent_retries: int = 1,
    ) -> None:
        self.model_url = model_url
        self.tool_url = tool_url
        self.gateway_key = gateway_key
        self.output_type = output_type
        self.max_retries = max_retries
        self.agent_retries = agent_retries

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        try:
            from openai import AsyncOpenAI
            from pydantic_ai import Agent
            from pydantic_ai.mcp import MCPToolset
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider
            from all_tomorrow.harness.types import ModelDecision

            target_output_type = self.output_type or ModelDecision

            client = AsyncOpenAI(
                base_url=self.model_url,
                api_key=self.gateway_key,
                max_retries=self.max_retries,
            )
            model = OpenAIChatModel(
                request.model_route_ref,
                provider=OpenAIProvider(openai_client=client),
            )
            tools = MCPToolset(
                self.tool_url,
                id=request.toolset_ref,
                auth=self.gateway_key,
                max_retries=self.max_retries,
            )
            agent = Agent(
                model,
                output_type=target_output_type,
                toolsets=[tools],
                retries=self.agent_retries,
            )

            async with agent as active_agent:
                result = await active_agent.run(request.prompt)

            raw_output = result.output
            if hasattr(raw_output, "model_dump"):
                output_data = raw_output.model_dump()
            elif isinstance(raw_output, dict):
                output_data = raw_output
            else:
                output_data = {"result": raw_output}

            stock_confirmed = getattr(raw_output, "stock_confirmed", None)
            if stock_confirmed is None and isinstance(output_data, dict):
                stock_confirmed = output_data.get("stock_confirmed")

            structured_data = {"stock_confirmed": stock_confirmed} if stock_confirmed is not None else output_data

            return AgentExecutionResult(
                success=True,
                output=output_data,
                structured_data=structured_data,
            )
        except Exception as exc:
            canonical = normalize_exception(exc, default_code="tool_or_gateway_unavailable")
            return AgentExecutionResult(
                success=False,
                output=None,
                structured_data=None,
                error=canonical,
            )
