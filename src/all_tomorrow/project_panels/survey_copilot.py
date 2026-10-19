"""survey-copilot panel: offer status counts, best new offers, ledger totals, bridge queue.

Read-only. copilot.db runs in WAL mode and its data may live only in the -wal file, so
it is opened with SQLite's read-only URI mode (never immutable=1, which ignores the WAL)
inside one read transaction. Titles, URLs, notes, raw text and the profile are never read.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

PROJECT_IDS = ("survey-copilot",)

STATUS_ORDER = ("new", "opened", "screened_out", "completed", "approved", "rejected", "skipped")
LEDGER_KINDS = ("earned", "approved", "paid")
REQUIRED_TABLES = ("offers", "ledger", "platforms")
TOP_LIMIT = 3


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


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def offer_facts(conn: sqlite3.Connection, problems: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        # Duplicates (dup_of set) are hidden in the app's list, so they are counted separately.
        rows = conn.execute("SELECT status, sum(dup_of IS NULL), sum(dup_of IS NOT NULL) FROM offers "
                            "GROUP BY status").fetchall()
    except sqlite3.Error:
        problems.append("offers 읽기 실패")
        return out
    unique = {str(s): int(n or 0) for s, n, _ in rows}
    statuses = [{"status": s, "count": unique.pop(s, 0)} for s in STATUS_ORDER]
    statuses += [{"status": s[:30], "count": n} for s, n in sorted(unique.items())]
    out["statuses"] = statuses
    out["offers_total"] = sum(r["count"] for r in statuses)
    out["duplicates"] = sum(int(d or 0) for _, _, d in rows)

    try:
        new = conn.execute(
            "SELECT o.platform_id, p.name, o.reward_krw, o.minutes, o.p_qualify, o.deadline "
            "FROM offers o LEFT JOIN platforms p ON p.id = o.platform_id "
            "WHERE o.status = 'new' AND o.dup_of IS NULL").fetchall()
    except sqlite3.Error:
        problems.append("신규 오퍼 읽기 실패")
        return out
    scored = []
    for platform_id, name, reward, minutes, p_qualify, deadline in new:
        reward, minutes, p_qualify = _num(reward), _num(minutes), _num(p_qualify)
        if reward is None or p_qualify is None or not minutes or minutes <= 0:
            continue
        scored.append({
            "platform": str(name or platform_id or "-")[:40],
            "reward_krw": round(reward),
            "minutes": round(minutes, 1),
            "p_qualify": round(p_qualify, 2),
            "deadline": str(deadline)[:20] if deadline else None,
            "krw_per_min": round(reward * p_qualify / minutes, 1),
        })
    scored.sort(key=lambda r: r["krw_per_min"], reverse=True)
    out["top_new"] = scored[:TOP_LIMIT]
    out["unscored_new"] = len(new) - len(scored)  # missing reward, minutes or p_qualify
    return out


def ledger_facts(conn: sqlite3.Connection, problems: list[str]) -> dict[str, Any] | None:
    try:
        # created_at is written with datetime('now','localtime'), so compare in the same clock.
        rows = conn.execute(
            "SELECT kind, count(*), coalesce(sum(amount_krw), 0), "
            "coalesce(sum(CASE WHEN created_at >= datetime('now','localtime','-30 days') THEN amount_krw END), 0) "
            "FROM ledger GROUP BY kind").fetchall()
    except sqlite3.Error:
        problems.append("ledger 읽기 실패")
        return None
    by_kind = {str(k): (int(n), float(total), float(recent)) for k, n, total, recent in rows}
    out = {}
    for kind in LEDGER_KINDS:
        entries, total, recent = by_kind.get(kind, (0, 0.0, 0.0))
        out[kind] = {"entries": entries, "all_krw": round(total), "d30_krw": round(recent)}
    return out


def bridge_facts(path: Path) -> dict[str, Any] | None:
    inbox, outbox = path / "bridge" / "inbox", path / "bridge" / "outbox"
    try:
        requests = {e.name: e.stat().st_mtime for e in os.scandir(inbox) if e.name.endswith(".json") and e.is_file()}
    except OSError:
        return None
    try:
        answered = {e.name for e in os.scandir(outbox) if e.name.endswith(".json")}
    except OSError:
        answered = set()
    pending = [mtime for name, mtime in requests.items() if name not in answered]
    oldest = datetime.fromtimestamp(min(pending), UTC).isoformat(timespec="seconds") if pending else None
    return {"requests": len(requests), "pending": len(pending), "oldest_pending_at": oldest}


def collect(path: Path) -> dict[str, Any]:
    problems: list[str] = []
    panel: dict[str, Any] = {"db": False, "note": None}
    db = path / "data" / "copilot.db"
    if not db.is_file():
        panel["note"] = "data/copilot.db 없음 — 앱을 한 번 실행하면 생성됨"
    else:
        try:
            conn = open_ro(db)
        except sqlite3.Error:
            conn = None
            panel["note"] = "data/copilot.db를 열 수 없음"
        if conn is not None:
            try:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                missing = [t for t in REQUIRED_TABLES if t not in tables]
                panel["db"] = True
                if missing:
                    panel["note"] = "스키마 없음: " + ", ".join(missing)
                if "offers" in tables:
                    panel.update(offer_facts(conn, problems))
                if "ledger" in tables:
                    panel["ledger"] = ledger_facts(conn, problems)
            except sqlite3.Error:
                problems.append("DB 읽기 실패")
            finally:
                conn.close()
    panel["bridge"] = bridge_facts(path)
    panel["problems"] = problems
    return panel
