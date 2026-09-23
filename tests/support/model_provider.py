"""Deterministic OpenAI wire fixture behind the real LiteLLM model router.

No external provider credentials or network requests are used.
"""
import json
from uuid import uuid4

from fastapi import FastAPI, Request

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def completion(request: Request):
    body = await request.json()
    functions = {t["function"]["name"]: t["function"] for t in body.get("tools", [])}
    has_tool_result = any(m["role"] == "tool" for m in body["messages"])
    identify = next((name for name in functions if "identify" in name), None)
    output = next((name for name in functions if name == "final_result"), None)
    if identify and not has_tool_result:
        name, args = identify, {}
    elif output:
        name, args = output, {
            "task_summary": "Gateway model fixture decision",
            "stock_confirmed": 42, "should_commit_mutation": True,
            "confidence_score": .99, "planned_mutation_value": "gateway-committed",
        }
    else:
        return {"id": f"chatcmpl-{uuid4().hex}", "object": "chat.completion", "created": 1,
                "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "completed"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    return {"id": f"chatcmpl-{uuid4().hex}", "object": "chat.completion", "created": 1,
            "model": body["model"], "choices": [{"index": 0, "finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call_{uuid4().hex}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
