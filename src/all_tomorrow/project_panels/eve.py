"""eve-scene-runtime panel: gate status, local git refs, Discord audit counts, manager session, SQLite files.

Everything read here is the local copy on this PC; production state lives on EC2. Read-only and
offline: git only reads local refs (never fetch, never `remote -v`, never the remote config, whose
URL carries a token), and the audit/session files are reduced to counts and statuses. Message
contents, snippets, error bodies and ids are never copied out.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from all_tomorrow.projects_snapshot import _git

PROJECT_IDS = ("eve-scene-runtime",)

BASE_BRANCH = "main"
EDGE_BRANCH = "feature/all-tomorrow-edge"
DESKTOP_PREFIXES = ("refs/heads/desktop/", "refs/remotes/desktop/")
DOC_MAX_BYTES = 256_000
AUDIT_MAX_BYTES = 2_000_000  # tail window; the real file is ~130 KB
SESSION_MAX_BYTES = 1_000_000
MAX_EVENT_KINDS = 30
MAX_SQLITE_FILES = 20

# `- **Gate 4.5 (Name)**: **PASS (100% Verified)** (2026-09-20)` — the date is optional (HANDOVER omits it).
GATE_LINE = re.compile(
    r"^- \*\*Gate\s+([0-9A-Za-z.]+)\s*(?:\(([^)]*)\))?\*\*\s*:\s*\*\*([^*]+)\*\*\s*(?:\((\d{4}-\d{2}-\d{2})\))?")


# ---------------------------------------------------------------- helpers
def _read_head(file: Path, limit: int) -> str | None:
    try:
        with file.open("rb") as handle:
            return handle.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


def _section(text: str, number: int) -> list[str]:
    """Lines under the `## <number>.` heading, up to the next `## ` heading."""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].lstrip().startswith(f"{number}.")
            continue
        if inside:
            out.append(line)
    return out


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _short(value: Any, limit: int = 80) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


# ---------------------------------------------------------------- gates
def _gate_key(gate: str) -> tuple:
    return tuple(int(part) if part.isdigit() else 0 for part in gate.split("."))


def gate_status(path: Path) -> dict[str, Any] | None:
    """HANDOVER.md §1 status block + AGENTS.md §6 gate list (AGENTS wins; it carries the dates)."""
    handover = _read_head(path / "HANDOVER.md", DOC_MAX_BYTES)
    agents = _read_head(path / "AGENTS.md", DOC_MAX_BYTES)
    if handover is None and agents is None:
        return None
    handover_lines = _section(handover or "", 1)

    status_line = None
    in_fence = False
    for line in handover_lines:
        if line.strip().startswith("```"):
            if in_fence:
                break
            in_fence = True
            continue
        if in_fence and line.strip():
            status_line = line.strip()[:200]
            break

    def parse(lines: list[str]) -> dict[str, dict[str, Any]]:
        found = {}
        for line in lines:
            match = GATE_LINE.match(line)
            if match:
                found[match[1]] = {"gate": match[1][:12], "name": _short(match[2], 120),
                                   "result": match[3].strip()[:60], "date": match[4]}
        return found

    from_handover = parse(handover_lines)
    from_agents = parse(_section(agents or "", 6))
    gates = []
    for gate in sorted(set(from_handover) | set(from_agents), key=_gate_key):
        entry = dict(from_agents.get(gate) or from_handover[gate])
        entry["in_agents"] = gate in from_agents
        entry["in_handover"] = gate in from_handover
        other = from_handover.get(gate)
        if other and gate in from_agents and other["result"].split()[0] != entry["result"].split()[0]:
            entry["handover_result"] = other["result"]
        gates.append(entry)
    return {"handover_status": status_line, "gates": gates[:40]}


# ---------------------------------------------------------------- git (local refs only)
REF_FORMAT = f"%(refname)%09%(committerdate:iso-strict)%09%(ahead-behind:{BASE_BRANCH})"
REF_FORMAT_PLAIN = "%(refname)%09%(committerdate:iso-strict)"


def _ref_patterns() -> list[str]:
    return [f"refs/heads/{BASE_BRANCH}", f"refs/remotes/origin/{BASE_BRANCH}", *DESKTOP_PREFIXES,
            f"refs/heads/{EDGE_BRANCH}"]


def _refs(path: Path) -> dict[str, dict[str, Any]]:
    """refname -> {date, ahead, behind} where ahead/behind are relative to BASE_BRANCH."""
    refs: dict[str, dict[str, Any]] = {}
    out = _git(path, "for-each-ref", f"--format={REF_FORMAT}", *_ref_patterns())
    if out:
        for line in out.splitlines():
            name, _, rest = line.partition("\t")
            date, _, counts = rest.partition("\t")
            ahead, _, behind = counts.partition(" ")
            refs[name] = {"date": date or None, "ahead": int(ahead) if ahead.isdigit() else None,
                          "behind": int(behind) if behind.isdigit() else None}
        return refs
    # git < 2.41 has no %(ahead-behind:...): list refs, then count each against the base in parallel.
    out = _git(path, "for-each-ref", f"--format={REF_FORMAT_PLAIN}", *_ref_patterns())
    for line in out.splitlines():
        name, _, date = line.partition("\t")
        refs[name] = {"date": date or None, "ahead": None, "behind": None}
    wanted = [name for name in refs if name != f"refs/heads/{BASE_BRANCH}"]
    if not wanted or f"refs/heads/{BASE_BRANCH}" not in refs:
        return refs
    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = pool.map(lambda name: _git(path, "rev-list", "--left-right", "--count",
                                            f"{name}...refs/heads/{BASE_BRANCH}"), wanted)
        for name, count in zip(wanted, counts):
            left, _, right = count.partition("\t")
            if left.isdigit() and right.isdigit():
                refs[name]["ahead"], refs[name]["behind"] = int(left), int(right)
    refs[f"refs/heads/{BASE_BRANCH}"].update(ahead=0, behind=0)
    return refs


def _worktree_for(porcelain: str, branch: str) -> dict[str, Any] | None:
    for block in porcelain.split("\n\n"):
        lines = block.splitlines()
        if f"branch refs/heads/{branch}" not in lines:
            continue
        where = next((line[len("worktree "):] for line in lines if line.startswith("worktree ")), "")
        return {"name": Path(where).name[:80] or None, "missing": any(line.startswith("prunable") for line in lines)}
    return None


def git_panel(path: Path, refs: dict[str, dict[str, Any]], worktrees: str) -> dict[str, Any]:
    main = refs.get(f"refs/heads/{BASE_BRANCH}")
    origin = refs.get(f"refs/remotes/origin/{BASE_BRANCH}")
    result: dict[str, Any] = {"base": BASE_BRANCH, "main": None, "desktop": None, "edge": None}
    if main and origin and origin["ahead"] is not None:
        # origin's ahead/behind are relative to main, so main's are the mirror image.
        result["main"] = {"ahead": origin["behind"], "behind": origin["ahead"], "origin_date": origin["date"]}
    elif main:
        result["main"] = {"ahead": None, "behind": None, "origin_date": None}
    fetch_head = path / ".git" / "FETCH_HEAD"
    try:
        result["origin_fetched_at"] = _iso(fetch_head.stat().st_mtime)
    except OSError:
        result["origin_fetched_at"] = None

    desktop = [(name, info) for name, info in refs.items() if name.startswith(DESKTOP_PREFIXES)]
    if desktop:
        floor = datetime.min.replace(tzinfo=UTC)
        name, info = max(desktop, key=lambda item: _ts(item[1]["date"]) or floor)
        short = name.removeprefix("refs/heads/").removeprefix("refs/remotes/")
        result["desktop"] = {"count": len(desktop), "newest": short[:100], "date": info["date"],
                             "ahead": info["ahead"], "behind": info["behind"]}

    edge = refs.get(f"refs/heads/{EDGE_BRANCH}")
    if edge:
        result["edge"] = {"branch": EDGE_BRANCH, "date": edge["date"], "ahead": edge["ahead"],
                          "behind": edge["behind"],
                          "merged": None if edge["ahead"] is None else edge["ahead"] == 0,
                          "worktree": _worktree_for(worktrees, EDGE_BRANCH)}
    return result


# ---------------------------------------------------------------- Discord audit
def audit_summary(file: Path) -> dict[str, Any] | None:
    """Per-event counts of the audit log tail; only `event`, `ok` and `timestamp` are read."""
    try:
        size = file.stat().st_size
        with file.open("rb") as handle:
            start = max(0, size - AUDIT_MAX_BYTES)
            handle.seek(start)
            data = handle.read(AUDIT_MAX_BYTES)
    except OSError:
        return None
    lines = data.split(b"\n")
    if start:
        lines = lines[1:]  # the window starts mid-line
    counts: Counter[str] = Counter()
    failed: Counter[str] = Counter()
    total = bad = 0
    last = last_failure = None
    for raw in lines:
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        if not isinstance(record, dict):
            bad += 1
            continue
        event = str(record.get("event") or "?")[:60]
        when = _ts(record.get("timestamp"))
        total += 1
        counts[event] += 1
        if when and (last is None or when > last):
            last = when
        if event.endswith("_failed") or record.get("ok") is False:
            failed[event] += 1
            if when and (last_failure is None or when > last_failure):
                last_failure = when
    failures = sum(failed.values())
    ranked = counts.most_common()
    return {
        "total": total, "failures": failures, "failure_ratio": round(failures / total, 4) if total else None,
        "last_event_at": last.isoformat(timespec="seconds") if last else None,
        "last_failure_at": last_failure.isoformat(timespec="seconds") if last_failure else None,
        "events": [{"event": event, "count": count, "failed": failed[event]} for event, count in ranked[:MAX_EVENT_KINDS]],
        "other_events": sum(count for _, count in ranked[MAX_EVENT_KINDS:]),
        "bad_lines": bad, "truncated": start > 0, "file_bytes": size,
    }


# ---------------------------------------------------------------- manager session
def session_summary(file: Path) -> dict[str, Any] | None:
    try:
        if file.stat().st_size > SESSION_MAX_BYTES:
            return {"error": "file too large"}
        data = json.loads(file.read_bytes())
    except OSError:
        return None
    except ValueError:
        return {"error": "unparseable"}
    if not isinstance(data, dict):
        return {"error": "unexpected shape"}
    chars, threshold = _int(data.get("pureDialogueChars")), _int(data.get("threshold"))
    rollover = data.get("rolloverState") if isinstance(data.get("rolloverState"), dict) else {}
    refresh = data.get("lastDocumentRefresh") if isinstance(data.get("lastDocumentRefresh"), dict) else {}
    return {
        "chars": chars, "threshold": threshold,
        "pct": round(100 * chars / threshold, 1) if chars is not None and threshold else None,
        "turns": _int(data.get("turnCount")),
        "rollover_status": _short(rollover.get("status"), 40),
        "doc_refresh_ok": refresh.get("ok") if isinstance(refresh.get("ok"), bool) else None,
        "doc_refresh_at": _short(refresh.get("completedAt"), 40),
        "saved_at": _short(data.get("savedAt"), 40),
    }


# ---------------------------------------------------------------- SQLite files (no rows read)
def sqlite_files(data_dir: Path) -> list[dict[str, Any]]:
    out = []
    try:
        files = sorted(data_dir.glob("*.sqlite"))[:MAX_SQLITE_FILES]
    except OSError:
        return out
    for file in files:
        try:
            stat = file.stat()
        except OSError:
            continue
        try:
            wal = file.with_name(file.name + "-wal").stat()
        except OSError:
            wal = None
        out.append({"name": file.name[:80], "bytes": stat.st_size, "wal_bytes": wal.st_size if wal else 0,
                    "mtime": _iso(max(stat.st_mtime, wal.st_mtime if wal else 0))})
    return out


# ---------------------------------------------------------------- entry point
def collect(path: Path) -> dict[str, Any]:
    has_git = (path / ".git").exists()
    with ThreadPoolExecutor(max_workers=2) as pool:
        # git process start-up dominates (~150 ms each on Windows), so overlap it with the file reads.
        refs_job = pool.submit(_refs, path) if has_git else None
        worktrees_job = pool.submit(_git, path, "worktree", "list", "--porcelain") if has_git else None
        panel: dict[str, Any] = {
            "status": gate_status(path),
            "audit": audit_summary(path / "data" / "discord-audit.jsonl"),
            "session": session_summary(path / "data" / "manager-session-state.json"),
            "sqlite": sqlite_files(path / "data"),
        }
        panel["git"] = git_panel(path, refs_job.result(), worktrees_job.result()) if has_git else None
    return panel
