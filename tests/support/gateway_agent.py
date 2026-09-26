"""Agent binding used by the combined compatibility probe."""
import os

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.instrumented import InstrumentationSettings

from all_tomorrow.harness.types import ModelDecision
from .otel_file_exporter import provider_for


def create_gateway_agent():
    key = os.environ["AT_TEST_GATEWAY_KEY"]
    client = AsyncOpenAI(base_url=os.environ["AT_TEST_MODEL_URL"], api_key=key, max_retries=0)
    model = OpenAIChatModel("fixture", provider=OpenAIProvider(openai_client=client))
    tools = MCPToolset(
        os.environ["AT_TEST_TOOL_URL"], id="all-tomorrow-tools", auth=key, max_retries=0,
    )
    instrumentation = False
    if path := os.environ.get("AT_TEST_OTEL_SPANS"):
        instrumentation = InstrumentationSettings(tracer_provider=provider_for(path), include_content=False)
    agent = Agent(model, output_type=ModelDecision, toolsets=[tools], retries=1)
    agent.instrument = instrumentation
    return agent
