"""video-factory panel: per-episode pipeline stage, QA state and board approvals.

Each episode is videos/<id>/. The stage is the furthest pipeline file present
(docs/pipeline.md order). QA comes from review/: the preflight summary lines
("- 결함 N건", "- 주의 N건"), "## 판정" lines in report.md that are not "통과",
and open items in notes.md/report.md (unchecked "- [ ]" boxes and "남은 것:" labels).
Only file names, mtimes, the brief's first heading and those counts are read out;
.env and script/report bodies never leave this module.
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_IDS = ("video-factory",)

# (key, path relative to videos/<id>/); "{id}" is the episode id.
STAGES = (
    ("brief", "brief.md"),
    ("facts", "facts.md"),
    ("script", "script.md"),
    ("shots", "shots.md"),
    ("timeline", "timeline.json"),
    ("review", "review"),
    ("output", "output/{id}.mp4"),
    ("youtube", "youtube.md"),
)
MAX_EPISODES = 40
TITLE_MAX = 120
HEAD_LIMIT = 8_000
TEXT_LIMIT = 256_000

HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$")
TITLE_LINE = re.compile(r"^\s*(?:[-*]\s+)?(?:제목|title)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)
DEFECTS = re.compile(r"^\s*-\s*결함\s*(\d+)\s*건", re.MULTILINE)
WARNINGS = re.compile(r"^\s*-\s*주의\s*(\d+)\s*건", re.MULTILINE)
UNCHECKED = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\[ \]", re.MULTILINE)
REMAINING = re.compile(r"^\s*[-*+]\s+(?:\*\*)?(?:남은 것|남은 일|수정 필요|미해결)(?:\*\*)?\s*[:：]", re.MULTILINE)
VERDICT_LINE = re.compile(r"^\s*[-*+]\s+(?:\*\*)?([^:：*]+?)(?:\*\*)?\s*[:：]")


def _iso(ts: float) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds") if ts else None


def _read(path: Path, limit: int = TEXT_LIMIT) -> str:
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def brief_title(brief: Path) -> str | None:
    for line in _read(brief, HEAD_LIMIT).splitlines():
        match = HEADING.match(line) or TITLE_LINE.match(line)
        if match:
            return match.group(1)[:TITLE_MAX]
    return None


def _verdict(report: str) -> tuple[int, int] | None:
    """(pass, fail) from report.md's "## 판정" list, or None when the report has no verdict."""
    lines = report.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^##\s+판정\s*$", line)), None)
    if start is None:
        return None
    passed = failed = 0
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        match = VERDICT_LINE.match(line)
        if not match:
            continue
        if match.group(1).strip() == "통과":
            passed += 1
        else:
            failed += 1
    return passed, failed


def review_qa(review: Path) -> dict[str, Any] | None:
    if not review.is_dir():
        return None
    preflight = _read(review / "preflight.md", HEAD_LIMIT)  # summary lines sit at the top
    report = _read(review / "report.md")
    notes = _read(review / "notes.md")
    defects = DEFECTS.search(preflight)
    warnings = WARNINGS.search(preflight)
    verdict = _verdict(report)
    unchecked = len(UNCHECKED.findall(notes)) + len(UNCHECKED.findall(report))
    remaining = len(REMAINING.findall(notes)) + len(REMAINING.findall(report))
    qa = {
        "defects": int(defects.group(1)) if defects else None,
        "warnings": int(warnings.group(1)) if warnings else None,
        "verdict_pass": verdict[0] if verdict else None,
        "verdict_fail": verdict[1] if verdict else None,
        "unchecked": unchecked,
        "remaining": remaining,
    }
    qa["open"] = (qa["defects"] or 0) + (qa["verdict_fail"] or 0) + unchecked + remaining
    return qa


def board_counts(status_file: Path) -> dict[str, int] | None:
    """board/status.json maps script line -> 승인/수정 (board.mjs stores OK as 승인)."""
    if not status_file.is_file():
        return None
    try:
        data = json.loads(_read(status_file) or "{}")
    except ValueError:
        return {"ok": 0, "fix": 0, "other": 0, "invalid": 1}
    counts = {"ok": 0, "fix": 0, "other": 0}
    for value in (data.values() if isinstance(data, dict) else ()):
        text = str(value).strip()
        if text == "승인" or text.lower() == "ok":
            counts["ok"] += 1
        elif text == "수정":
            counts["fix"] += 1
        else:
            counts["other"] += 1
    return counts


def episode(folder: Path) -> dict[str, Any]:
    ep_id = folder.name
    present, newest = [], 0.0
    for key, rel in STAGES:
        target = folder / rel.format(id=ep_id)
        if target.exists():
            present.append(key)
            newest = max(newest, _mtime(target))
    keys = [key for key, _ in STAGES]
    stage = present[-1] if present else None  # STAGES order, so the last hit is the furthest
    reached = keys.index(stage) + 1 if stage else 0
    final = folder / "output" / f"{ep_id}.mp4"
    final_mtime = _mtime(final)
    return {
        "id": ep_id,
        "title": brief_title(folder / "brief.md"),
        "stage": stage,
        "stage_index": reached,
        "stage_total": len(STAGES),
        "skipped": [key for key in keys[:max(reached - 1, 0)] if key not in present],
        "qa": review_qa(folder / "review"),
        "final": bool(final_mtime),
        "final_at": _iso(final_mtime),
        "board": board_counts(folder / "board" / "status.json"),
        "updated": _iso(newest),
    }


def review_render(out: Path) -> dict[str, Any]:
    newest_name, newest = None, 0.0
    try:
        with os.scandir(out) as it:
            for entry in it:
                if entry.name.endswith("-review.mp4") and entry.is_file():
                    mtime = entry.stat().st_mtime
                    if mtime > newest:
                        newest_name, newest = entry.name, mtime
    except OSError:
        pass
    return {"video": newest_name, "video_at": _iso(newest), "log_at": _iso(_mtime(out / "render-review.log"))}


def collect(path: Path) -> dict[str, Any]:
    try:
        with os.scandir(path / "videos") as it:
            folders = [Path(e.path) for e in it if e.is_dir() and not e.name.startswith(".")]
    except OSError:
        folders = []
    episodes = [episode(folder) for folder in sorted(folders)[:MAX_EPISODES]]
    episodes.sort(key=lambda e: e["updated"] or "", reverse=True)
    board = {"ok": 0, "fix": 0, "other": 0}
    for ep in episodes:
        for key in board:
            board[key] += (ep["board"] or {}).get(key, 0)
    return {
        "episodes": episodes,
        "more": max(0, len(folders) - MAX_EPISODES),
        "review_render": review_render(path / "out"),
        "board": board,
    }
