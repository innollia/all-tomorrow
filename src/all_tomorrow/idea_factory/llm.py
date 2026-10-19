"""Chat calls through the LiteLLM gateway (OpenAI-compatible). Key rotation lives in the gateway."""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx


def gateway_url() -> str:
    return os.environ.get("IDEA_FACTORY_GATEWAY_URL") or "http://127.0.0.1:4000"


class LLMError(RuntimeError):
    pass


def chat(model_group: str, system: str, user: str, *, max_tokens: int = 6000, temperature: float = 0.8) -> tuple[str, str]:
    """Returns (content, deployment id that served it)."""
    response = httpx.post(
        f"{gateway_url()}/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ.get('IDEA_FACTORY_GATEWAY_KEY', '')}"},
        json={"model": model_group, "max_tokens": max_tokens, "temperature": temperature,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        timeout=300,
    )
    if response.status_code != 200:
        raise LLMError(f"gateway {response.status_code}: {response.text[:300]}")
    data = response.json()
    content = data["choices"][0]["message"].get("content") or ""
    served = response.headers.get("x-litellm-model-id", data.get("model", ""))
    return content, served


def parse_json(text: str) -> Any:
    """Parse the first JSON object/array in a model reply (models wrap JSON in prose or fences)."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.S)
    if fence:
        cleaned = fence.group(1)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"no JSON in reply: {text[:200]!r}")


def chat_json(model_group: str, system: str, user: str, **kwargs: Any) -> tuple[Any, str]:
    last: Exception | None = None
    for _ in range(2):
        content, served = chat(model_group, system + "\n\n반드시 JSON만 출력한다. 설명 문장은 쓰지 않는다.", user, **kwargs)
        try:
            return parse_json(content), served
        except LLMError as error:
            last = error
    raise LLMError(str(last))
