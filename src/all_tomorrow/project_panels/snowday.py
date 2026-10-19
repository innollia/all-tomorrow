"""Snow Day (team GameMaker RPG prototype) panel facts.

Reads only notes/TODO/TODO.txt, notes/build_*.log and the existence of
dialogue-preview/index.html. Never opens 디스코드대화/ (other people's messages) or
.gmcache. Build logs carry local paths and licence arguments, so only the result,
exit code and path-stripped `Error :` lines leave this module.
"""
from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_IDS = ("snowday-orig",)

TODO_FILE = "notes/TODO/TODO.txt"
PREVIEW_FILE = "dialogue-preview/index.html"
MAX_LOGS = 8
MAX_READ_BYTES = 2_000_000
SYNC_TMP_PREFIX = "~syncthing~"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_WIN_PATH = re.compile(r"[A-Za-z]:[\\/][^\s\"']*")
# GameMaker CLI (clack-style step lines) and Igor final markers. "|  Success" lines are
# per-step and appear in failed builds too, so they are not a build result.
_FAILED = re.compile(r"^\s*x\s+Failed\b", re.MULTILINE)
_SUCCEEDED = re.compile(r"^\s*\*\s+Compilation finished\b|Igor complete\.", re.MULTILINE)
_EXIT = re.compile(r"Igor exited with code (-?\d+)")
_ERROR_LINE = re.compile(r"^\s*\|?\s*Error\s*:\s*(.+)$", re.MULTILINE)


def _mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    except OSError:
        return None


def _decode(data: bytes) -> str:
    """Build logs come from PowerShell redirects (UTF-16 LE with BOM) or plain UTF-8."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if len(data) > 3 and data[1:2] == b"\x00" and data[3:4] == b"\x00":
        return data.decode("utf-16-le", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def _read(path: Path, tail: bool = False) -> str | None:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if tail and size > MAX_READ_BYTES:
                head = handle.read(4)  # keep the BOM so the encoding is still detectable
                handle.seek(size - MAX_READ_BYTES + (MAX_READ_BYTES % 2))
                data = (head[:2] if head[:2] in (b"\xff\xfe", b"\xfe\xff") else b"") + handle.read()
            else:
                data = handle.read(MAX_READ_BYTES)
    except OSError:
        return None
    return _decode(data)


def todo_counts(root: Path) -> dict[str, Any] | None:
    """`- 항목 - 성공!` = done, `- 항목 - 진행 중` = in progress, `- 항목` = not started."""
    file = root / TODO_FILE
    text = _read(file)
    if text is None:
        return None
    counts = {"done": 0, "in_progress": 0, "todo": 0, "other": 0}
    for line in text.splitlines():
        line = line.strip()
        if not re.match(r"^[-*]\s+\S", line):
            continue
        item = line[1:].strip()
        status = item.rsplit(" - ", 1)[1].strip() if " - " in item else ""
        if not status:
            counts["todo"] += 1
        elif re.search(r"성공|완료|done", status, re.IGNORECASE):
            counts["done"] += 1
        elif "진행" in status:
            counts["in_progress"] += 1
        else:
            counts["other"] += 1
    return {**counts, "total": sum(counts.values()), "mtime": _mtime(file)}


def _clean(line: str, limit: int = 120) -> str:
    """Strip local paths (they carry user names) and clip."""
    text = " ".join(_WIN_PATH.sub("…", line).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_result(file: Path) -> dict[str, Any]:
    text = _read(file, tail=True)
    out: dict[str, Any] = {"name": file.name, "mtime": _mtime(file), "result": "unreadable",
                           "exit_code": None, "errors": 0, "first_error": None, "last_step": None}
    if text is None:
        return out
    text = _ANSI.sub("", text).replace("\r", "")
    exit_codes = [int(c) for c in _EXIT.findall(text)]
    errors = [m.group(1) for m in _ERROR_LINE.finditer(text)]
    out["exit_code"] = exit_codes[-1] if exit_codes else None
    out["errors"] = len(errors)
    if errors:
        out["first_error"] = _clean(errors[0])
    failed = _FAILED.search(text)
    # Last "|  ..." step line before the end (or before "x Failed"): where the build stopped.
    steps = re.findall(r"^\s*\|\s+(\S.*)$", text[: failed.start()] if failed else text, re.MULTILINE)
    out["last_step"] = _clean(steps[-1]) if steps else None
    if failed or (exit_codes and exit_codes[-1] != 0):
        out["result"] = "fail"
    elif _SUCCEEDED.search(text) or (exit_codes and exit_codes[-1] == 0):
        out["result"] = "success"
    else:
        out["result"] = "incomplete"  # no final marker: interrupted, hung or still running
    return out


def builds(root: Path) -> list[dict[str, Any]]:
    stamped = []
    for file in (root / "notes").glob("build_*.log"):
        if file.name.startswith(SYNC_TMP_PREFIX):
            continue
        try:
            stamped.append((file.stat().st_mtime, file.name, file))
        except OSError:
            continue
    stamped.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [build_result(file) for _mtime_value, _name, file in stamped[:MAX_LOGS]]


def collect(path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    notes: list[str] = []
    todo = todo_counts(path)
    if todo is None:
        notes.append(f"{TODO_FILE} 없음")
    logs = builds(path)
    if not logs:
        notes.append("notes/build_*.log 없음")
    # Synced copies get the copy time as mtime, so "newest" can be a coin flip.
    stamps = [datetime.fromisoformat(log["mtime"]) for log in logs[:2] if log["mtime"]]
    ambiguous = len(stamps) == 2 and abs((stamps[0] - stamps[1]).total_seconds()) < 5
    preview = path / PREVIEW_FILE
    return {
        "todo": todo,
        "latest_build": logs[0] if logs else None,
        "latest_ambiguous": ambiguous,
        "builds": logs,
        "dialogue_preview": {"exists": preview.is_file(), "mtime": _mtime(preview) if preview.is_file() else None},
        "notes": notes,
        "collect_ms": round((time.perf_counter() - started) * 1000),
    }
