"""Jev (TypeSafe System One) caller for the console: typed questions in, typed answers out.

POST https://api.typesafe.ai/v1/systemone. The key comes from TYPESAFE_API_KEY, else from the
key-pool file (JEV__BELLASIL2085). The key is never logged, returned or put into an error text.
A failed call raises JevError; callers keep their old behaviour then — a failure is not an answer.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
POOL_NAME = "JEV__BELLASIL2085"


class JevError(RuntimeError):
    pass


def key_pool_path() -> Path:
    return Path(os.environ.get("IDEA_FACTORY_KEY_POOL") or Path.home() / ".all-tomorrow" / "key-pool.env")


def api_key() -> str:
    if key := os.environ.get("TYPESAFE_API_KEY", "").strip():
        return key
    try:
        for line in key_pool_path().read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.strip() == POOL_NAME and value.strip():
                return value.strip().strip("\"'")
    except OSError:
        pass
    return ""


def ask(state: Any, questions: dict[str, dict[str, Any]], timeout: float = 90) -> dict[str, dict[str, Any]]:
    """One request, many questions answered in parallel by Jev. Returns the `answers` object."""
    key = api_key()
    if not key:
        raise JevError("TYPESAFE_API_KEY 없음")
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise JevError(f"Jev HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:200]}") from None
    except (OSError, ValueError) as error:
        raise JevError(f"Jev 호출 실패: {type(error).__name__}") from None
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise JevError("Jev 응답에 answers 없음")
    return answers
