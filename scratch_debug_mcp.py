import subprocess
import time
import httpx
import sys

port = 52345
proc = subprocess.Popen([sys.executable, "-m", "tests.support.mcp_upstream", "alpha", str(port)])
start = time.time()
print("Starting MCP upstream...")
while time.time() - start < 30:
    if proc.poll() is not None:
        print("Process died with returncode:", proc.returncode)
        break
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/")
        print("GET / responded:", r.status_code, r.text[:100])
        break
    except Exception as e:
        time.sleep(0.5)
else:
    print("Timed out waiting for port")

if proc.poll() is None:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/mcp")
        print("GET /mcp responded:", r.status_code, r.text[:100])
    except Exception as e:
        print("GET /mcp error:", type(e), e)
    proc.terminate()
    proc.wait()
