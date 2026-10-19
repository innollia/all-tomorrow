"""Subscription usage snapshots for the web dashboard.

The collector runs on the PC that holds the Claude/Codex logins and pushes a
credential-free snapshot to the web server. Token values never leave this module
except as the Authorization header of Anthropic's own usage endpoint.

  python -m all_tomorrow.usage show
  python -m all_tomorrow.usage push --url https://<server>   # POST /internal/usage
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_CLAUDE_TIERS = {"default_claude_max_20x": "Max 20x", "default_claude_max_5x": "Max 5x"}
_CLAUDE_LIMIT_LABELS = {"session": "5-hour", "weekly_all": "Weekly"}
# The server's collector credential; the old usage-only name still works as a fallback.
TOKEN_ENV = "ALL_TOMORROW_COLLECTOR_TOKEN"
LEGACY_TOKEN_ENV = "ALL_TOMORROW_USAGE_TOKEN"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _window(label: str, percent: Any, resets_at: Any) -> dict[str, Any]:
    if isinstance(resets_at, (int, float)):
        resets_at = datetime.fromtimestamp(resets_at, UTC).isoformat(timespec="seconds")
    return {"label": label, "percent": float(percent or 0), "resets_at": resets_at}


def claude_windows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    windows = []
    for limit in payload.get("limits") or []:
        kind = limit.get("kind")
        label = _CLAUDE_LIMIT_LABELS.get(kind)
        if kind == "weekly_scoped":
            model = ((limit.get("scope") or {}).get("model") or {}).get("display_name") or "scoped"
            label = f"Weekly · {model}"
        if label:
            windows.append(_window(label, limit.get("percent"), limit.get("resets_at")))
    if not windows:  # older response shape
        for key, label in (("five_hour", "5-hour"), ("seven_day", "Weekly")):
            if payload.get(key):
                windows.append(_window(label, payload[key].get("utilization"), payload[key].get("resets_at")))
    return windows


def collect_claude(home: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": "claude", "name": "Claude", "plan": None, "status": "error", "observed_at": _now(), "windows": []}
    try:
        oauth = json.loads((home / ".claude" / ".credentials.json").read_text(encoding="utf-8"))["claudeAiOauth"]
    except (OSError, KeyError, ValueError):
        entry["status"] = "not_logged_in"
        return entry
    entry["plan"] = _CLAUDE_TIERS.get(oauth.get("rateLimitTier"), oauth.get("subscriptionType"))
    if int(oauth.get("expiresAt", 0)) <= int(time.time() * 1000):
        # Refreshing would rotate Claude Code's own credentials; leave that to Claude Code.
        entry["status"] = "token_expired"
        return entry
    request = urllib.request.Request(
        CLAUDE_USAGE_URL,
        headers={"Authorization": f"Bearer {oauth['accessToken']}", "anthropic-beta": "oauth-2025-04-20"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
    except Exception as error:  # noqa: BLE001 - surfaced as status, never raised to the pusher
        entry["error"] = type(error).__name__
        return entry
    entry["windows"] = claude_windows(payload)
    entry["status"] = "connected"
    return entry


def _jwt_claims(token: str) -> dict[str, Any]:
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def latest_codex_rate_limits(sessions: Path) -> tuple[dict[str, Any], str] | None:
    files = sorted(sessions.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[:20]:
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            limits = (event.get("payload") or {}).get("rate_limits")
            if limits and limits.get("primary"):
                return limits, event.get("timestamp") or datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    return None


def collect_codex(home: Path) -> dict[str, Any]:
    codex = home / ".codex"
    entry: dict[str, Any] = {"id": "codex", "name": "Codex", "plan": None, "status": "error", "observed_at": _now(), "windows": []}
    try:
        tokens = json.loads((codex / "auth.json").read_text(encoding="utf-8"))["tokens"]
        plan = _jwt_claims(tokens["id_token"]).get("https://api.openai.com/auth", {}).get("chatgpt_plan_type")
        entry["plan"] = plan.capitalize() if plan else None
    except (OSError, KeyError, ValueError, IndexError):
        entry["status"] = "not_logged_in"
        return entry
    found = latest_codex_rate_limits(codex / "sessions")
    if not found:
        entry["status"] = "no_data"
        return entry
    limits, observed_at = found
    names = {300: "5-hour", 10080: "Weekly"}
    for key in ("primary", "secondary"):
        window = limits.get(key)
        if window:
            label = names.get(window.get("window_minutes"), f"{window.get('window_minutes')}m")
            entry["windows"].append(_window(label, window.get("used_percent"), window.get("resets_at")))
    # Codex only records limits when a session runs; observed_at says how fresh they are.
    entry["observed_at"] = observed_at
    entry["status"] = "connected"
    return entry


def collect(home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    return {"collected_at": _now(), "providers": [collect_claude(home), collect_codex(home)]}


def push(snapshot: dict[str, Any], url: str, token: str) -> int:
    request = urllib.request.Request(
        url.rstrip("/") + "/internal/usage",
        data=json.dumps(snapshot).encode(),
        headers={"Authorization": f"Bearer {token}", "content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status


def collector_token(token_env: str) -> str | None:
    token = os.environ.get(token_env)
    if not token and token_env == TOKEN_ENV:
        token = os.environ.get(LEGACY_TOKEN_ENV)
    return token or None


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="all-tomorrow-usage")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    push_parser = sub.add_parser("push")
    push_parser.add_argument("--url", default=os.environ.get("ALL_TOMORROW_URL"))
    push_parser.add_argument("--token-env", default=TOKEN_ENV)
    args = parser.parse_args(argv)
    snapshot = collect()
    if args.command == "show":
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    token = collector_token(args.token_env)
    if not args.url or not token:
        print(f"--url (or ALL_TOMORROW_URL) and ${args.token_env} are required", file=sys.stderr)
        return 2
    print(push(snapshot, args.url, token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
