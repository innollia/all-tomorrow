"""money panel: agent-run side-income research tracked in 진행현황.csv.

Reads the task table (id, name, status, next action) and the real-world counters
(실제지원/실제판매/현금수령검증) from the CSV, the date on README's "기준일:" line,
and only file names/mtimes from 보고서/ and 문서/실행기준_v*.md. README and report
bodies are never returned.
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_IDS = ("money",)

CSV_FILE = "진행현황.csv"
COUNTERS = (("applied", "실제지원"), ("sold", "실제판매"), ("cash_verified", "현금수령검증"))
CSV_LIMIT = 1_000_000
README_LIMIT = 64_000
MAX_TASKS = 50
CELL_MAX = 120
BASE_DATE = re.compile(r"기준일\s*[:：]\s*(.+)")
VERSION = re.compile(r"^실행기준_v(\d+(?:\.\d+)*)\.md$")


def _iso(ts: float) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds") if ts else None


def decode(raw: bytes) -> str:
    """Agents on Windows may save the CSV as UTF-8 (with or without BOM) or as cp949."""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def progress(path: Path) -> dict[str, Any] | None:
    file = path / CSV_FILE
    try:
        if file.stat().st_size > CSV_LIMIT:
            return {"error": "too large"}
        text = decode(file.read_bytes())
    except OSError:
        return None
    reader = csv.DictReader(io.StringIO(text))
    totals = {key: {"sum": 0, "unknown": 0} for key, _ in COUNTERS}
    tasks = []
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items() if isinstance(v, str)}
        if not any(row.values()):
            continue
        for key, column in COUNTERS:
            value = row.get(column, "")
            if re.fullmatch(r"\d+", value):
                totals[key]["sum"] += int(value)
            elif value:
                totals[key]["unknown"] += 1  # e.g. "미확인"
        if len(tasks) < MAX_TASKS:
            tasks.append({"id": row.get("작업ID", "")[:20], "name": row.get("작업명", "")[:CELL_MAX],
                          "status": row.get("상태", "")[:CELL_MAX], "next": row.get("다음행동", "")[:CELL_MAX]})
    return {"tasks": tasks, "totals": totals}


def base_date(path: Path) -> str | None:
    try:
        with open(path / "README.md", "rb") as handle:
            text = decode(handle.read(README_LIMIT))
    except OSError:
        return None
    for line in text.splitlines():
        match = BASE_DATE.search(line)
        if match:
            # Keep only the value ("2026-10-18, Asia/Seoul"), not the sentences that follow it.
            return match.group(1).split(". ")[0].strip().rstrip(".")[:40] or None
    return None


def _files(folder: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(folder) as it:
            return [entry for entry in it if entry.is_file() and not entry.name.startswith(".")]
    except OSError:
        return []


def newest_report(path: Path) -> dict[str, Any] | None:
    entries = _files(path / "보고서")
    if not entries:
        return None
    stamped = [(entry.stat().st_mtime, entry.name) for entry in entries]
    mtime, name = max(stamped)
    return {"name": name, "at": _iso(mtime), "count": len(entries)}


def latest_standard(path: Path) -> dict[str, Any] | None:
    versions = []
    for entry in _files(path / "문서"):
        match = VERSION.match(entry.name)
        if match:
            versions.append((tuple(int(p) for p in match.group(1).split(".")), match.group(1), entry))
    if not versions:
        return None
    _, version, entry = max(versions, key=lambda v: v[0])
    return {"version": f"v{version}", "name": entry.name, "at": _iso(entry.stat().st_mtime), "count": len(versions)}


def collect(path: Path) -> dict[str, Any]:
    return {
        "progress": progress(path),
        "base_date": base_date(path),
        "report": newest_report(path),
        "standard": latest_standard(path),
    }
