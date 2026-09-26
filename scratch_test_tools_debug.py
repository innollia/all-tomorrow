import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
import httpx
import yaml

from tests.test_walking_skeleton_c01_c10 import _free_port, _stop_process

async def main():
    litellm_bin = os.environ.get("AT_TEST_LITELLM_BIN") or "/opt/all-tomorrow-litellm-venv/bin/litellm"
    provider_port, tool_port, gateway_port = _free_port(), _free_port(), _free_port()
    key = f"sk-test-debug-{uuid4().hex}"
    
    tmp_path = Path("/tmp/scratch_tools_debug")
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
    env["PYTHONPATH"] = "/mnt/c/projects/all-tomorrow"
    model_url = f"http://127.0.0.1:{gateway_port}/v1"
    tool_url = f"http://127.0.0.1:{gateway_port}/mcp"
    
    provider_cmd = [sys.executable, "-m", "uvicorn", "tests.support.model_provider:app", "--host", "127.0.0.1", "--port", str(provider_port)]
    tool_cmd = [sys.executable, "-m", "tests.support.mcp_upstream", "alpha", str(tool_port)]
    gateway_cmd = [litellm_bin, "--config", str(config_path), "--port", str(gateway_port), "--telemetry", "False"]
    
    log_p = open(tmp_path / "p.log", "w")
    log_t = open(tmp_path / "t.log", "w")
    log_g = open(tmp_path / "g.log", "w")
    
    provider_proc = subprocess.Popen(provider_cmd, stdout=log_p, stderr=subprocess.STDOUT, env=env)
    tool_proc = subprocess.Popen(tool_cmd, stdout=log_t, stderr=subprocess.STDOUT, env=env)
    gateway_proc = subprocess.Popen(gateway_cmd, stdout=log_g, stderr=subprocess.STDOUT, env=env)
    
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            for _ in range(120):
                try:
                    r = await client.get(f"http://127.0.0.1:{gateway_port}/health/liveliness")
                    if r.status_code == 200:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            else:
                print("Gateway failed readiness")
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
        
        async with agent as active:
            tool_list = await tools.list_tools()
            print("ACTIVE AGENT TOOLSET LIST_TOOLS:", [t.name for t in tool_list])
            res = await active.run("test prompt")
            print("ACTIVE AGENT RUN RESULT:", res.output)
            
    finally:
        _stop_process(tool_proc)
        _stop_process(provider_proc)
        _stop_process(gateway_proc)
        log_p.close()
        log_t.close()
        log_g.close()

if __name__ == "__main__":
    asyncio.run(main())
