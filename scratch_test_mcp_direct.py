import asyncio
import subprocess
import sys
import httpx
from pydantic_ai.mcp import MCPToolset
from tests.test_walking_skeleton_c01_c10 import _free_port, _stop_process

async def main():
    port = _free_port()
    cmd = [sys.executable, "-m", "tests.support.mcp_upstream", "alpha", str(port)]
    proc = subprocess.Popen(cmd)
    try:
        # Wait for port
        async with httpx.AsyncClient(timeout=2) as client:
            for _ in range(30):
                try:
                    r = await client.get(f"http://127.0.0.1:{port}/mcp")
                    break
                except Exception:
                    await asyncio.sleep(0.1)
        
        toolset = MCPToolset(f"http://127.0.0.1:{port}/mcp")
        async with toolset:
            tools = await toolset.list_tools()
            print("Direct FastMCP tools:", [t.name for t in tools])
            res = await toolset.call_tool("identify", {})
            print("Direct call_tool result:", res)
    finally:
        _stop_process(proc)

if __name__ == "__main__":
    asyncio.run(main())
