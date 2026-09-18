from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
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


def _sanitize_error(error: Exception, *, include_traceback: bool = False) -> str:
    """Sanitize error messages to avoid leaking sensitive data."""
    msg = str(error)
    redacted = msg.replace(os.environ.get("HOME", ""), "<HOME>")
    redacted = redacted.replace(os.environ.get("USERPROFILE", ""), "<USERPROFILE>")
    for key, value in os.environ.items():
        if "KEY" in key.upper() or "TOKEN" in key.upper() or "SECRET" in key.upper() or "PASSWORD" in key.upper():
            if value and value in redacted:
                redacted = redacted.replace(value, "<REDACTED>")
    return redacted


def _check_executable_available(argv: list[str]) -> bool:
    """Check if the executable in argv[0] is available on PATH or as absolute path."""
    exe = argv[0]
    if os.path.isabs(exe):
        return os.path.isfile(exe) and os.access(exe, os.X_OK)
    return shutil.which(exe) is not None


async def _run_subprocess(
    argv: list[str],
    cwd: Path,
    *,
    timeout_seconds: float,
    output_limit_bytes: int,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run subprocess with timeout and output limits. Returns (exit_code, stdout, stderr)."""
    if not _check_executable_available(argv):
        raise WorkerError(f"Executable not found: {argv[0]}")

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
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
        except ProcessLookupError:
            pass
        raise WorkerError(f"Process timed out after {timeout_seconds}s") from None

    stdout_str = stdout.decode("utf-8", errors="replace")
    stderr_str = stderr.decode("utf-8", errors="replace")

    if len(stdout_str.encode("utf-8")) > output_limit_bytes:
        raise WorkerError(f"Output exceeds limit of {output_limit_bytes} bytes")

    if proc.returncode != 0:
        raise WorkerError(
            f"Process exited with code {proc.returncode}",
        )

    if not stdout_str.strip():
        raise WorkerError("Process produced empty output")

    return proc.returncode, stdout_str, stderr_str


class AntigravityWorker:
    """Worker adapter for Antigravity CLI via asyncio subprocess."""

    def __init__(
        self,
        *,
        argv: list[str],
        allowed_roots: tuple[str, ...],
        model: str = "opus",
        effort: str = "high",
        timeout_seconds: float = 120.0,
        output_limit_bytes: int = 1024 * 1024,
        env: dict[str, str] | None = None,
    ) -> None:
        if not argv:
            raise ValueError("argv must not be empty")
        self._argv = list(argv)
        self._allowed_roots = allowed_roots
        self._model = model
        self._effort = effort
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

        full_argv = [
            *self._argv,
            "--model",
            self._model,
            "--effort",
            self._effort,
            "--json",
        ]

        input_data = json.dumps(
            {
                "request_id": request.request_id,
                "trace_id": request.trace_id,
                "project_id": request.project_id,
                "capabilities": list(request.capabilities),
                "payload": request.payload,
            }
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_argv,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **self._env},
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=input_data.encode("utf-8")),
                    timeout=self._timeout_seconds,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
                duration_ms = int((time.perf_counter() - start) * 1000)
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.TIMEOUT,
                    duration_ms=duration_ms,
                    error=f"Antigravity process timed out after {self._timeout_seconds}s",
                )

            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
            duration_ms = int((time.perf_counter() - start) * 1000)

            if proc.returncode != 0:
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.FAILED,
                    duration_ms=duration_ms,
                    error=_sanitize_error(WorkerError(f"Exit code {proc.returncode}")),
                )

            if len(stdout_str.encode("utf-8")) > self._output_limit_bytes:
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.OUTPUT_TOO_LARGE,
                    duration_ms=duration_ms,
                    error=f"Output exceeds {self._output_limit_bytes} bytes",
                )

            if not stdout_str.strip():
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.EMPTY_OUTPUT,
                    duration_ms=duration_ms,
                    error="Antigravity produced empty output",
                )

            try:
                payload = json.loads(stdout_str)
                if not isinstance(payload, dict):
                    raise ValueError("Output is not a JSON object")
            except (json.JSONDecodeError, ValueError) as e:
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.INVALID_OUTPUT,
                    duration_ms=duration_ms,
                    error=_sanitize_error(e),
                )

            return WorkerResult(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status=WorkerStatus.SUCCESS,
                payload=payload,
                duration_ms=duration_ms,
            )

        except WorkerError:
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return WorkerResult(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status=WorkerStatus.FAILED,
                duration_ms=duration_ms,
                error=_sanitize_error(e),
            )


class OpenCodeWorker:
    """Worker adapter for OpenCode CLI via asyncio subprocess."""

    def __init__(
        self,
        *,
        argv_prefix: list[str] | None = None,
        allowed_roots: tuple[str, ...],
        model: str = "default",
        agent: str = "default",
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

        full_argv = [
            *self._argv_prefix,
            "--model",
            self._model,
            "--agent",
            self._agent,
        ]

        input_data = json.dumps(
            {
                "request_id": request.request_id,
                "trace_id": request.trace_id,
                "project_id": request.project_id,
                "capabilities": list(request.capabilities),
                "payload": request.payload,
            }
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_argv,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **self._env},
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=input_data.encode("utf-8")),
                    timeout=self._timeout_seconds,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
                duration_ms = int((time.perf_counter() - start) * 1000)
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.TIMEOUT,
                    duration_ms=duration_ms,
                    error=f"OpenCode process timed out after {self._timeout_seconds}s",
                )

            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
            duration_ms = int((time.perf_counter() - start) * 1000)

            if proc.returncode != 0:
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.FAILED,
                    duration_ms=duration_ms,
                    error=_sanitize_error(WorkerError(f"Exit code {proc.returncode}")),
                )

            if len(stdout_str.encode("utf-8")) > self._output_limit_bytes:
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.OUTPUT_TOO_LARGE,
                    duration_ms=duration_ms,
                    error=f"Output exceeds {self._output_limit_bytes} bytes",
                )

            if not stdout_str.strip():
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.EMPTY_OUTPUT,
                    duration_ms=duration_ms,
                    error="OpenCode produced empty output",
                )

            try:
                payload = json.loads(stdout_str)
                if not isinstance(payload, dict):
                    raise ValueError("Output is not a JSON object")
            except (json.JSONDecodeError, ValueError) as e:
                return WorkerResult(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=WorkerStatus.INVALID_OUTPUT,
                    duration_ms=duration_ms,
                    error=_sanitize_error(e),
                )

            return WorkerResult(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status=WorkerStatus.SUCCESS,
                payload=payload,
                duration_ms=duration_ms,
            )

        except WorkerError:
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return WorkerResult(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status=WorkerStatus.FAILED,
                duration_ms=duration_ms,
                error=_sanitize_error(e),
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

    registered = []

    if antigravity_argv is not None:
        worker = AntigravityWorker(argv=antigravity_argv, allowed_roots=allowed_roots, **worker_kwargs)
        if await worker.is_available():
            registry.register_worker(
                Worker(
                    worker_id=worker.worker_id,
                    capabilities=worker.capabilities,
                    status="available",
                )
            )
            registered.append(worker.worker_id)

    if opencode_argv_prefix is not None:
        worker = OpenCodeWorker(argv_prefix=opencode_argv_prefix, allowed_roots=allowed_roots, **worker_kwargs)
        if await worker.is_available():
            registry.register_worker(
                Worker(
                    worker_id=worker.worker_id,
                    capabilities=worker.capabilities,
                    status="available",
                )
            )
            registered.append(worker.worker_id)

    return registered