"""wobnovel panel: implementation log, Studio DB and the canonical Muvel works.

Reads only:
- docs/tracking/status.md: section titles, dates and how many "미확인" items each has.
- .studio/studio-muvel.sqlite3, opened read-only: counts and the latest runs' ids/status/times.
- ~/Documents/MuvelProjects/<work>/episodes/*.mvle: names and mtimes only, never their text,
  plus the work id from <work>/*.muvl to label Studio runs.

Never opens novelpiacr/ (crawler cookies), scratch/ or any manuscript body.
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

PROJECT_IDS = ("wobnovel",)

STATUS_FILE = Path("docs") / "tracking" / "status.md"
STUDIO_DB = Path(".studio") / "studio-muvel.sqlite3"
READ_LIMIT = 2_000_000
META_LIMIT = 64_000
RECENT_SECTIONS = 5
RECENT_RUNS = 5
MAX_WORKS = 40
TITLE_MAX = 120

SECTION = re.compile(r"^##\s+(?P<title>.+?)\s*$")
TRAILING_DATE = re.compile(r"^(?P<title>.*?)\s*[—–-]+\s*(?P<date>\d{4}-\d{2}-\d{2})$")
LEADING_DATE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<title>.+)$")
# "- 미확인: ...", "**미확인**: ...", or a "미확인:" / "### 미확인" label whose items follow as bullets.
UNVERIFIED = re.compile(r"^(?P<indent>\s*)(?P<mark>[-*+]\s+|#{3,6}\s+)?(?:\*\*)?미확인(?:\s*(?:사항|항목|부분))?(?:\*\*)?\s*(?:[:：](?P<rest>.*))?$")
BULLET = re.compile(r"^(?P<indent>\s*)(?:[-*+]|\d+\.)\s+\S")
NOTHING = {"없음", "없다", "-"}


def works_root() -> Path:
    """Canonical Muvel works live outside the repository, in the user's Documents folder."""
    return Path.home() / "Documents" / "MuvelProjects"


def _iso(ts: float) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds") if ts else None


def _read(path: Path, limit: int = READ_LIMIT) -> str | None:
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------- status.md

def _count_unverified(lines: list[str]) -> int:
    count, label_indent = 0, None  # label_indent: collecting bullets under an empty "미확인:" label
    for line in lines:
        if label_indent is not None:
            bullet = BULLET.match(line)
            if bullet and len(bullet.group("indent")) > label_indent:
                count += 1
                continue
            if not line.strip():
                continue
            label_indent = None
        match = UNVERIFIED.match(line)
        if not match:
            continue
        rest = (match.group("rest") or "").strip()
        if not rest:  # bare label: its items are the bullets nested under it
            heading = (match.group("mark") or "").startswith("#")
            label_indent = -1 if heading else len(match.group("indent"))
        elif rest.rstrip(".") not in NOTHING:
            count += 1
    return count


def _sections(text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        heading = SECTION.match(line)
        if heading:
            raw = heading.group("title").strip()
            trailing, leading = TRAILING_DATE.match(raw), LEADING_DATE.match(raw)
            found = trailing or leading
            title = (found.group("title") if found else raw).strip() or raw
            current = {"title": title[:TITLE_MAX], "date": found.group("date") if found else None, "lines": []}
            sections.append(current)
        elif current is not None:
            current["lines"].append(line)
    for section in sections:
        section["unverified"] = _count_unverified(section.pop("lines"))
    return sections


def status_summary(path: Path) -> dict[str, Any] | None:
    text = _read(path / STATUS_FILE)
    if text is None:
        return None
    sections = _sections(text)
    dated = [s for s in sections if s["date"]]
    # The log is newest-first, but older dated notes also get appended at the bottom:
    # rank by date and keep file order for ties.
    ranked = sorted(dated, key=lambda s: s["date"], reverse=True) or sections
    newest = ranked[0] if ranked else None
    return {
        "title": newest["title"] if newest else None,
        "date": newest["date"] if newest else None,
        "unverified": newest["unverified"] if newest else 0,
        "sections": len(sections),
        "recent": ranked[:RECENT_SECTIONS],
    }


# ---------------------------------------------------------------- works

def _work_id(folder: Path) -> str | None:
    try:
        with os.scandir(folder) as it:
            candidates = [e for e in it if e.name.endswith(".muvl") and e.is_file()]
    except OSError:
        return None
    for entry in candidates:
        try:
            if entry.stat().st_size > META_LIMIT:
                continue
            data = json.loads(_read(Path(entry.path), META_LIMIT) or "")
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            return data["id"]
    return None


def works_summary(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Episode counts per work folder; also returns {work id: folder name} for labelling runs."""
    try:
        with os.scandir(root) as it:
            folders = sorted((e for e in it if e.is_dir() and not e.name.startswith(".")), key=lambda e: e.name)
    except OSError:
        return {"found": False, "items": []}, {}
    items, ids = [], {}
    for entry in folders[:MAX_WORKS]:
        folder = Path(entry.path)
        episodes, newest = 0, 0.0
        has_episodes = (folder / "episodes").is_dir()
        if has_episodes:
            try:
                with os.scandir(folder / "episodes") as it:
                    for episode in it:
                        if episode.name.endswith(".mvle") and episode.is_file():
                            episodes += 1
                            newest = max(newest, episode.stat().st_mtime)
            except OSError:
                pass
        work_id = _work_id(folder)
        if not has_episodes and work_id is None:
            continue  # not a Muvel work folder
        if work_id:
            ids[work_id] = entry.name
        items.append({"title": entry.name[:TITLE_MAX], "episodes": episodes, "newest": _iso(newest)})
    items.sort(key=lambda w: w["newest"] or "", reverse=True)
    return {"found": True, "items": items, "more": max(0, len(folders) - MAX_WORKS)}, ids


# ---------------------------------------------------------------- Studio DB

def studio_summary(path: Path, work_titles: dict[str, str]) -> dict[str, Any] | None:
    db = path / STUDIO_DB
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{quote(db.as_posix(), safe='/:')}?mode=ro", uri=True, timeout=0.5)
    except sqlite3.Error as error:
        return {"error": type(error).__name__}
    try:
        tables = {row[0] for row in con.execute("select name from sqlite_master where type='table'")}

        def columns(table: str) -> set[str]:
            return {row[1] for row in con.execute(f'pragma table_info("{table}")')} if table in tables else set()

        def count(table: str, where: str = "") -> int | None:
            if table not in tables:
                return None
            return con.execute(f'select count(*) from "{table}" {where}').fetchone()[0]

        approvals = columns("studio_approvals")
        runs: list[dict[str, Any]] = []
        run_cols = columns("studio_runs")
        if {"run_id", "status"} <= run_cols:
            at = next((c for c in ("started_at", "created_at") if c in run_cols), None)
            picks = ["run_id", "status", *(c for c in ("engine", "work_id", "updated_at") if c in run_cols)]
            if at:
                picks.append(at)
            order = f"order by {at} desc" if at else "order by rowid desc"
            for row in con.execute(f'select {", ".join(picks)} from studio_runs {order} limit {RECENT_RUNS}'):
                rec = dict(zip(picks, row))
                runs.append({"id": str(rec["run_id"])[:8], "status": rec["status"], "engine": rec.get("engine"),
                             "work": work_titles.get(rec.get("work_id") or ""), "at": rec.get(at) if at else None,
                             "updated": rec.get("updated_at")})
        return {
            "approvals_pending": count("studio_approvals", "where status = 'pending'" if "status" in approvals else ""),
            "sessions": count("studio_sessions"),
            "runs": count("studio_runs"),
            "revisions": count("document_revisions"),
            "recent_runs": runs,
        }
    except sqlite3.Error as error:
        return {"error": type(error).__name__}
    finally:
        con.close()


def collect(path: Path) -> dict[str, Any]:
    works, work_titles = works_summary(works_root())
    return {
        "status": status_summary(path),
        "studio": studio_summary(path, work_titles),
        "works": works,
    }
