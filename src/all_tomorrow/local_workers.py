"""Host-local composition of the existing WorkerService (no server or queue)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from all_tomorrow.adapters.workers import (
    AntigravityWorker, CodexWorker, KiroWorker, OpenCodeWorker, _worker_environment,
)
from all_tomorrow.contracts import Worker, WorkerRequest, WorkerStatus
from all_tomorrow.registry import WorkerService


ADAPTERS = {"antigravity": AntigravityWorker, "opencode": OpenCodeWorker,
            "codex": CodexWorker, "kiro": KiroWorker}
EXECUTABLES = {"antigravity": "agy", "opencode": "opencode", "codex": "codex", "kiro": "kiro-cli"}


def discover_executable(worker_id: str) -> str | None:
    executable = shutil.which(EXECUTABLES[worker_id])
    if executable:
        return executable
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        return None
    local = Path(os.environ["LOCALAPPDATA"])
    patterns = {
        "antigravity": "agy/bin/agy.exe",
        "codex": "OpenAI/Codex/bin/*/codex.exe",
        "kiro": "Kiro-Cli/kiro-cli.exe",
        "opencode": "npm-cache/_npx/*/node_modules/opencode-ai/bin/opencode.exe",
    }
    candidates = [p for p in local.glob(patterns[worker_id]) if p.is_file()]
    return str(max(candidates, key=lambda p: p.stat().st_mtime)) if candidates else None


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    roots = config.get("allowed_roots")
    if not isinstance(roots, list) or not roots:
        raise ValueError("Configuration requires non-empty allowed_roots")
    if any(not isinstance(p, str) or not Path(p).is_absolute() or not Path(p).is_dir() for p in roots):
        raise ValueError("allowed_roots must be existing absolute directories")
    if not isinstance(config.get("workers"), dict) or not config["workers"]:
        raise ValueError("Configuration requires workers")
    if set(config["workers"]) - ADAPTERS.keys():
        raise ValueError("Unknown worker in configuration")
    return config


def configured_adapters(config: dict[str, Any]) -> dict[str, Any]:
    adapters = {}
    for worker_id, entry in config["workers"].items():
        if entry.get("enabled", True) is False:
            continue
        argv = entry.get("argv")
        if argv is None:
            argv = [discover_executable(worker_id) or EXECUTABLES[worker_id]]
            if worker_id == "opencode":
                argv.append("run")
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv):
            raise ValueError(f"Invalid argv for {worker_id}")
        options = dict(entry.get("options", {}))
        # Config stores names, never credential values. Explicit opt-in per worker.
        env_names = entry.get("env_names", [])
        if not isinstance(env_names, list) or any(not isinstance(n, str) for n in env_names):
            raise ValueError(f"Invalid env_names for {worker_id}")
        if any(k in options for k in ("env", "argv", "argv_prefix", "allowed_roots")):
            raise ValueError("Use top-level argv, allowed_roots and env_names")
        options["env"] = {name: os.environ[name] for name in env_names if name in os.environ}
        options["allowed_roots"] = tuple(config["allowed_roots"])
        options["argv_prefix" if worker_id == "opencode" else "argv"] = argv
        adapters[worker_id] = ADAPTERS[worker_id](**options)
    return adapters


async def build_worker_service(config: dict[str, Any]) -> WorkerService:
    service = WorkerService()
    for worker_id, adapter in configured_adapters(config).items():
        if await adapter.is_available():
            service.register_worker(Worker(worker_id, adapter.capabilities, status="available"), adapter)
    return service


async def list_workers(config: dict[str, Any]) -> list[dict[str, Any]]:
    async def inspect(worker_id: str, adapter: Any) -> dict[str, Any]:
        available = await adapter.is_available()
        argv = adapter._argv_prefix if isinstance(adapter, OpenCodeWorker) else adapter._argv
        row = {"worker_id": worker_id, "executable_available": available,
               "authentication": "not_checked", "version": None}
        if available:
            # OpenCode's configured prefix includes run; version belongs to the binary.
            version_argv = argv[:-1] if worker_id == "opencode" and argv[-1] == "run" else argv
            try:
                result = await asyncio.to_thread(subprocess.run, [*version_argv, "--version"],
                    capture_output=True, timeout=30, stdin=subprocess.DEVNULL,
                    env=_worker_environment({}), encoding="utf-8", errors="replace")
                if result.returncode == 0:
                    row["version"] = result.stdout.strip()[:200]
                else:
                    row["probe_error"] = f"version probe exited {result.returncode}"
            except (OSError, subprocess.TimeoutExpired):
                row["probe_error"] = "version probe failed or timed out"
        return row
    return list(await asyncio.gather(*(inspect(k, v) for k, v in configured_adapters(config).items())))


async def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.command == "list":
        print(json.dumps(await list_workers(config), ensure_ascii=False, indent=2))
        return 0
    service = await build_worker_service(config)
    if not service.has_worker(args.worker):
        raise ValueError(f"Worker is disabled or executable is unavailable: {args.worker}")
    task = args.task_file.read_text(encoding="utf-8") if args.task_file else args.task
    if not task or not task.strip():
        raise ValueError("Task must not be empty")
    request = WorkerRequest(
        request_id=str(uuid4()), trace_id=str(uuid4()), project_id=args.project_id,
        capabilities=service.get_adapter(args.worker).capabilities,
        payload={"cwd": str(args.cwd.resolve()), "task": task})
    result = await service.execute(args.worker, request)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.status == WorkerStatus.SUCCESS else 1


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/workers.local.json"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="Check installed CLIs; does not verify authentication")
    execution = subparsers.add_parser("run")
    execution.add_argument("worker", choices=tuple(ADAPTERS))
    execution.add_argument("--cwd", type=Path, required=True)
    execution.add_argument("--project-id")
    prompt = execution.add_mutually_exclusive_group(required=True)
    prompt.add_argument("--task")
    prompt.add_argument("--task-file", type=Path)
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args)))
    except (OSError, ValueError, TypeError) as error:
        # Configuration errors must not dump credential values or task contents.
        from all_tomorrow.adapters.workers import _sanitize_error
        print(json.dumps({"status": "FAILED", "error": _sanitize_error(error)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
