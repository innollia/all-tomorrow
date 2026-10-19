"""Validate key-pool entries without printing key values.

  python scripts/check_key_pool.py [~/.all-tomorrow/key-pool.env]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CHECKS = {
    "OPENCODE": ("https://opencode.ai/zen/v1/models", lambda d: f"{len(d.get('data', []))} models"),
    "OPENROUTER": ("https://openrouter.ai/api/v1/key", lambda d: "free_tier={is_free_tier} usage={usage} limit={limit}".format(**{k: d.get("data", {}).get(k) for k in ("is_free_tier", "usage", "limit")})),
    "GROQ": ("https://api.groq.com/openai/v1/models", lambda d: f"{len(d.get('data', []))} models"),
    "HUGGINGFACE": ("https://huggingface.co/api/whoami-v2", lambda d: f"user ok, token role={d.get('auth', {}).get('accessToken', {}).get('role')}"),
    "GITHUB": ("https://models.github.ai/catalog/models", lambda d: f"{len(d)} models"),
}


def load_env(path: Path) -> dict[str, str]:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            entries[name.strip()] = value.strip()
    return entries


def check(provider: str, key: str) -> str:
    url, summarize = CHECKS[provider]
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "all-tomorrow-keycheck"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return "OK " + summarize(json.loads(response.read()))
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}"
    except Exception as error:  # noqa: BLE001
        return type(error).__name__


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / ".all-tomorrow" / "key-pool.env")
    for name, key in load_env(path).items():
        provider = name.split("__", 1)[0]
        status = check(provider, key) if provider in CHECKS and key else "skipped (no text-LLM check)"
        print(f"{name:40} {status}")


if __name__ == "__main__":
    main()
