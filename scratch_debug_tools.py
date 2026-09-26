import json

from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/v1/chat/completions")
async def completion(request: Request):
    body = await request.json()
    tools = [t["function"]["name"] for t in body.get("tools", [])]
    print(f"DEBUG_TOOLS: {tools}", flush=True)
    # Return stop
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "fixture",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
    }
