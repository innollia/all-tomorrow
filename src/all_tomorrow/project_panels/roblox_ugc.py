"""roblox-ugc-factory panel: job funnel, triage queue, providers, latest prepared report.

Read-only. The factory DB is opened with SQLite's read-only URI mode inside one read
transaction, so every count comes from the same snapshot; nothing is ever written.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

PROJECT_IDS = ("roblox-ugc-factory",)

# Used only when core/states.js cannot be read or parsed.
FALLBACK_STATES = ("new", "generated", "approved", "preparing", "validation_passed", "ready_to_publish",
                   "published", "distributed", "rejected", "rerolled", "failed")
TRIAGE_STATE = "generated"
TRIAGE_LIMIT = 10
BRIEF_MAX = 60
REPORT_MAX_BYTES = 1_000_000
SPIKE_MAX_BYTES = 1_000_000
PASS_KEYS = ("pass", "passed", "ok", "valid", "success")
VERDICT_KEYS = ("status", "result", "verdict")


def open_ro(db: Path) -> sqlite3.Connection:
    """Read-only connection that still sees committed WAL frames (no immutable=1).

    readonly_shm=1 stops a reader from rewriting the -shm index when no app holds the DB
    open; if SQLite refuses that (rare: live writer, no usable read mark) fall back to plain
    mode=ro, which may only touch the -shm scratch index, never the DB or WAL contents.
    """
    base = f"file:{quote(db.as_posix(), safe='/:')}?mode=ro"
    try:
        return _begin_read(base + "&readonly_shm=1")
    except sqlite3.Error:
        return _begin_read(base)


def _begin_read(uri: str) -> sqlite3.Connection:
    conn = sqlite3.connect(uri, uri=True, timeout=0.3)
    try:
        conn.execute("BEGIN")  # one snapshot for every query below
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def iso_utc(value: Any) -> str | None:
    """SQLite datetime('now') text is UTC without a zone; mark it so the browser does not read local time."""
    if not value:
        return None
    text = str(value)[:32]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?", text):
        return text.replace(" ", "T") + "Z"
    return text


def read_states(path: Path) -> tuple[list[str], bool]:
    try:
        source = (path / "core" / "states.js").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return list(FALLBACK_STATES), False
    match = re.search(r"STATES\s*=\s*\[(.*?)\]", source, re.S)
    states = re.findall(r"['\"]([\w-]+)['\"]", match.group(1)) if match else []
    return (states, True) if states else (list(FALLBACK_STATES), False)


def short(text: Any, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _rows(conn: sqlite3.Connection, sql: str, problems: list[str], label: str) -> list[tuple] | None:
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.Error:
        problems.append(f"{label} 읽기 실패")
        return None


def db_facts(db: Path, states: list[str], problems: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        conn = open_ro(db)
    except sqlite3.Error:
        problems.append("data/factory.db 열기 실패")
        return out
    try:
        counts = _rows(conn, "SELECT state, count(*) FROM jobs GROUP BY state", problems, "jobs")
        if counts is not None:
            by_state = {str(s): int(n) for s, n in counts}
            ordered = [{"state": s, "count": by_state.pop(s, 0)} for s in states]
            ordered += [{"state": s, "count": n} for s, n in sorted(by_state.items())]  # states.js drifted
            out["funnel"] = ordered
            out["jobs_total"] = sum(r["count"] for r in ordered)
        triage = _rows(conn, f"SELECT id, category, brief, updated_at FROM jobs WHERE state = '{TRIAGE_STATE}' "
                             "ORDER BY updated_at, id", problems, "jobs")
        if triage is not None:
            out["triage_total"] = len(triage)
            out["triage"] = [{"id": i, "category": short(c, 24), "brief": short(b, BRIEF_MAX), "updated_at": iso_utc(u)}
                             for i, c, b, u in triage[:TRIAGE_LIMIT]]
        providers = _rows(conn, "SELECT provider, status, count(*) FROM provider_jobs GROUP BY provider, status",
                          problems, "provider_jobs")
        if providers is not None:
            table: dict[str, dict[str, Any]] = {}
            for provider, status, n in providers:
                row = table.setdefault(str(provider), {"provider": short(provider, 40), "success": 0, "failed": 0, "other": 0})
                key = status if status in ("success", "failed") else "other"
                row[key] += int(n)
            out["providers"] = sorted(table.values(), key=lambda r: r["provider"])
        events = _rows(conn, "SELECT job_id, from_state, to_state, at FROM events ORDER BY id DESC LIMIT 5",
                       problems, "events")
        if events is not None:
            out["events"] = [{"job_id": j, "from": short(f, 30) or None, "to": short(t, 30), "at": iso_utc(a)}
                             for j, f, t, a in events]
    finally:
        conn.close()
    return out


def verdict(report: dict[str, Any]) -> bool | None:
    for key in PASS_KEYS:
        if isinstance(report.get(key), bool):
            return report[key]
    for key in VERDICT_KEYS:
        value = str(report.get(key, "")).strip().lower()
        if value in ("pass", "passed", "ok", "success"):
            return True
        if value in ("fail", "failed", "error"):
            return False
    return None


def latest_report(path: Path, problems: list[str]) -> dict[str, Any] | None:
    newest: tuple[float, Path] | None = None
    try:
        job_dirs = [d for d in os.scandir(path / "data" / "prepared") if d.is_dir()]
    except OSError:
        return None
    for job_dir in job_dirs:
        try:
            for entry in os.scandir(job_dir.path):
                if entry.name.startswith("report") and entry.name.endswith(".json") and entry.is_file():
                    mtime = entry.stat().st_mtime
                    if newest is None or mtime > newest[0]:
                        newest = (mtime, Path(entry.path))
        except OSError:
            continue
    if newest is None:
        return None
    mtime, file = newest
    out: dict[str, Any] = {"job": file.parent.name[:20], "file": file.name[:60],
                           "mtime": datetime.fromtimestamp(mtime, UTC).isoformat(timespec="seconds")}
    try:
        if file.stat().st_size > REPORT_MAX_BYTES:
            raise ValueError("too large")
        report = json.loads(file.read_text(encoding="utf-8-sig"))
        if not isinstance(report, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        problems.append(f"리포트 읽기 실패: {out['job']}/{out['file']}")
        return out
    for key in ("triangle_count", "vertex_count"):
        value = report.get(key)
        out[key] = value if isinstance(value, int) and not isinstance(value, bool) else None
    out["passed"] = verdict(report)
    return out


def latest_spike(path: Path) -> dict[str, str] | None:
    try:
        with (path / "docs" / "SPIKE_LOG.md").open(encoding="utf-8", errors="replace") as handle:
            text = handle.read(SPIKE_MAX_BYTES)
    except OSError:
        return None
    best: tuple[str, str] | None = None
    for match in re.finditer(r"^#{1,6}\s+(\d{4}-\d{2}-\d{2})\b[\s:.-]*(.*)$", text, re.M):
        if best is None or match.group(1) >= best[0]:  # same date: the later section wins
            best = (match.group(1), short(match.group(2), 80))
    return {"date": best[0], "title": best[1]} if best else None


def collect(path: Path) -> dict[str, Any]:
    problems: list[str] = []
    states, states_ok = read_states(path)
    if not states_ok:
        problems.append("core/states.js를 읽지 못해 기본 상태 순서 사용")
    panel: dict[str, Any] = {"states_source": "core/states.js" if states_ok else "fallback"}
    db = path / "data" / "factory.db"
    if db.is_file():
        panel.update(db_facts(db, states, problems))
    else:
        problems.append("data/factory.db 없음")
    panel["report"] = latest_report(path, problems)
    panel["spike"] = latest_spike(path)
    panel["problems"] = problems
    return panel
