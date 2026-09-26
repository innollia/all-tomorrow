import subprocess
import time
import httpx
import sys

proc = subprocess.Popen([sys.executable, "-m", "tests.support.mcp_upstream", "alpha", "52345"])
time.sleep(3)
try:
    r = httpx.get("http://127.0.0.1:52345/mcp")
    print("status:", r.status_code, r.text)
except Exception as e:
    print("error:", type(e), e)
finally:
    proc.terminate()
