"""Subscription usage snapshots for the web dashboard.

The collector runs on the PC that holds the Claude/Codex logins and pushes a
credential-free snapshot to the web server. Token values never leave this module
except as the Authorization header of Anthropic's own usage endpoint.

  python -m all_tomorrow.usage show
  python -m all_tomorrow.usage push --url https://<server>   # POST /internal/usage
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CLAUDE_USER_AGENT = "claude-cli/2.0 (external, cli)"
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


class ClaudeLoginRequired(ValueError):
    pass


def _claude_failure(entry: dict, error: Exception, phase: str) -> dict:
    # Never retain response text, URLs, exception messages, or credential values.
    reason = type(error).__name__
    if isinstance(error, ClaudeLoginRequired):
        entry["status"] = "needs_login"
        reason = "missing_refresh_token"
    elif isinstance(error, urllib.error.HTTPError):
        reason = f"http_{error.code}"
        try:
            payload = json.loads(error.read(8192))
            code = payload.get("error")
            if isinstance(code, dict):
                code = code.get("type")
        except (ValueError, OSError, AttributeError):
            code = None
        if 400 <= error.code < 500 and code in ("invalid_grant", "invalid_token", "token_expired"):
            entry["status"] = "needs_login"
            reason += ":" + code
    entry["error"] = phase + ":" + reason
    return entry


def collect_claude(home: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": "claude", "name": "Claude", "plan": None, "status": "error", "observed_at": _now(), "windows": []}
    try:
        oauth = json.loads((home / ".claude" / ".credentials.json").read_text(encoding="utf-8"))["claudeAiOauth"]
    except FileNotFoundError:
        entry["status"] = "not_logged_in"
        return entry
    except (OSError, KeyError, ValueError) as error:
        return _claude_failure(entry, error, "credentials")
    entry["plan"] = _CLAUDE_TIERS.get(oauth.get("rateLimitTier"), oauth.get("subscriptionType"))
    if int(oauth.get("expiresAt", 0)) <= int(time.time() * 1000):
        # CLI가 새로 저장한 토큰과 경쟁하지 않도록 파일 교체 직전에 다시 확인한다.
        try:
            oauth = refresh_claude(home, oauth)
        except Exception as error:
            return _claude_failure(entry, error, "refresh")
    request = urllib.request.Request(
        CLAUDE_USAGE_URL,
        headers={"Authorization": f"Bearer {oauth['accessToken']}", "anthropic-beta": "oauth-2025-04-20",
                 "User-Agent": CLAUDE_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
    except Exception as error:  # noqa: BLE001 - surfaced as status, never raised to the pusher
        return _claude_failure(entry, error, "usage")
    entry["windows"] = claude_windows(payload)
    entry["status"] = "connected"
    return entry


def refresh_claude(home: Path, oauth: dict) -> dict:
    path = home / ".claude" / ".credentials.json"
    original = path.read_bytes()
    current = json.loads(original)["claudeAiOauth"]
    if current != oauth:
        return current
    if not oauth.get("refreshToken"):
        raise ClaudeLoginRequired("Claude 재로그인 필요")
    request = urllib.request.Request("https://platform.claude.com/v1/oauth/token",
        data=json.dumps({"grant_type": "refresh_token", "refresh_token": oauth["refreshToken"],
                         "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e"}).encode(),
        headers={"content-type": "application/json", "User-Agent": CLAUDE_USER_AGENT}, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        fresh = json.loads(response.read().decode())
    updated = {**oauth, "accessToken": fresh["access_token"],
               "refreshToken": fresh.get("refresh_token", oauth["refreshToken"]),
               "expiresAt": int(time.time() * 1000) + int(fresh["expires_in"]) * 1000}
    if path.read_bytes() != original:
        return json.loads(path.read_bytes())["claudeAiOauth"]
    data = json.loads(original)
    data["claudeAiOauth"] = updated
    # tempfile는 원본과 같은 디렉터리여서 같은 볼륨에서 원자 교체된다.
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix=".usage-refresh-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return updated


def _jwt_claims(token: str) -> dict[str, Any]:
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def latest_codex_rate_limits(sessions: Path) -> tuple[dict[str, Any], str] | None:
    files = sorted(sessions.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    found = []
    for path in files[:40]:
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            limits = (event.get("payload") or {}).get("rate_limits")
            if limits and limits.get("primary"):
                found.append((limits, event.get("timestamp") or datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()))
                break
    return max(found, key=lambda item: item[1]) if found else None


async def codex_live_limits() -> dict[str, Any]:
    """공식 app-server RPC. 모델을 호출하지 않고 로그인 계정의 현재 할당량을 읽는다."""
    from all_tomorrow.local_workers import discover_executable
    from all_tomorrow.adapters.workers import _worker_environment
    executable = discover_executable("codex")
    if not executable:
        raise FileNotFoundError("Codex CLI 없음")
    process = await asyncio.create_subprocess_exec(executable, "app-server",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env=_worker_environment({}), creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0))

    async def send(message):
        process.stdin.write((json.dumps(message) + "\n").encode())
        await process.stdin.drain()

    async def receive(ident):
        while True:
            line = await process.stdout.readline()
            if not line:
                raise ValueError("Codex RPC 조기 종료")
            data = json.loads(line)
            if data.get("id") == ident:
                if "error" in data:
                    raise ValueError("Codex 사용량 조회 실패")
                return data["result"]
    try:
        async with asyncio.timeout(20):
            await send({"method": "initialize", "id": 0,
                        "params": {"clientInfo": {"name": "all_tomorrow", "version": "0.1.0"}}})
            await receive(0)
            await send({"method": "initialized", "params": {}})
            await send({"method": "account/rateLimits/read", "id": 1})
            result = await receive(1)
            return result.get("rateLimitsByLimitId", {}).get("codex") or result["rateLimits"]
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


def collect_codex(home: Path, *, live: bool = True) -> dict[str, Any]:
    codex = Path(os.environ.get("CODEX_HOME", home / ".codex")) if home == Path.home() else home / ".codex"
    entry: dict[str, Any] = {"id": "codex", "name": "Codex", "plan": None, "status": "error", "observed_at": _now(), "windows": []}
    try:
        tokens = json.loads((codex / "auth.json").read_text(encoding="utf-8"))["tokens"]
        plan = _jwt_claims(tokens["id_token"]).get("https://api.openai.com/auth", {}).get("chatgpt_plan_type")
        entry["plan"] = plan.capitalize() if plan else None
    except (OSError, KeyError, ValueError, IndexError):
        entry["status"] = "not_logged_in"
        return entry
    found = None
    if live and home == Path.home():
        try:
            raw = asyncio.run(codex_live_limits())
            limits = {key: {"used_percent": raw[key]["usedPercent"],
                            "window_minutes": raw[key]["windowDurationMins"], "resets_at": raw[key]["resetsAt"]}
                      for key in ("primary", "secondary") if raw.get(key)}
            if limits:
                found = limits, _now()
        except Exception:
            pass  # 오류 본문을 남기지 않고 관측 시각이 있는 로그로 돌아간다.
    found = found or latest_codex_rate_limits(codex / "sessions")
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
