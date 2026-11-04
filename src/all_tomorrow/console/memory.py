"""Memory panel: what is holding this PC's memory, one level above Task Manager.

  GET /api/memory   processes grouped as Claude Code sessions (by title) → their MCP servers,
                    All Tomorrow components, and other apps, with each session's idle time

A view the user opens when they want to manage memory. It never warns, alerts or records
anomalies (user, 2026-11-04: low memory is not a problem to report). Computed on request on the
PC the API runs on (Windows, WMI via pywin32), cached 30 seconds. Command lines are read only to
classify processes; the response carries fixed labels, exe names, session titles and folder names,
never raw command lines.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends

from all_tomorrow.console import ConsoleContext

log = logging.getLogger(__name__)

CACHE_SECONDS = 30
GB = 2 ** 30
# Ancestors above these are the OS, not the app that started the process.
SYSTEM_PARENTS = {"explorer.exe", "svchost.exe", "services.exe", "wininit.exe", "winlogon.exe", "system",
                  "smss.exe", "csrss.exe", "taskhostw.exe", "sihost.exe", "userinit.exe"}
SYSTEM_NAMES = SYSTEM_PARENTS | {"system idle process", "registry", "memory compression", "lsass.exe",
                                 "dwm.exe", "fontdrvhost.exe", "searchindexer.exe", "msmpeng.exe",
                                 "conhost.exe", "runtimebroker.exe", "spoolsv.exe", "audiodg.exe",
                                 "wmiprvse.exe", "dllhost.exe", "ctfmon.exe", "lsaiso.exe", "securityhealthservice.exe",
                                 "nissrv.exe", "searchhost.exe", "startmenuexperiencehost.exe", "textinputhost.exe",
                                 "shellexperiencehost.exe", "applicationframehost.exe", "smartscreen.exe", "vmmem",
                                 "vmmemwsl", "wudfhost.exe", "sgrmbroker.exe", "unsecapp.exe", "useroobebroker.exe"}
APPS = {"chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "code.exe": "VS Code",
        "chatgpt.exe": "ChatGPT 앱", "agy.exe": "Antigravity", "antigravity.exe": "Antigravity",
        "codex.exe": "Codex", "kiro.exe": "Kiro", "discord.exe": "Discord", "slack.exe": "Slack",
        "docker desktop.exe": "Docker Desktop", "com.docker.backend.exe": "Docker Desktop",
        "postgres.exe": "PostgreSQL", "syncthing.exe": "Syncthing", "tailscale-ipn.exe": "Tailscale",
        "tailscaled.exe": "Tailscale", "obs64.exe": "OBS", "steam.exe": "Steam", "unity.exe": "Unity",
        "unity hub.exe": "Unity Hub", "notion.exe": "Notion", "kakaotalk.exe": "카카오톡", "robloxstudiobeta.exe": "Roblox Studio"}
# Known MCP servers by a fragment of their command line.
MCP_LABELS = (("all_tomorrow.mcp_server", "All Tomorrow MCP"), ("oracle_mcp", "신탁 MCP"),
              ("antigravity_mcp", "Antigravity MCP"), ("mcp-proxy-for-aws", "AWS 플러그인 MCP"),
              ("research_mcp", "조사 목록 MCP"), ("excalidraw", "Excalidraw MCP"), ("notion", "Notion MCP"),
              ("github", "GitHub MCP"), ("playwright", "Playwright MCP"), ("chrome-native-host", "Claude in Chrome 연결"))
AT_COMPONENT = re.compile(r"all_tomorrow\.overseer\.runtime\s+([\w-]+)|runtime\.py\s+([\w-]+)")
AT_OTHER = (("idea_factory gateway", "게이트웨이"), ("litellm", "게이트웨이(LiteLLM)"),
            ("quote_vn_desk", "인용 작업판(quote_vn_desk)"), ("all_tomorrow.overseer.metacog_session", "메타인지 세션"))
OTHER_HELPER = "세션이 띄운 기타 프로세스"
RESUME = re.compile(r"--resume[ =]\"?([0-9a-f-]{36})")


def _exe(name: str) -> str:
    return (name or "").lower()


def mcp_label(cmdlines: list[str]) -> str:
    """Name an MCP server (or other helper) from its process subtree's command lines."""
    joined = " ".join(cmdlines).lower()
    for fragment, label in MCP_LABELS:
        if fragment in joined:
            return label
    for cmd in cmdlines:
        module = re.search(r"\s-m\s+([\w.]+)", cmd)
        if module:
            return module.group(1).rsplit(".", 1)[-1]
        package = re.search(r"([\w@/-]*mcp[\w-]*)", cmd, re.I)
        if package:
            return package.group(1).rsplit("/", 1)[-1]
    return OTHER_HELPER


def at_label(cmd: str) -> str | None:
    match = AT_COMPONENT.search(cmd)
    if match:
        return match.group(1) or match.group(2)
    for fragment, label in AT_OTHER:
        if fragment in cmd:
            return label
    return None


def session_records(data_dir: Path | None) -> dict[str, dict]:
    """Claude desktop session files, keyed by CLI session id (the --resume argument). A cleared or
    forked session keeps running on its earlier id, so earlier ids point at the same record."""
    if not data_dir:
        return {}
    found = {}
    for path in (data_dir / "claude-code-sessions").glob("*/*/local_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for cli in data.get("priorCliSessionIds") or []:
            found.setdefault(cli, data)
        if data.get("cliSessionId"):
            found[data["cliSessionId"]] = data
    return found


def is_session_cli(p: dict) -> bool:
    """A desktop Claude Code session: the bundled CLI (…/claude-code/<ver>/claude.exe), not a headless `claude -p`."""
    return (_exe(p["name"]) == "claude.exe" and "/claude-code/" in p["cmd"].replace("\\", "/")
            and not re.search(r"\s(-p|--print)(\s|$)", p["cmd"]))


def session_record(p: dict, sessions: dict[str, dict]) -> dict:
    """By --resume id; a session started fresh has none, so match its start to the session's creation."""
    match = RESUME.search(p["cmd"])
    if match:
        return sessions.get(match.group(1), {})
    started = p.get("started")
    if not started:
        return {}
    near = [r for r in sessions.values() if r.get("createdAt") and abs(r["createdAt"] / 1000 - started) < 120]
    return min(near, key=lambda r: abs(r["createdAt"] / 1000 - started)) if near else {}


def classify(processes: list[dict], sessions: dict[str, dict], now: float) -> dict:
    """processes: pid, ppid, name, cmd, private (bytes). Returns the grouped view."""
    by_pid = {p["pid"]: p for p in processes}

    def chain(p):
        seen, out = set(), []
        while p and p["pid"] not in seen:
            seen.add(p["pid"])
            out.append(p)
            parent = by_pid.get(p["ppid"])
            if not parent or _exe(parent["name"]) in SYSTEM_PARENTS:
                break
            p = parent
        return out

    def is_session(p):
        return is_session_cli(p)

    def is_desktop(p):
        return _exe(p["name"]) == "claude.exe" and "windowsapps" in p["cmd"].lower()

    session_parts: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    helper_cmds: dict[tuple[int, int], list[str]] = defaultdict(list)
    helper_mem: dict[tuple[int, int], float] = defaultdict(float)
    at: dict[str, float] = defaultdict(float)
    apps: dict[str, list] = defaultdict(lambda: [0.0, 0])
    headless = 0.0
    for p in processes:
        path = chain(p)
        mem = p["private"]
        root = next((i for i, a in enumerate(path) if is_session(a)), None)
        if root is not None:
            session = path[root]
            if root == 0:
                session_parts[session["pid"]]["Claude Code 본체"] += mem
            else:
                helper = path[root - 1]           # the session's direct child names the MCP server
                helper_cmds[(session["pid"], helper["pid"])].append(p["cmd"])
                helper_mem[(session["pid"], helper["pid"])] += mem
            continue
        label = next((at_label(a["cmd"]) for a in path if at_label(a["cmd"])), None)
        if label:
            at[label] += mem
            continue
        if any(is_desktop(a) for a in path):
            apps["Claude 데스크톱 앱"][0] += mem
            apps["Claude 데스크톱 앱"][1] += 1
            continue
        if any(_exe(a["name"]) == "claude.exe" and " -p" in a["cmd"] for a in path):
            headless += mem
            continue
        app = next((APPS[_exe(a["name"])] for a in reversed(path) if _exe(a["name"]) in APPS), None)
        if app is None:
            top = path[-1]
            name = _exe(top["name"])
            app = "Windows 시스템" if name in SYSTEM_NAMES or "\\windows\\" in top["cmd"].lower() else top["name"]
        apps[app][0] += mem
        apps[app][1] += 1
    if headless:
        apps["헤드리스 Claude(claude -p)"] = [headless, 0]

    mcp_total: dict[str, float] = defaultdict(float)
    mcp_sessions: dict[str, set] = defaultdict(set)
    for (session_pid, helper_pid), cmds in helper_cmds.items():
        label = mcp_label(cmds)
        mem = helper_mem[(session_pid, helper_pid)]
        session_parts[session_pid][label] += mem
        if label != OTHER_HELPER:
            mcp_total[label] += mem
            mcp_sessions[label].add(session_pid)

    rows = []
    for pid, parts in session_parts.items():
        record = session_record(by_pid[pid], sessions)
        cli = record.get("cliSessionId") or str(pid)
        last = record.get("lastActivityAt") or record.get("lastTurnEdgeAt")
        rows.append({"title": record.get("title") or f"(제목 모름 {cli[:8]})",
                     "folder": Path(record["cwd"]).name if record.get("cwd") else "",
                     "idle_minutes": round((now - last / 1000) / 60) if last else None,
                     "archived": bool(record.get("isArchived")),
                     "gb": round(sum(parts.values()) / GB, 2),
                     "parts": sorted(({"label": k, "gb": round(v / GB, 2)} for k, v in parts.items()),
                                     key=lambda x: -x["gb"])})
    rows.sort(key=lambda r: -r["gb"])

    def listing(items):
        return sorted(({"label": k, "gb": round(v[0] / GB, 2), "count": v[1]} for k, v in items.items()),
                      key=lambda x: -x["gb"])
    app_rows = listing(apps)
    small = [a for a in app_rows[12:]]
    app_rows = app_rows[:12] + ([{"label": f"그 밖의 앱 {len(small)}개", "gb": round(sum(a["gb"] for a in small), 2),
                                  "count": sum(a["count"] for a in small)}] if small else [])
    at_rows = sorted(({"label": k, "gb": round(v / GB, 2)} for k, v in at.items()), key=lambda x: -x["gb"])
    summary = [{"label": "Claude Code 세션", "gb": round(sum(r["gb"] for r in rows), 1), "count": len(rows)},
               {"label": "All Tomorrow", "gb": round(sum(r["gb"] for r in at_rows), 1), "count": len(at_rows)},
               {"label": "그 밖의 앱", "gb": round(sum(r["gb"] for r in app_rows), 1), "count": len(apps)}]
    mcp = sorted(({"label": k, "gb": round(v / GB, 2), "count": len(mcp_sessions[k])} for k, v in mcp_total.items()),
                 key=lambda x: -x["gb"])
    return {"summary": summary, "sessions": rows, "mcp": mcp, "all_tomorrow": at_rows, "apps": app_rows}


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong),
                ("avail_phys", ctypes.c_ulonglong), ("total_commit", ctypes.c_ulonglong),
                ("avail_commit", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong),
                ("avail_virtual", ctypes.c_ulonglong), ("avail_extended", ctypes.c_ulonglong)]


def totals() -> dict | None:
    if os.name != "nt":
        return None
    s = _MemoryStatus()
    s.length = ctypes.sizeof(s)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
        return None
    return {"physical_gb": round(s.total_phys / GB, 1), "physical_used_gb": round((s.total_phys - s.avail_phys) / GB, 1),
            "commit_gb": round((s.total_commit - s.avail_commit) / GB, 1), "commit_limit_gb": round(s.total_commit / GB, 1)}


def wmi_time(value: str | None) -> float | None:
    """WMI datetime '20261104001234.123456+540' → epoch seconds."""
    try:
        stamp = time.strptime(value[:14], "%Y%m%d%H%M%S")
        offset = int(value[21:25]) * 60
    except (TypeError, ValueError):
        return None
    import calendar
    return calendar.timegm(stamp) - offset


def windows_processes() -> list[dict]:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        def read():
            wmi = win32com.client.GetObject(r"winmgmts:root\cimv2")
            return [{"pid": int(p.ProcessId), "ppid": int(p.ParentProcessId or 0), "name": p.Name or "",
                     "cmd": p.CommandLine or "", "private": int(p.PrivatePageCount or 0),
                     "started": wmi_time(p.CreationDate)}
                    for p in wmi.ExecQuery("SELECT ProcessId,ParentProcessId,Name,CommandLine,PrivatePageCount,"
                                           "CreationDate FROM Win32_Process")]
        return read()
    finally:
        pythoncom.CoUninitialize()


def claude_data_dir(processes: list[dict]) -> Path | None:
    """The desktop app's data folder, from a session CLI path (…\\Claude-Data\\<id>\\claude-code\\…)."""
    for p in processes:
        match = re.search(r"(.+?)[\\/]claude-code[\\/]", p["cmd"].strip('"'))
        if match and is_session_cli(p):
            return Path(match.group(1).strip('"'))
    return None


def snapshot(read=windows_processes, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if os.name != "nt" and read is windows_processes:
        return {"available": False, "reason": "이 컴퓨터(Windows 아님)에서는 관측하지 않습니다."}
    started = time.monotonic()
    processes = read()
    view = classify(processes, session_records(claude_data_dir(processes)), now)
    return {"available": True, "observed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
            "totals": totals(), "process_count": len(processes),
            "took_s": round(time.monotonic() - started, 1), "cache_seconds": CACHE_SECONDS, **view}


def build_router(ctx: ConsoleContext) -> APIRouter:
    router = APIRouter()
    cache: dict = {"at": 0.0, "data": None}
    lock = asyncio.Lock()

    @router.get("/api/memory")
    async def memory(_: str = Depends(ctx.current_user)) -> dict:
        async with lock:
            if cache["data"] is None or time.monotonic() - cache["at"] > CACHE_SECONDS:
                try:
                    cache["data"] = await asyncio.to_thread(snapshot)
                except Exception as error:   # the panel must still render
                    log.warning("memory snapshot failed: %s", type(error).__name__)
                    return {"available": False, "reason": f"관측 실패: {type(error).__name__}"}
                cache["at"] = time.monotonic()
            return cache["data"]

    return router
