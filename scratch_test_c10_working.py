import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
import httpx

from all_tomorrow.domain.errors import ErrorCategory
from all_tomorrow.ports.agent import AgentExecutionRequest, AgentExecutionResult
from tests.test_walking_skeleton_c01_c10 import _free_port, _stop_process

class PydanticAIGatewayAdapter:
    def __init__(self, model_url: str, tool_url: str, gateway_key: str) -> None:
        self.model_url = model_url
        self.tool_url = tool_url
        self.gateway_key = gateway_key

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        from openai import AsyncOpenAI
        from pydantic_ai import Agent
        from pydantic_ai.mcp import MCPToolset
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from all_tomorrow.harness.types import ModelDecision
        from all_tomorrow.error_normalization import normalize_exception

        try:
            client = AsyncOpenAI(base_url=self.model_url, api_key=self.gateway_key, max_retries=0)
            model = OpenAIChatModel("fixture", provider=OpenAIProvider(openai_client=client))
            tools = MCPToolset(self.tool_url, id="all-tomorrow-tools", auth=self.gateway_key, max_retries=0)
            agent = Agent(model, output_type=ModelDecision, toolsets=[tools], retries=1)

            async with agent as active_agent:
                result = await active_agent.run(request.prompt)
            return AgentExecutionResult(
                success=True,
                output=result.output.model_dump(),
                structured_data={"stock_confirmed": result.output.stock_confirmed},
            )
        except Exception as exc:
            canonical = normalize_exception(exc, default_code="tool_unavailable")
            return AgentExecutionResult(
                success=False,
                output=None,
                structured_data=None,
                error=canonical,
            )

async def main():
    provider_port, tool_port = _free_port(), _free_port()
    key = "test-gateway-key"
    model_url = f"http://127.0.0.1:{provider_port}/v1"
    tool_url = f"http://127.0.0.1:{tool_port}/mcp"
    
    env = os.environ.copy()
    env["PYTHONPATH"] = "/mnt/c/projects/all-tomorrow"
    
    provider_cmd = [sys.executable, "-m", "uvicorn", "tests.support.model_provider:app", "--host", "127.0.0.1", "--port", str(provider_port)]
    tool_cmd = [sys.executable, "-m", "tests.support.mcp_upstream", "alpha", str(tool_port)]
    
    provider_proc = subprocess.Popen(provider_cmd, env=env)
    tool_proc = subprocess.Popen(tool_cmd, env=env)
    
    try:
        # Wait for provider and tool
        async with httpx.AsyncClient(timeout=2) as client:
            for _ in range(120):
                assert provider_proc.poll() is None
                assert tool_proc.poll() is None
                try:
                    r1 = await client.get(f"http://127.0.0.1:{provider_port}/health")
                    r2 = await client.get(f"http://127.0.0.1:{tool_port}/mcp")
                    if r1.status_code == 200:
                        break
                except Exception:
                    await asyncio.sleep(0.25)
            else:
                print("Failed readiness")
                return
        
        adapter = PydanticAIGatewayAdapter(model_url=model_url, tool_url=tool_url, gateway_key=key)
        req = AgentExecutionRequest(model_route_ref="fixture", toolset_ref="all-tomorrow-tools", prompt="Audit stock")
        
        # 1. Normal run
        res_normal = await adapter.execute(req)
        print("1. NORMAL RESULT:", res_normal.success, res_normal.structured_data, res_normal.error)
        assert res_normal.success is True
        assert res_normal.error is None
        assert res_normal.structured_data.get("stock_confirmed") == 42
        
        # 2. Down upstream tool
        print("2. DOWNING TOOL PROCESS...")
        _stop_process(tool_proc)
        assert tool_proc.poll() is not None
        
        res_down = await adapter.execute(req)
        print("DOWN RESULT:", res_down.success, res_down.output, res_down.structured_data, res_down.error)
        assert res_down.success is False
        assert res_down.error is not None
        assert res_down.error.category == ErrorCategory.UNAVAILABLE
        assert res_down.output is None
        assert res_down.structured_data is None
        
        # 3. Recover upstream tool
        print("3. RECOVERING TOOL PROCESS...")
        tool_proc = subprocess.Popen(tool_cmd, env=env)
        async with httpx.AsyncClient(timeout=2) as client:
            for _ in range(120):
                assert tool_proc.poll() is None
                try:
                    r = await client.get(f"http://127.0.0.1:{tool_port}/mcp")
                    break
                except Exception:
                    await asyncio.sleep(0.25)
            else:
                print("Tool failed to recover")
                return
                
        res_rec = await adapter.execute(req)
        print("RECOVERED RESULT:", res_rec.success, res_rec.structured_data, res_rec.error)
        assert res_rec.success is True
        assert res_rec.error is None
        assert res_rec.structured_data.get("stock_confirmed") == 42
        
        print("\nSUCCESS: All phases directly verified through product adapter!")
        
    finally:
        _stop_process(tool_proc)
        _stop_process(provider_proc)

if __name__ == "__main__":
    asyncio.run(main())
