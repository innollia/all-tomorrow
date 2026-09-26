import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
import httpx
import yaml

from pydantic_ai.messages import ToolReturnPart, ToolCallPart

from all_tomorrow.domain.errors import ErrorCategory
from all_tomorrow.ports.agent import AgentExecutionRequest, AgentExecutionResult
from tests.test_walking_skeleton_c01_c10 import _free_port, _stop_process

async def main():
    litellm_bin = os.environ.get("AT_TEST_LITELLM_BIN") or "/opt/all-tomorrow-litellm-venv/bin/litellm"
    provider_port, tool_port, gateway_port = _free_port(), _free_port(), _free_port()
    key = f"sk-test-c10-{uuid4().hex}"
    
    tmp_path = Path("/tmp/scratch_c10_inspect")
    tmp_path.mkdir(parents=True, exist_ok=True)
    
    config = {
        "model_list": [{
            "model_name": "fixture",
            "litellm_params": {
                "model": "openai/fixture",
                "api_base": f"http://127.0.0.1:{provider_port}/v1",
                "api_key": "local-fixture",
                "num_retries": 0,
            },
        }],
        "router_settings": {"num_retries": 0},
        "general_settings": {
            "master_key": "os.environ/AT_TEST_GATEWAY_KEY",
            "store_prompts_in_spend_logs": False,
            "turn_off_message_logging": True,
        },
        "litellm_settings": {"callbacks": [], "num_retries": 0},
        "mcp_servers": {
            "alpha": {"url": f"http://127.0.0.1:{tool_port}/mcp", "transport": "http", "allow_all_keys": True}
        },
    }
    config_path = tmp_path / "gateway.yaml"
    config_path.write_text(yaml.safe_dump(config))
    
    env = os.environ.copy()
    env["AT_TEST_GATEWAY_KEY"] = key
    model_url = f"http://127.0.0.1:{gateway_port}/v1"
    tool_url = f"http://127.0.0.1:{gateway_port}/mcp"
    
    provider_cmd = [sys.executable, "-m", "uvicorn", "tests.support.model_provider:app", "--host", "127.0.0.1", "--port", str(provider_port)]
    tool_cmd = [sys.executable, "-m", "tests.support.mcp_upstream", "alpha", str(tool_port)]
    gateway_cmd = [litellm_bin, "--config", str(config_path), "--port", str(gateway_port), "--telemetry", "False"]
    
    f_prov = open(tmp_path / "provider.log", "wb")
    f_tool = open(tmp_path / "tool.log", "wb")
    f_gw = open(tmp_path / "gw.log", "wb")
    
    provider_proc = subprocess.Popen(provider_cmd, stdout=f_prov, stderr=subprocess.STDOUT, env=env)
    tool_proc = subprocess.Popen(tool_cmd, stdout=f_tool, stderr=subprocess.STDOUT, env=env)
    gateway_proc = subprocess.Popen(gateway_cmd, stdout=f_gw, stderr=subprocess.STDOUT, env=env)
    
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            for _ in range(120):
                try:
                    r = await client.get(f"http://127.0.0.1:{gateway_port}/health/liveliness")
                    if r.status_code == 200:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.25)
            else:
                print("Gateway failed readiness")
                print("Gateway log:", (tmp_path / "gw.log").read_text(errors="replace"))
                return
        
        from openai import AsyncOpenAI
        from pydantic_ai import Agent
        from pydantic_ai.mcp import MCPToolset
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from all_tomorrow.harness.types import ModelDecision
        
        client = AsyncOpenAI(base_url=model_url, api_key=key, max_retries=0)
        model = OpenAIChatModel("fixture", provider=OpenAIProvider(openai_client=client))
        tools = MCPToolset(tool_url, id="all-tomorrow-tools", auth=key, max_retries=0)
        agent = Agent(model, output_type=ModelDecision, toolsets=[tools], retries=1)
        
        # 1. Normal run
        async with agent as active:
            res1 = await active.run("prompt 1")
            print("RUN 1 MESSAGES:")
            for m in res1.all_messages():
                print(" ", type(m).__name__, getattr(m, "parts", None))
                
        # 2. Down tool
        print("\nDOWNING TOOL...")
        _stop_process(tool_proc)
        await asyncio.sleep(0.5)
        
        # Fresh agent context to force fresh MCP tool lookup
        tools2 = MCPToolset(tool_url, id="all-tomorrow-tools", auth=key, max_retries=0)
        agent2 = Agent(model, output_type=ModelDecision, toolsets=[tools2], retries=1)
        try:
            async with agent2 as active2:
                res2 = await active2.run("prompt 2")
                print("RUN 2 MESSAGES (DURING DOWN):")
                for m in res2.all_messages():
                    print(" ", type(m).__name__, getattr(m, "parts", None))
                print("RUN 2 OUTPUT:", res2.output)
        except Exception as e:
            print("RUN 2 RAISED EXCEPTION:", type(e).__name__, e)
            
    finally:
        _stop_process(tool_proc)
        _stop_process(provider_proc)
        _stop_process(gateway_proc)
        f_prov.close()
        f_tool.close()
        f_gw.close()

if __name__ == "__main__":
    asyncio.run(main())
