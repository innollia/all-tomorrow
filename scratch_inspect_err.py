import asyncio
from pydantic_ai.mcp import MCPToolset
from pydantic_ai import Agent
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

async def test():
    tools = MCPToolset("http://127.0.0.1:54321/mcp", id="tools", auth="key", max_retries=0)
    client = AsyncOpenAI(base_url="http://127.0.0.1:54322/v1", api_key="key", max_retries=0)
    model = OpenAIChatModel("fixture", provider=OpenAIProvider(openai_client=client))
    agent = Agent(model, toolsets=[tools])
    try:
        async with agent as active_agent:
            await active_agent.run("test")
    except Exception as exc:
        print("EXC_TYPE:", type(exc).__name__)
        print("EXC_MSG:", repr(str(exc)))
        print("EXC_CAUSE:", type(exc.__cause__).__name__, type(exc.__cause__).__mro__, repr(str(exc.__cause__)))
        print("EXC_CONTEXT:", type(exc.__context__).__name__, repr(str(exc.__context__)))
        cur = exc
        chain = []
        while cur:
            chain.append(type(cur).__name__)
            cur = cur.__cause__ or cur.__context__
        print("CHAIN:", chain)

if __name__ == "__main__":
    asyncio.run(test())
