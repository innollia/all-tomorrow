"""P0 key-pool probe: LiteLLM Router rotation + 429 cooldown + recovery.

Run in the separate gateway runtime (deploy/gateway/requirements.txt), not the agent venv:
  <gateway-python> scripts/probe_key_pool.py [~/.all-tomorrow/key-pool.env]
Real free deployments from the key-pool file plus one local always-429 key to observe
cooldown. Key values are loaded into the process environment only and never printed.
"""
import asyncio, json, os, threading, collections, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from litellm import Router
import litellm
litellm.suppress_debug_info = True
import sys
from pathlib import Path
POOL = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / ".all-tomorrow" / "key-pool.env")
for line in POOL.read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        name, value = line.split("=", 1); os.environ[name.strip()] = value.strip()
# OpenRouter accounts flagged free_tier by /api/v1/key; only :free models so paid keys never bill.
OPENROUTER_FREE = ["OPENROUTER__BELLASIL2085", "OPENROUTER__CHUNGHO208", "OPENROUTER__CHUNGHO2082"]
hits = collections.Counter()
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path.startswith("/429"):
            hits["mock429"] += 1; code, body = 429, {"error":{"message":"rate limited","type":"rate_limit_error"}}
        else:
            hits["mockok"] += 1; code, body = 200, {"id":"x","object":"chat.completion","created":int(time.time()),"model":"mock","choices":[{"index":0,"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}
        b = json.dumps(body).encode(); self.send_response(code); self.send_header("content-type","application/json"); self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
COOLDOWN = 20
router = Router(model_list=[
    *[{"model_name":"free","litellm_params":{"model":"openrouter/nvidia/nemotron-3-super-120b-a12b:free","api_key":f"os.environ/{n}"},"model_info":{"id":"key-" + n.lower()}} for n in OPENROUTER_FREE],
    {"model_name":"free","litellm_params":{"model":"groq/openai/gpt-oss-20b","api_key":"os.environ/GROQ__CHUNGHO208"},"model_info":{"id":"key-groq__chungho208"}},
    {"model_name":"free","litellm_params":{"model":"openai/openai/gpt-oss-20b","api_base":"https://router.huggingface.co/v1","api_key":"os.environ/HUGGINGFACE__BELLASIL2085"},"model_info":{"id":"key-huggingface__bellasil2085"}},
    {"model_name":"free","litellm_params":{"model":"openai/mock","api_base":base+"/429/v1","api_key":"mock"},"model_info":{"id":"key-mock-429"}},
], routing_strategy="simple-shuffle", num_retries=2, allowed_fails=0, cooldown_time=COOLDOWN, retry_after=0)
async def batch(n, label):
    served = collections.Counter(); errors = []
    before = hits["mock429"]
    for _ in range(n):
        try:
            r = await router.acompletion(model="free", messages=[{"role":"user","content":"Reply OK"}], max_tokens=20)
            served[r._hidden_params.get("model_id")] += 1
        except Exception as e:
            errors.append(type(e).__name__ + ": " + str(e)[:160])
    print(label, json.dumps({"served": served, "mock429_hits_in_batch": hits["mock429"]-before, "errors": errors}, ensure_ascii=False))
async def main():
    await batch(12, "phase1 (12 calls):")
    await batch(6, "phase2 still cooling (6 calls):")
    time.sleep(COOLDOWN + 2)
    await batch(12, f"phase3 after {COOLDOWN}s cooldown (12 calls):")
asyncio.run(main())
