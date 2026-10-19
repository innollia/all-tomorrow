"""Projects snapshot for the central console, collected on the PC that holds the projects.

The server is small, so all work happens here: git, roadmap parsing and per-project
plugins (all_tomorrow.project_panels). The server only stores and serves the result.

  python -m all_tomorrow.projects_snapshot show [project_id]
  python -m all_tomorrow.projects_snapshot push --url https://<server>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from all_tomorrow.project_panels import plugins

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = Path(os.environ.get("ALL_TOMORROW_PROJECTS", REPO_ROOT / "config" / "projects.local.json"))
PANEL_MAX_BYTES = 20_000
GIT_TIMEOUT = 5  # a broken or huge repo must not stall the whole snapshot
STATUS_FILES = ("docs/roadmap.md", "ROADMAP.md", "docs/status.md", "STATUS.md")


def _git(path: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, encoding="utf-8",
                                errors="replace", timeout=GIT_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def git_facts(path: Path) -> dict[str, Any] | None:
    if not (path / ".git").exists():
        return None
    last = _git(path, "log", "-1", "--format=%cs%x09%s")
    if not last:
        # No readable HEAD (no commits yet, or HEAD points at a missing object). `git status`
        # can take tens of seconds on such trees and tells us nothing, so skip it.
        return {"branch": None, "last_commit": None, "last_subject": None, "dirty_files": None,
                "commits_30d": 0, "problem": "HEAD를 읽을 수 없음 (커밋 없음 또는 저장소 손상)"}
    date, _, subject = last.partition("\t")
    status = _git(path, "status", "--porcelain")
    return {
        "branch": _git(path, "rev-parse", "--abbrev-ref", "HEAD"),
        "last_commit": date or None,
        "last_subject": subject[:120] or None,
        "dirty_files": len(status.splitlines()) if status else 0,
        "commits_30d": len(_git(path, "log", "--since=30.days", "--format=%h").splitlines()),
    }


def latest_mtime(path: Path, limit: int = 4000) -> str | None:
    """Newest file time, skipping heavy folders; bounded so huge trees stay cheap."""
    newest, seen = 0.0, 0
    skip = {".git", "node_modules", ".venv", "venv", "__pycache__", ".artifacts", "dist", "build", ".godot"}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for name in files:
            seen += 1
            try:
                newest = max(newest, os.stat(os.path.join(root, name)).st_mtime)
            except OSError:
                pass
            if seen >= limit:
                break
        if seen >= limit:
            break
    return datetime.fromtimestamp(newest, UTC).date().isoformat() if newest else None


def status_table(path: Path) -> list[dict[str, str]]:
    """First markdown table with a 상태/Status column in a known status file: (item, status) rows."""
    for name in STATUS_FILES:
        file = path / name
        if not file.exists():
            continue
        lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines[:-1]):
            if not line.lstrip().startswith("|") or not re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
                continue
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            col = next((j for j, h in enumerate(header) if h in ("상태", "Status", "status")), None)
            if col is None:
                continue
            rows = []
            for row in lines[i + 2:]:
                if not row.lstrip().startswith("|"):
                    break
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                if len(cells) > col:
                    label = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cells[0 if col else 1])
                    rows.append({"item": label[:100], "status": cells[col][:30]})
            if rows:
                return rows[:25]
    return []


def load_registry() -> dict[str, dict[str, Any]]:
    if not REGISTRY.exists():
        return {}
    return json.loads(REGISTRY.read_text(encoding="utf-8")).get("projects", {})


def collect_project(project_id: str, entry: dict[str, Any], plugin_map: dict[str, Any]) -> dict[str, Any]:
    path = Path(entry["path"])
    item: dict[str, Any] = {
        "id": project_id, "name": entry.get("name", project_id), "notes": entry.get("notes", ""),
        "links": entry.get("links", []), "exists": path.is_dir(),
    }
    if not item["exists"]:
        return item
    item["git"] = git_facts(path)
    item["last_activity"] = (item["git"] or {}).get("last_commit") or latest_mtime(path)
    item["status_table"] = status_table(path)
    plugin = plugin_map.get(project_id)
    if plugin:
        try:
            panel = plugin.collect(path)
            encoded = json.dumps(panel, ensure_ascii=False)
            item["panel"] = panel if len(encoded.encode()) <= PANEL_MAX_BYTES else {"error": "panel data over size cap"}
        except Exception as error:  # noqa: BLE001 - one broken plugin must not drop the snapshot
            item["panel"] = {"error": type(error).__name__}
    return item


def collect(only: str | None = None) -> dict[str, Any]:
    plugin_map = plugins()
    entries = [(pid, entry) for pid, entry in sorted(load_registry().items()) if only is None or pid == only]
    # Mostly waiting on git subprocesses, so threads are enough.
    with ThreadPoolExecutor(max_workers=8) as pool:
        projects = list(pool.map(lambda item: collect_project(item[0], item[1], plugin_map), entries))
    return {"collected_at": datetime.now(UTC).isoformat(timespec="seconds"), "projects": projects}


def push(snapshot: dict[str, Any], url: str, token: str) -> int:
    request = urllib.request.Request(
        url.rstrip("/") + "/internal/projects", data=json.dumps(snapshot, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {token}", "content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="projects_snapshot")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("project_id", nargs="?")
    push_parser = sub.add_parser("push")
    push_parser.add_argument("--url", default=os.environ.get("ALL_TOMORROW_URL"))
    # Same collector credential as the usage push.
    push_parser.add_argument("--token-env", default="ALL_TOMORROW_USAGE_TOKEN")
    args = parser.parse_args(argv)
    if args.command == "show":
        print(json.dumps(collect(args.project_id), ensure_ascii=False, indent=2))
        return 0
    token = os.environ.get(args.token_env)
    if not args.url or not token:
        print(f"--url (or ALL_TOMORROW_URL) and ${args.token_env} are required", file=sys.stderr)
        return 2
    print(push(collect(), args.url, token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
