"""innollia.github.io panel: Hugo content counts, chronicle stats and a public-repo data warning.

The chronicle file holds personal notes. Only its `gen` field and the numeric/date fields of
`stats` are read out; entry bodies, titles and topics never leave this module. Whether the file
is tracked is checked against the local index only (no network).
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from all_tomorrow.projects_snapshot import GIT_TIMEOUT

PROJECT_IDS = ("innollia-github-io",)

CHRONICLE = "static/chronicle/data.json"
CHRONICLE_MAX_BYTES = 16_000_000  # the real file is ~1.6 MB; json.load once is cheap at that size
STAT_KEYS = ("n", "sealed", "first", "last", "imgs", "chars")
MAX_CONTENT_FILES = 5000
MAX_SECTIONS = 30
TRACKED_WARNING = "공개 저장소에 개인 메모 데이터 커밋됨"


def content_counts(content: Path) -> dict[str, Any] | None:
    """Markdown pages per top-level section of content/, not counting section lists (_index.md)."""
    try:
        sections = sorted(entry for entry in content.iterdir() if entry.is_dir() and not entry.name.startswith("."))
    except OSError:
        return None
    counts: dict[str, int] = {}
    seen = 0
    truncated = False
    for section in sections[:MAX_SECTIONS]:
        pages = 0
        for root, dirs, files in os.walk(section):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            pages += sum(1 for name in files if name.endswith(".md") and not name.startswith("_index"))
            seen += len(files)
            if seen >= MAX_CONTENT_FILES:
                truncated = True
                break
        counts[section.name[:60]] = pages
        if truncated:
            break
    return {"sections": counts, "total": sum(counts.values()), "truncated": truncated}


def chronicle_stats(file: Path) -> dict[str, Any] | None:
    try:
        stat = file.stat()
    except OSError:
        return None
    info: dict[str, Any] = {"bytes": stat.st_size,
                            "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds")}
    if stat.st_size > CHRONICLE_MAX_BYTES:
        info["error"] = "file too large"
        return info
    try:
        data = json.loads(file.read_bytes())
    except OSError:
        info["error"] = "unreadable"
        return info
    except ValueError:
        info["error"] = "unparseable"
        return info
    if not isinstance(data, dict):
        info["error"] = "unexpected shape"
        return info
    gen = data.get("gen")
    info["gen"] = gen[:40] if isinstance(gen, str) else None
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    for key in STAT_KEYS:
        value = stats.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            info[key] = value
        elif isinstance(value, str):
            info[key] = value[:40]
        else:
            info[key] = None
    return info


def is_tracked(path: Path, relative: str) -> bool | None:
    """True/False from the local git index; None when git is unavailable or the folder is not a repo."""
    if not (path / ".git").exists():
        return None
    try:
        result = subprocess.run(["git", "-C", str(path), "ls-files", "--error-unmatch", "--", relative],
                                capture_output=True, timeout=GIT_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {0: True, 1: False}.get(result.returncode)


def collect(path: Path) -> dict[str, Any]:
    tracked = is_tracked(path, CHRONICLE)
    return {
        "content": content_counts(path / "content"),
        "chronicle": chronicle_stats(path / CHRONICLE),
        "chronicle_path": CHRONICLE,
        "chronicle_tracked": tracked,
        "warnings": [TRACKED_WARNING] if tracked else [],
    }
