from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from all_tomorrow.contracts import (
    ContractError,
    WorkerAdapter,
    WorkerRequest,
    WorkerResult,
    WorkerStatus,
)


class WorkerError(RuntimeError):
    """Internal worker error that should not leak sensitive data."""


def _resolve_cwd(cwd: str | None, allowed_roots: tuple[str, ...]) -> Path:
    """Resolve and validate working directory against allowed roots."""
    if cwd is None:
        raise WorkerError("Working directory must be specified")

    resolved = Path(cwd).resolve()
    allowed = tuple(Path(root).resolve() for root in allowed_roots)

    for root in allowed:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue

    raise WorkerError(f"Working directory {resolved} is outside allowed roots")


def _sanitize_error(error: Exception | str, *, include_traceback: bool = False) -> str:
    """Sanitize error messages to avoid leaking sensitive data or empty strings."""
    msg = str(error)
    home = os.environ.get("HOME")
    if home:
        msg = msg.replace(home, "<HOME>")
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        msg = msg.replace(userprofile, "<USERPROFILE>")
    for key, value in os.environ.items():
        if any(s in key.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            if value and value in msg:
                msg = msg.replace(value, "<REDACTED>")
    return msg


def _check_executable_available(argv: list[str]) -> bool:
    """Check if the executable in argv[0] is available on PATH or as absolute path."""
    if not argv:
        return False
    exe = argv[0]
    if os.path.isabs(exe):
        return os.path.isfile(exe) and (os.access(exe, os.X_OK) or os.name == "nt")
    if shutil.which(exe) is not None:
        return True
    if os.name == "nt" and "." not in Path(exe).name:
        pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
        for ext in pathext:
            candidate = f"{exe}{ext}"
            if shutil.which(candidate) is not None:
                return True
    return False


def _build_worker_prompt(request: WorkerRequest) -> str:
    """Build a structured plain-text prompt from WorkerRequest preserving all context."""
    sections = [
        f"# Task Request [{request.request_id}]",
        f"- Trace ID: {request.trace_id}",
    ]
    if request.project_id:
        sections.append(f"- Project ID: {request.project_id}")
    if request.capabilities:
        sections.append(f"- Capabilities: {', '.join(sorted(request.capabilities))}")

    payload = request.payload

    task = (
        payload.get("task")
        or payload.get("instructions")
        or payload.get("prompt")
        or payload.get("message")
    )
    if task:
        sections.append(f"\n## Instructions\n{task}")
    else:
        extra = {
            k: v
            for k, v in payload.items()
            if k not in ("cwd", "constraints", "acceptance_criteria", "expected_result_format", "result_format")
        }
        if extra:
            sections.append(f"\n## Instructions\n{json.dumps(extra, indent=2)}")
        else:
            sections.append("\n## Instructions\nExecute the requested task.")

    constraints = payload.get("constraints")
    if constraints is not None:
        if isinstance(constraints, (list, tuple)):
            c_text = "\n".join(f"- {c}" for c in constraints)
        elif isinstance(constraints, dict):
            c_text = json.dumps(constraints, indent=2)
        else:
            c_text = str(constraints)
        sections.append(f"\n## Constraints\n{c_text}")

    acceptance_criteria = payload.get("acceptance_criteria")
    if acceptance_criteria is not None:
        if isinstance(acceptance_criteria, (list, tuple)):
            ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria)
        elif isinstance(acceptance_criteria, dict):
            ac_text = json.dumps(acceptance_criteria, indent=2)
        else:
            ac_text = str(acceptance_criteria)
        sections.append(f"\n## Acceptance Criteria\n{ac_text}")

    expected_format = payload.get("expected_result_format") or payload.get("result_format")
    if expected_format is not None:
        if isinstance(expected_format, dict):
            fmt_text = json.dumps(expected_format, indent=2)
        else:
            fmt_text = str(expected_format)
        sections.append(f"\n## Expected Result Format\n{fmt_text}")

    return "\n".join(sections)


async def _run_process_safe(
    *,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
    output_limit_bytes: int,
    request: WorkerRequest,
    worker_name: str,
    start_time: float,
) -> tuple[str, int] | WorkerResult:
    """
    Execute a subprocess with timeout, combined output limit, process reap, and error redaction.
    Returns (stdout_str, duration_ms) on process success (exit code 0 and non-empty output),
    or WorkerResult on any failure.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env},
        )
    except FileNotFoundError:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return WorkerResult(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status=WorkerStatus.EXECUTABLE_NOT_FOUND,
            duration_ms=duration_ms,
            error=_sanitize_error(f"Executable not found: {cmd[0]}"),
        )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except (ProcessLookupError, OSError):
            pass
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return WorkerResult(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status=WorkerStatus.TIMEOUT,
            duration_ms=duration_ms,
            error=f"{worker_name} process timed out after {timeout_seconds}s",
        )

    stdout_str = stdout.decode("utf-8", errors="replace")
    stderr_str = stderr.decode("utf-8", errors="replace")
    duration_ms = int((time.perf_counter() - start_time) * 1000)

    # Combined output limit accounts for stdout plus stderr
    combined_bytes = len(stdout) + len(stderr)
    if combined_bytes > output_limit_bytes:
        return WorkerResult(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status=WorkerStatus.OUTPUT_TOO_LARGE,
            duration_ms=duration_ms,
            error=f"Output exceeds {output_limit_bytes} bytes",
        )

    # Non-zero exit code: redact stderr secrets
    if proc.returncode != 0:
        err_msg = f"Exit code {proc.returncode}"
        if stderr_str.strip():
            sanitized_stderr = _sanitize_error(stderr_str.strip())
            err_msg = f"{err_msg}: {sanitized_stderr}"
        return WorkerResult(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status=WorkerStatus.FAILED,
            duration_ms=duration_ms,
            error=_sanitize_error(err_msg),
        )

    if not stdout_str.strip():
        return WorkerResult(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status=WorkerStatus.EMPTY_OUTPUT,
            duration_ms=duration_ms,
            error=f"{worker_name} produced empty output",
        )

    return stdout_str, duration_ms


class AntigravityWorker:
    """Worker adapter for Antigravity CLI via asyncio subprocess."""

    def __init__(
        self,
        *,
        argv: list[str] | None = None,
        allowed_roots: tuple[str, ...],
        mode: str = "accept-edits",
        dangerously_skip_permissions: bool = False,
        effort: str = "high",
        model: str | None = None,
        output_format: str = "json",
        timeout_seconds: float = 120.0,
        output_limit_bytes: int = 1024 * 1024,
        env: dict[str, str] | None = None,
    ) -> None:
        if argv is None:
            argv = ["agy.exe"] if os.name == "nt" else ["agy"]
        if not argv:
            raise ValueError("argv must not be empty")
        self._argv = list(argv)
        self._allowed_roots = allowed_roots
        self._mode = mode
        self._dangerously_skip_permissions = dangerously_skip_permissions
        self._effort = effort
        self._model = model
        self._output_format = output_format
        self._timeout_seconds = timeout_seconds
        self._output_limit_bytes = output_limit_bytes
        self._env = env or {}

    @property
    def worker_id(self) -> str:
        return "antigravity"

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"coding", "repo_edit", "analysis"})

    async def is_available(self) -> bool:
        return _check_executable_available(self._argv)

    def build_argv(self, prompt: str) -> list[str]:
        """Construct the actual argv command line for Antigravity CLI."""
        cmd = list(self._argv)
        if self._mode:
            cmd.extend(["--mode", self._mode])
        if self._dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        if self._effort:
            cmd.extend(["--effort", self._effort])
        if self._model:
            cmd.extend(["--model", self._model])
        if self._output_format:
            cmd.extend(["--output-format", self._output_format])
        cmd.extend(["--print", prompt])
        return cmd

    async def execute(self, request: WorkerRequest) -> WorkerResult:
        start = time.perf_counter()
        try:
            cwd = _resolve_cwd(request.payload.get("cwd"), self._allowed_roots)
        except WorkerError as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return WorkerResult(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status=WorkerStatus.TRAVERSAL_BLOCKED,
                duration_ms=duration_ms,
                error=_sanitize_error(e),
            )

        prompt = _build_worker_prompt(request)
        cmd = self.build_argv(prompt)

        res = await _run_process_safe(
            cmd=cmd,
            cwd=cwd,
            env=self._env,
            timeout_seconds=self._timeout_seconds,
            output_limit_bytes=self._output_limit_bytes,
            request=request,
            worker_name="Antigravity",
            start_time=start,
        )

        if isinstance(res, WorkerResult):
            return res

        stdout_str, duration_ms = res

        if self._output_format == "json":
            try:
                parsed = json.loads(stdout_str)
                if isinstance(parsed, dict):
                    payload = parsed
                elif isinstance(parsed, list):
                    payload = {"items": parsed}
                else:
                    payload = {"output": str(parsed), "text": stdout_str}
            except (json.JSONDecodeError, ValueError) as e:
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.INVALID_OUTPUT,
                    duration_ms=duration_ms,
                    error=_sanitize_error(e),
                )
        else:
            payload = {"output": stdout_str, "text": stdout_str, "response": stdout_str}

        return WorkerResult(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status=WorkerStatus.SUCCESS,
            payload=payload,
            duration_ms=duration_ms,
        )


class OpenCodeWorker:
    """Worker adapter for OpenCode CLI via asyncio subprocess."""

    def __init__(
        self,
        *,
        argv_prefix: list[str] | None = None,
        allowed_roots: tuple[str, ...],
        model: str | None = None,
        agent: str | None = None,
        format: str = "json",
        auto: bool = False,
        timeout_seconds: float = 180.0,
        output_limit_bytes: int = 1024 * 1024,
        env: dict[str, str] | None = None,
    ) -> None:
        if argv_prefix is None:
            if os.name == "nt":
                argv_prefix = ["npx.cmd", "-y", "opencode-ai", "run"]
            else:
                argv_prefix = ["npx", "-y", "opencode-ai", "run"]
        if not argv_prefix:
            raise ValueError("argv_prefix must not be empty")
        self._argv_prefix = list(argv_prefix)
        self._allowed_roots = allowed_roots
        self._model = model
        self._agent = agent
        self._format = format
        self._auto = auto
        self._timeout_seconds = timeout_seconds
        self._output_limit_bytes = output_limit_bytes
        self._env = env or {}

    @property
    def worker_id(self) -> str:
        return "opencode"

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"coding", "repo_edit", "analysis", "terminal"})

    async def is_available(self) -> bool:
        return _check_executable_available(self._argv_prefix)

    def build_argv(self, prompt: str) -> list[str]:
        """Construct the actual argv command line for OpenCode CLI."""
        cmd = list(self._argv_prefix)
        if self._format:
            cmd.extend(["--format", self._format])
        if self._model:
            cmd.extend(["--model", self._model])
        if self._agent:
            cmd.extend(["--agent", self._agent])
        if self._auto:
            cmd.append("--auto")
        cmd.append(prompt)
        return cmd

    async def execute(self, request: WorkerRequest) -> WorkerResult:
        start = time.perf_counter()
        try:
            cwd = _resolve_cwd(request.payload.get("cwd"), self._allowed_roots)
        except WorkerError as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return WorkerResult(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status=WorkerStatus.TRAVERSAL_BLOCKED,
                duration_ms=duration_ms,
                error=_sanitize_error(e),
            )

        prompt = _build_worker_prompt(request)
        cmd = self.build_argv(prompt)

        res = await _run_process_safe(
            cmd=cmd,
            cwd=cwd,
            env=self._env,
            timeout_seconds=self._timeout_seconds,
            output_limit_bytes=self._output_limit_bytes,
            request=request,
            worker_name="OpenCode",
            start_time=start,
        )

        if isinstance(res, WorkerResult):
            return res

        stdout_str, duration_ms = res

        if self._format == "json":
            try:
                parsed = json.loads(stdout_str)
                if isinstance(parsed, dict):
                    payload = parsed
                elif isinstance(parsed, list):
                    payload = {"items": parsed}
                else:
                    payload = {"output": str(parsed), "text": stdout_str}
            except (json.JSONDecodeError, ValueError):
                # Try parsing as newline-delimited JSON events
                events = []
                lines = [line.strip() for line in stdout_str.splitlines() if line.strip()]
                parsed_any = False
                for line in lines:
                    try:
                        events.append(json.loads(line))
                        parsed_any = True
                    except (json.JSONDecodeError, ValueError):
                        pass
                if parsed_any and events:
                    payload = {"events": events, "output": stdout_str}
                else:
                    return WorkerResult(
                        request_id=request.request_id,
                        trace_id=request.trace_id,
                        status=WorkerStatus.INVALID_OUTPUT,
                        duration_ms=duration_ms,
                        error=_sanitize_error(ValueError("Output is not valid JSON")),
                    )
        else:
            payload = {"output": stdout_str, "text": stdout_str}

        return WorkerResult(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status=WorkerStatus.SUCCESS,
            payload=payload,
            duration_ms=duration_ms,
        )


async def register_available_workers(
    registry: Any,
    *,
    antigravity_argv: list[str] | None = None,
    opencode_argv_prefix: list[str] | None = None,
    allowed_roots: tuple[str, ...],
    **worker_kwargs: Any,
) -> list[str]:
    """
    Register workers that are actually available (executable exists).
    Returns list of registered worker IDs.
    """
    from all_tomorrow.contracts import Worker
    from all_tomorrow.registry import WorkerService

    def _register(meta: Worker, adapter: Any) -> None:
        if isinstance(registry, WorkerService):
            registry.register_worker(meta, adapter)
        else:
            registry.register_worker(meta)

    registered = []

    if antigravity_argv is not None:
        worker = AntigravityWorker(argv=antigravity_argv, allowed_roots=allowed_roots, **worker_kwargs)
        if await worker.is_available():
            meta = Worker(
                worker_id=worker.worker_id,
                capabilities=worker.capabilities,
                status="available",
            )
            _register(meta, worker)
            registered.append(worker.worker_id)

    if opencode_argv_prefix is not None:
        worker = OpenCodeWorker(argv_prefix=opencode_argv_prefix, allowed_roots=allowed_roots, **worker_kwargs)
        if await worker.is_available():
            meta = Worker(
                worker_id=worker.worker_id,
                capabilities=worker.capabilities,
                status="available",
            )
            _register(meta, worker)
            registered.append(worker.worker_id)

    return registered