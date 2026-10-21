"""MCP server that lets a Claude session direct All Tomorrow on this host.

Claude attaches over stdio and gets the project registry, per-project git state,
local coding workers (Codex/OpenCode/Kiro/Antigravity) and subscription usage.
Worker runs are spawned as detached processes so they outlive the Claude session;
their files under .artifacts/mcp-runs are the single record of each run.

Runs execute on this PC only. They do not go through the central server's
device-agent queue (see docs/mcp-control.md).
"""
from __future__ import annotations

import ctypes
import importlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastmcp import FastMCP

from all_tomorrow.local_workers import ADAPTERS, list_workers, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_PATH = Path(os.environ.get("ALL_TOMORROW_PROJECTS", REPO_ROOT / "config" / "projects.local.json"))
WORKERS_PATH = Path(os.environ.get("ALL_TOMORROW_WORKERS", REPO_ROOT / "config" / "workers.local.json"))
RUNS_DIR = Path(os.environ.get("ALL_TOMORROW_RUNS", REPO_ROOT / ".artifacts" / "mcp-runs"))
USAGE_MODULE = "all_tomorrow.usage"

mcp = FastMCP(
    "all-tomorrow",
    instructions=(
        "All Tomorrow control plane on the user's PC. Use list_projects/project_status to see managed "
        "projects, dispatch_task to hand coding work to a local worker CLI inside a project, and "
        "get_run to collect the result. A SUCCESS run means the CLI finished; check the project's "
        "actual changes before reporting the requested work as done."
    ),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_projects() -> dict[str, dict[str, Any]]:
    if not PROJECTS_PATH.exists():
        return {}
    return json.loads(PROJECTS_PATH.read_text(encoding="utf-8")).get("projects", {})


def _save_projects(projects: dict[str, dict[str, Any]]) -> None:
    PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_PATH.write_text(json.dumps({"projects": projects}, ensure_ascii=False, indent=2), encoding="utf-8")


def _project(project_id: str) -> dict[str, Any]:
    projects = load_projects()
    if project_id not in projects:
        raise ValueError(f"Unknown project {project_id!r}; known: {sorted(projects)}")
    return projects[project_id]


def _git(path: str, *args: str) -> str:
    result = subprocess.run(["git", "-C", path, *args], capture_output=True, encoding="utf-8",
                            errors="replace", timeout=30, stdin=subprocess.DEVNULL)
    return (result.stdout or result.stderr).strip()


def _worker_config() -> dict[str, Any]:
    """Worker config whose allowed_roots also cover every registered project."""
    config = json.loads(WORKERS_PATH.read_text(encoding="utf-8"))
    roots = list(config.get("allowed_roots", []))
    for project in load_projects().values():
        if Path(project["path"]).is_absolute() and Path(project["path"]).is_dir() and project["path"] not in roots:
            roots.append(project["path"])
    config["allowed_roots"] = roots
    return config


def _pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    # os.kill(pid, 0) terminates the process on Windows, so query it instead.
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


def read_run(run_dir: Path, include_output: bool = True) -> dict[str, Any]:
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    result_path = run_dir / "result.json"
    text = result_path.read_text(encoding="utf-8", errors="replace").strip() if result_path.exists() else ""
    result = None
    if text:
        try:
            result = json.loads(text)
        except ValueError:
            result = None
    if result is not None:
        meta["status"] = result.get("status", "UNKNOWN")
        if include_output:
            meta["result"] = result
    elif _pid_alive(meta["pid"]):
        meta["status"] = "RUNNING"
    else:
        meta["status"] = "INTERRUPTED"
        stderr = run_dir / "stderr.log"
        if include_output and stderr.exists():
            meta["stderr_tail"] = stderr.read_text(encoding="utf-8", errors="replace")[-2000:]
    return meta


@mcp.tool
def list_projects() -> list[dict[str, Any]]:
    """List projects All Tomorrow manages (id, name, path, notes)."""
    return [{"project_id": key, **value} for key, value in load_projects().items()]


@mcp.tool
def register_project(project_id: str, path: str, name: str | None = None, notes: str = "") -> dict[str, Any]:
    """Add or update a managed project. path must be an existing absolute directory."""
    resolved = Path(path)
    if not resolved.is_absolute() or not resolved.is_dir():
        raise ValueError("path must be an existing absolute directory")
    projects = load_projects()
    projects[project_id] = {"name": name or resolved.name, "path": resolved.as_posix(), "notes": notes}
    _save_projects(projects)
    return {"project_id": project_id, **projects[project_id]}


@mcp.tool
def project_status(project_id: str) -> dict[str, Any]:
    """Git branch/changes/recent commits of a project, plus the head of its roadmap or README."""
    project = _project(project_id)
    path = project["path"]
    status: dict[str, Any] = {"project_id": project_id, **project}
    if (Path(path) / ".git").exists():
        status["git_status"] = _git(path, "status", "--short", "--branch")[:4000]
        status["recent_commits"] = _git(path, "log", "--oneline", "-8")
    for doc in ("docs/roadmap.md", "ROADMAP.md", "README.md"):
        doc_path = Path(path) / doc
        if doc_path.exists():
            status["overview_file"] = doc
            status["overview"] = "\n".join(doc_path.read_text(encoding="utf-8", errors="replace").splitlines()[:60])
            break
    return status


@mcp.tool
async def list_local_workers() -> list[dict[str, Any]]:
    """Check which worker CLIs are installed. Does not verify login."""
    return await list_workers(load_config_dict(_worker_config()))


def load_config_dict(config: dict[str, Any]) -> dict[str, Any]:
    # Reuse local_workers validation, which reads from a file.
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / "_validated-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return load_config(path)


def _run_child(run_dir: Path) -> int:
    """Entry point of the detached run process: execute the worker CLI into the run files."""
    argv = json.loads((run_dir / "argv.json").read_text(encoding="utf-8"))
    with open(run_dir / "result.json", "wb") as out, open(run_dir / "stderr.log", "wb") as err:
        return subprocess.run(argv, stdout=out, stderr=err, stdin=subprocess.DEVNULL, cwd=REPO_ROOT).returncode


def _spawn_detached(run_dir: Path) -> tuple[int, str]:
    argv = [sys.executable, "-m", "all_tomorrow.mcp_server", "_run", str(run_dir)]
    if os.name != "nt":
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, cwd=REPO_ROOT, start_new_session=True)
        return process.pid, "session"
    # MCP clients tear down this server's whole process tree when the Claude session ends
    # (observed even with job breakaway). WMI creates the run outside that tree.
    command = subprocess.list2cmdline(argv).replace("'", "''")
    script = (f"$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
              f"@{{CommandLine='{command}'; CurrentDirectory='{REPO_ROOT}'}}; \"$($r.ReturnValue) $($r.ProcessId)\"")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL)
    code, _, pid = result.stdout.strip().partition(" ")
    if code != "0":
        raise RuntimeError(f"WMI process creation failed: {result.stdout.strip()} {result.stderr.strip()[:300]}")
    return int(pid), "wmi"


@mcp.tool
def dispatch_task(project_id: str, worker: str, task: str) -> dict[str, Any]:
    """Start a worker CLI (codex/opencode/kiro/antigravity) on a task inside a project.

    Returns immediately with a run_id; poll get_run for the result. Runs keep going
    after this Claude session ends.
    """
    if worker not in ADAPTERS:
        raise ValueError(f"worker must be one of {sorted(ADAPTERS)}")
    if not task.strip():
        raise ValueError("task must not be empty")
    project = _project(project_id)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    config = load_config_dict(_worker_config())
    (run_dir / "workers.json").write_text(json.dumps(config), encoding="utf-8")
    (run_dir / "task.txt").write_text(task, encoding="utf-8")
    worker_argv = [sys.executable, "-m", "all_tomorrow.local_workers", "--config", str(run_dir / "workers.json"),
                   "run", worker, "--cwd", project["path"], "--project-id", project_id,
                   "--task-file", str(run_dir / "task.txt")]
    (run_dir / "argv.json").write_text(json.dumps(worker_argv), encoding="utf-8")
    pid, spawn = _spawn_detached(run_dir)
    meta = {"run_id": run_id, "project_id": project_id, "worker": worker, "cwd": project["path"],
            "task_preview": task[:200], "started_at": _now(), "pid": pid, "spawn": spawn}
    (run_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {**meta, "status": "RUNNING"}


@mcp.tool
def get_run(run_id: str) -> dict[str, Any]:
    """Status and, once finished, the worker's full result for a dispatched run."""
    run_dir = RUNS_DIR / run_id
    if not (run_dir / "meta.json").exists() or run_dir.parent != RUNS_DIR:
        raise ValueError(f"Unknown run {run_id!r}")
    return read_run(run_dir)


@mcp.tool
def list_runs(project_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Recent dispatched runs, newest first, without full output."""
    if not RUNS_DIR.exists():
        return []
    runs = []
    for run_dir in sorted((d for d in RUNS_DIR.iterdir() if (d / "meta.json").exists()), reverse=True):
        run = read_run(run_dir, include_output=False)
        if project_id is None or run["project_id"] == project_id:
            runs.append(run)
        if len(runs) >= limit:
            break
    return runs


@mcp.tool
def subscription_usage() -> dict[str, Any]:
    """Current Claude/Codex subscription usage windows (same data as the web panel)."""
    # Imported here so the other tools keep working in a checkout without the usage module.
    try:
        usage_module = importlib.import_module(USAGE_MODULE)
    except ModuleNotFoundError as error:
        if error.name != USAGE_MODULE:
            raise
        raise RuntimeError(f"{USAGE_MODULE} is not available in this checkout") from None
    return usage_module.collect()


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "_run":
        raise SystemExit(_run_child(Path(sys.argv[2])))
    mcp.run()


if __name__ == "__main__":
    main()
