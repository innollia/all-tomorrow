"""TINProject (Godot 4 game-kit monorepo) panel facts.

Read-only and bounded: a handful of known files plus one capped directory scan. The
local .git is a Syncthing copy and unreliable, so nothing here touches git. The folder
may be mid-sync: Syncthing temp files (`~syncthing~*.tmp`) are ignored everywhere and a
missing file is reported, never raised.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_IDS = ("tinproject",)

SYNC_TMP_PREFIX = "~syncthing~"
SENTINEL = "modules/stone_story_rpg/PRESENCE.md"
SCORE_FILE = "modules/quote_vn/reports/score.md"
EVAL_FILE = "tools/avatar_judge/eval_report.md"
MAX_READ_BYTES = 512_000
SYNC_SCAN_ENTRIES = 1500     # directory entries looked at while hunting for Syncthing temp files
SYNC_SCAN_SECONDS = 0.25
SYNC_SCAN_SKIP = {".git", ".stversions", ".stfolder", ".godot", ".import", "node_modules"}

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _visible(name: str) -> bool:
    return not name.startswith(SYNC_TMP_PREFIX) and not name.startswith(".")


def _mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    except OSError:
        return None


def _read(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_READ_BYTES)
    except OSError:
        return None
    return data.decode("utf-8-sig", errors="replace")


def _clip(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _unfenced(lines: list[str]) -> list[bool]:
    """True for lines outside ``` / ~~~ code fences (a `# comment` in a code block is no heading)."""
    out, fenced = [], False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            out.append(False)
            continue
        out.append(not fenced)
    return out


def _sections(lines: list[str]) -> list[tuple[int, str, list[str]]]:
    """(level, heading text, body lines up to the next heading of the same or higher level)."""
    plain = _unfenced(lines)
    heads = [(i, len(m.group(1)), m.group(2)) for i, line in enumerate(lines)
             if plain[i] and (m := _HEADING.match(line))]
    out = []
    for n, (i, level, text) in enumerate(heads):
        end = next((j for j, lv, _ in heads[n + 1:] if lv <= level), len(lines))
        out.append((level, text, lines[i + 1:end]))
    return out


def _table_rows(body: list[str]) -> tuple[list[str], list[list[str]]]:
    """First markdown table in body: (header cells, data rows)."""
    for i, line in enumerate(body[:-1]):
        if line.lstrip().startswith("|") and re.match(r"^\s*\|[\s:|-]+\|\s*$", body[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            for row in body[i + 2:]:
                if not row.lstrip().startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            return header, rows
    return [], []


def _count_items(body: list[str]) -> int:
    """Top-level list items only (nested sub-points are not separate items)."""
    plain = _unfenced(body)
    indents = [len(line) - len(line.lstrip()) for i, line in enumerate(body) if plain[i] and _LIST_ITEM.match(line)]
    return sum(1 for n in indents if n <= min(indents) + 1) if indents else 0


# ---------------------------------------------------------------- sync state

def sync_state(root: Path) -> dict[str, Any]:
    """Cheap guess whether Syncthing is still filling the folder; bounded, never a full walk."""
    reasons = []
    if not (root / "project.godot").exists():
        reasons.append("루트 project.godot 없음")
    seen, tmp_found, queue = 0, 0, [root]
    deadline = time.monotonic() + SYNC_SCAN_SECONDS
    while queue and seen < SYNC_SCAN_ENTRIES and time.monotonic() < deadline:
        current = queue.pop(0)
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    seen += 1
                    if entry.name.startswith(SYNC_TMP_PREFIX):
                        tmp_found += 1
                    elif entry.name not in SYNC_SCAN_SKIP and entry.is_dir(follow_symlinks=False):
                        queue.append(Path(entry.path))
                    if seen >= SYNC_SCAN_ENTRIES:
                        break
        except OSError:
            continue
    if tmp_found:
        reasons.append(f"동기화 임시 파일 {tmp_found}개 (제한 탐색)")
    return {"in_progress": bool(reasons), "reasons": reasons, "scanned_entries": seen,
            "scan_complete": not queue}


# ---------------------------------------------------------------- sections

def dryforge(root: Path, notes: list[str]) -> dict[str, Any] | None:
    folder = root / ".dryforge"
    if not folder.is_dir():
        notes.append(".dryforge 없음")
        return None
    out: dict[str, Any] = {"branch": None, "intent": None, "cycles": 0, "latest_cycle": None}
    try:
        cycles = sorted(e.name for e in os.scandir(folder) if e.is_dir() and re.fullmatch(r"\d{3}", e.name))
    except OSError:
        cycles = []
    out["cycles"], out["latest_cycle"] = len(cycles), (cycles[-1] if cycles else None)
    raw = _read(folder / "status.json")
    if raw is None:
        notes.append(".dryforge/status.json 없음")
        return out
    try:
        cycle = (json.loads(raw) or {}).get("current_cycle") or {}
    except (ValueError, AttributeError):
        notes.append(".dryforge/status.json 해석 실패")
        return out
    if isinstance(cycle, dict):
        out["branch"] = _clip(cycle.get("branch"), 120)
        out["intent"] = _clip(cycle.get("intent"), 240)
    return out


def kit_status(folder: Path) -> dict[str, Any] | None:
    file = folder / "IMPLEMENTATION_STATUS.md"
    text = _read(file)
    if text is None:
        return None
    lines = text.splitlines()
    title = None
    updated = branch = None
    for line in lines:
        bare = line.strip().lstrip(">-* ").replace("*", "").strip()
        if title is None and (m := re.match(r"^#\s+(.*)$", line.strip())):
            title = m.group(1).split("—", 1)[-1].strip()
        if updated is None and (m := re.match(r"^최종\s*갱신\s*[:：]\s*(.*)$", bare)):
            date = _DATE.search(m.group(1))
            updated = date.group(0) if date else (m.group(1).strip() or None)
        if branch is None and (m := re.match(r"^브랜치\s*[:：]\s*(.*)$", bare)):
            branch = m.group(1).strip().strip("`").strip() or None
    # Pending user questions: the §0.2-style "waiting for the user" section, counted from its
    # table's 상태 column (rows still marked 대기), or from its list items if there is no table.
    pending = total = None
    for _level, heading, body in _sections(lines):
        if not (re.match(r"^0\.2\b", heading) or re.search(r"답을 기다리|사용자 질문|대기 중인 질문", heading)):
            continue
        header, rows = _table_rows(body)
        col = next((j for j, h in enumerate(header) if h in ("상태", "Status", "status")), None)
        if col is not None:
            total = len(rows)
            pending = sum(1 for r in rows if len(r) > col and "대기" in r[col])
        else:
            total = pending = _count_items(body)
        break
    # A note above the status line saying the user's answers were relayed (the table may lag it).
    head = lines[: next((i for i, line in enumerate(lines) if "최종" in line and "갱신" in line), 30)]
    answer_note = any(line.lstrip().startswith(">") and "사용자 답" in line for line in head)
    return {"kit": folder.name, "title": _clip(title, 80), "updated": _clip(updated, 30),
            "branch": _clip(branch, 120), "pending_questions": pending, "questions": total,
            "answer_note": answer_note, "mtime": _mtime(file)}


def kits(root: Path, notes: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    folder = root / "plans" / "kits"
    try:
        dirs = sorted(e.name for e in os.scandir(folder) if e.is_dir() and _visible(e.name))
    except OSError:
        notes.append("plans/kits 없음")
        return [], []
    found, missing = [], []
    for name in dirs:
        status = kit_status(folder / name)
        (found.append(status) if status else missing.append(name))
    return found, missing


def module_status(file: Path) -> dict[str, Any]:
    text = _read(file)
    if text is None:
        return {"status_file": False}
    next_items = questions = None
    questions_heading = None
    for _level, heading, body in _sections(text.splitlines()):
        if next_items is None and re.match(r"^다음\s*할\s*일", heading):
            next_items = _count_items(body)
        elif questions is None and re.match(r"^질문", heading):
            questions = _count_items(body)
            note = re.search(r"\(([^)]*)\)", heading)
            questions_heading = _clip(note.group(1), 40) if note else None
    return {"status_file": True, "next": next_items, "questions": questions,
            "questions_note": questions_heading, "mtime": _mtime(file)}


def modules(root: Path, notes: list[str]) -> list[dict[str, Any]]:
    folder = root / "modules"
    try:
        names = sorted(e.name for e in os.scandir(folder) if e.is_dir() and _visible(e.name))
    except OSError:
        notes.append("modules 없음")
        return []
    return [{"name": name, **module_status(folder / name / "STATUS.md")} for name in names[:60]]


def quote_score(root: Path) -> dict[str, Any] | None:
    file = root / SCORE_FILE
    text = _read(file)
    if text is None:
        return None
    total = re.search(r"총점\s*\**\s*([\d.]+)\s*/\s*([\d.]+)", text)
    parts = []
    in_total = False
    for line in text.splitlines():
        if (m := _HEADING.match(line)):
            in_total = "총점" in m.group(2)
            continue
        if in_total and (p := re.match(r"^\s*[-*]\s*(?:\d+\)\s*)?(.+?)\s+([\d.]+)\s*$", line)):
            parts.append({"label": _clip(p.group(1), 40), "score": float(p.group(2))})
    return {"total": float(total.group(1)) if total else None, "max": float(total.group(2)) if total else None,
            "parts": parts[:8], "mtime": _mtime(file)}


def judge_eval(root: Path) -> dict[str, Any] | None:
    file = root / EVAL_FILE
    text = _read(file)
    if text is None:
        return None

    def rates(line: str) -> tuple[float | None, float | None]:
        verdict = re.search(r"(?:통과/퇴짜|판정)\s*일치\s*\**\s*([\d.]+)\s*%", line)
        reason = re.search(r"이유\s*일치\s*\**\s*([\d.]+)\s*%", line)
        return (float(verdict.group(1)) if verdict else None, float(reason.group(1)) if reason else None)

    out: dict[str, Any] = {"verdict_pct": None, "reason_pct": None, "basis": None,
                           "first_verdict_pct": None, "first_reason_pct": None, "mtime": _mtime(file)}
    for line in text.splitlines():
        bare = line.strip().lstrip("-* ").replace("*", "")
        if out["verdict_pct"] is None and bare.startswith("최종"):
            out["verdict_pct"], out["reason_pct"] = rates(bare)
            basis = re.match(r"^최종\s*\(([^)]*)\)", bare)
            out["basis"] = _clip(basis.group(1), 40) if basis else None
        elif out["first_verdict_pct"] is None and bare.startswith("처음"):
            out["first_verdict_pct"], out["first_reason_pct"] = rates(bare)
    if out["verdict_pct"] is None:
        # No summary line: fall back to the last row of the per-round table.
        _header, rows = _table_rows(text.splitlines())
        for row in reversed(rows):
            pcts = [float(x) for c in row for x in re.findall(r"\(([\d.]+)%\)", c)]
            if len(pcts) >= 2:
                out["verdict_pct"], out["reason_pct"], out["basis"] = pcts[0], pcts[1], "마지막 회차"
                break
    return out


def sentinel(root: Path, syncing: bool) -> dict[str, Any]:
    present = (root / SENTINEL).is_file()
    state = "present" if present else ("sync_hold" if syncing else "missing")
    return {"path": SENTINEL, "present": present, "state": state}


def collect(path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    notes: list[str] = []
    sync = sync_state(path)
    kit_rows, kits_without_status = kits(path, notes)
    module_rows = modules(path, notes)
    score = quote_score(path)
    if score is None:
        notes.append(f"{SCORE_FILE} 없음")
    judge = judge_eval(path)
    if judge is None:
        notes.append(f"{EVAL_FILE} 없음")
    return {
        "sync": sync,
        "sentinel": sentinel(path, sync["in_progress"]),
        "dryforge": dryforge(path, notes),
        "kits": kit_rows,
        "kits_without_status": kits_without_status[:30],
        "modules": module_rows,
        "quote_score": score,
        "judge_eval": judge,
        "notes": notes,
        "collect_ms": round((time.perf_counter() - started) * 1000),
    }
