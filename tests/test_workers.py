from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from all_tomorrow.adapters.workers import AntigravityWorker, OpenCodeWorker, register_available_workers
from all_tomorrow.contracts import WorkerRequest, WorkerResult, WorkerStatus


class FakeProcess:
    """Fake subprocess for testing without calling real processes."""

    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        delay: float = 0.001,
        should_timeout: bool = False,
    ) -> None:
        self._returncode = returncode
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")
        self._delay = delay
        self._should_timeout = should_timeout
        self.killed = False
        self.communicate_called = False
        self.stdin_data: bytes | None = None

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.communicate_called = True
        self.stdin_data = input
        if self._should_timeout:
            raise asyncio.TimeoutError()
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._stdout, self._stderr

    async def wait(self) -> int:
        return self._returncode

    def kill(self) -> None:
        self.killed = True

    @property
    def returncode(self) -> int:
        return self._returncode


def make_worker_request(
    *,
    request_id: str = "req_test",
    trace_id: str = "trace_test",
    project_id: str | None = "proj_test",
    capabilities: frozenset[str] = frozenset({"coding"}),
    payload: dict | None = None,
) -> WorkerRequest:
    if payload is None:
        payload = {"cwd": "/allowed/project"}
    return WorkerRequest(
        request_id=request_id,
        trace_id=trace_id,
        project_id=project_id,
        capabilities=capabilities,
        payload=payload,
    )


class TestAntigravityWorker:
    @pytest.mark.asyncio
    async def test_successful_execution_returns_parsed_json(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(
            returncode=0,
            stdout=json.dumps({"result": "success", "files_changed": 3}),
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.SUCCESS
        assert result.payload == {"result": "success", "files_changed": 3}
        assert result.duration_ms > 0
        assert result.error is None
        fake_proc.communicate_called = True
        assert fake_proc.stdin_data is not None
        input_json = json.loads(fake_proc.stdin_data.decode("utf-8"))
        assert input_json["request_id"] == request.request_id
        assert input_json["trace_id"] == request.trace_id

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(should_timeout=True)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=0.1,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.TIMEOUT
        assert result.error is not None
        assert "timed out" in result.error
        assert fake_proc.killed

    @pytest.mark.asyncio
    async def test_nonzero_exit_returns_failed_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(returncode=1, stderr="compilation error")

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.FAILED
        assert result.error is not None
        assert "Exit code 1" in result.error

    @pytest.mark.asyncio
    async def test_empty_output_returns_empty_output_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(returncode=0, stdout="   \n\t  ")

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.EMPTY_OUTPUT
        assert result.error is not None
        assert "empty output" in result.error.lower()

    @pytest.mark.asyncio
    async def test_oversized_output_returns_output_too_large_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        large_output = "x" * (2 * 1024 * 1024)
        fake_proc = FakeProcess(returncode=0, stdout=large_output)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
                output_limit_bytes=1024 * 1024,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.OUTPUT_TOO_LARGE
        assert result.error is not None
        assert "exceeds" in result.error

    @pytest.mark.asyncio
    async def test_invalid_json_output_returns_invalid_output_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(returncode=0, stdout="not valid json {")

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.INVALID_OUTPUT
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_traversal_blocked_outside_allowed_roots(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()

        worker = AntigravityWorker(
            argv=["antigravity"],
            allowed_roots=(str(project_dir),),
            timeout_seconds=10.0,
        )
        request = make_worker_request(payload={"cwd": str(outside_dir)})

        result = await worker.execute(request)

        assert result.status is WorkerStatus.TRAVERSAL_BLOCKED
        assert result.error is not None
        assert "outside allowed roots" in result.error

    @pytest.mark.asyncio
    async def test_missing_cwd_raises_error(self, tmp_path: Path) -> None:
        worker = AntigravityWorker(
            argv=["antigravity"],
            allowed_roots=(str(tmp_path),),
            timeout_seconds=10.0,
        )
        request = make_worker_request(payload={"cwd": None})

        result = await worker.execute(request)

        assert result.status is WorkerStatus.TRAVERSAL_BLOCKED
        assert result.error is not None
        assert "must be specified" in result.error

    @pytest.mark.asyncio
    async def test_is_available_checks_executable(self, tmp_path: Path) -> None:
        with patch("shutil.which", return_value="/usr/bin/antigravity"):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
            )
            assert await worker.is_available() is True

        with patch("shutil.which", return_value=None):
            worker = AntigravityWorker(
                argv=["nonexistent"],
                allowed_roots=(str(tmp_path),),
            )
            assert await worker.is_available() is False


class TestOpenCodeWorker:
    @pytest.mark.asyncio
    async def test_successful_execution_returns_parsed_json(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(
            returncode=0,
            stdout=json.dumps({"result": "opencode success", "changes": 5}),
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = OpenCodeWorker(
                argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.SUCCESS
        assert result.payload == {"result": "opencode success", "changes": 5}
        assert result.duration_ms > 0
        assert result.error is None
        assert fake_proc.stdin_data is not None
        input_json = json.loads(fake_proc.stdin_data.decode("utf-8"))
        assert input_json["request_id"] == request.request_id

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(should_timeout=True)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = OpenCodeWorker(
                argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=0.1,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.TIMEOUT
        assert result.error is not None
        assert "timed out" in result.error
        assert fake_proc.killed

    @pytest.mark.asyncio
    async def test_nonzero_exit_returns_failed_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(returncode=2, stderr="agent error")

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = OpenCodeWorker(
                argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.FAILED
        assert result.error is not None
        assert "Exit code 2" in result.error

    @pytest.mark.asyncio
    async def test_empty_output_returns_empty_output_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(returncode=0, stdout="")

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = OpenCodeWorker(
                argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.EMPTY_OUTPUT
        assert result.error is not None
        assert "empty output" in result.error.lower()

    @pytest.mark.asyncio
    async def test_oversized_output_returns_output_too_large_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        large_output = "y" * (2 * 1024 * 1024)
        fake_proc = FakeProcess(returncode=0, stdout=large_output)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = OpenCodeWorker(
                argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
                output_limit_bytes=1024 * 1024,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.OUTPUT_TOO_LARGE
        assert result.error is not None
        assert "exceeds" in result.error

    @pytest.mark.asyncio
    async def test_invalid_json_output_returns_invalid_output_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(returncode=0, stdout="not json")

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = OpenCodeWorker(
                argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
                timeout_seconds=10.0,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.INVALID_OUTPUT
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_traversal_blocked_outside_allowed_roots(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()

        worker = OpenCodeWorker(
            argv_prefix=["opencode"],
            allowed_roots=(str(project_dir),),
            timeout_seconds=10.0,
        )
        request = make_worker_request(payload={"cwd": str(outside_dir)})

        result = await worker.execute(request)

        assert result.status is WorkerStatus.TRAVERSAL_BLOCKED
        assert result.error is not None
        assert "outside allowed roots" in result.error

    @pytest.mark.asyncio
    async def test_is_available_checks_executable(self, tmp_path: Path) -> None:
        with patch("shutil.which", return_value="/usr/bin/npx"):
            worker = OpenCodeWorker(
                argv_prefix=["npx", "-y", "opencode-ai", "run"],
                allowed_roots=(str(tmp_path),),
            )
            assert await worker.is_available() is True

        with patch("shutil.which", return_value=None):
            worker = OpenCodeWorker(
                argv_prefix=["nonexistent"],
                allowed_roots=(str(tmp_path),),
            )
            assert await worker.is_available() is False

    @pytest.mark.asyncio
    async def test_default_argv_prefix_on_windows(self, tmp_path: Path) -> None:
        with patch("os.name", "nt"):
            worker = OpenCodeWorker(
                allowed_roots=(str(tmp_path),),
            )
            assert worker._argv_prefix == ["npx.cmd", "-y", "opencode-ai", "run"]

    @pytest.mark.asyncio
    async def test_default_argv_prefix_on_unix(self, tmp_path: Path) -> None:
        with patch("os.name", "posix"):
            worker = OpenCodeWorker(
                allowed_roots=(str(tmp_path),),
            )
            assert worker._argv_prefix == ["npx", "-y", "opencode-ai", "run"]


class TestRegisterAvailableWorkers:
    @pytest.mark.asyncio
    async def test_registers_only_available_workers(self, tmp_path: Path) -> None:
        from all_tomorrow.registry import CapabilityRegistry

        registry = CapabilityRegistry()

        with patch("shutil.which", side_effect=lambda exe: "/usr/bin/antigravity" if exe == "antigravity" else None):
            registered = await register_available_workers(
                registry,
                antigravity_argv=["antigravity"],
                opencode_argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
            )

        assert registered == ["antigravity"]
        worker = registry._workers.get("antigravity")
        assert worker is not None
        assert worker.status == "available"
        assert "opencode" not in registry._workers

    @pytest.mark.asyncio
    async def test_registers_both_when_both_available(self, tmp_path: Path) -> None:
        from all_tomorrow.registry import CapabilityRegistry

        registry = CapabilityRegistry()

        with patch("shutil.which", return_value="/usr/bin/exe"):
            registered = await register_available_workers(
                registry,
                antigravity_argv=["antigravity"],
                opencode_argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
            )

        assert set(registered) == {"antigravity", "opencode"}
        assert "antigravity" in registry._workers
        assert "opencode" in registry._workers

    @pytest.mark.asyncio
    async def test_registers_none_when_neither_available(self, tmp_path: Path) -> None:
        from all_tomorrow.registry import CapabilityRegistry

        registry = CapabilityRegistry()

        with patch("shutil.which", return_value=None):
            registered = await register_available_workers(
                registry,
                antigravity_argv=["antigravity"],
                opencode_argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
            )

        assert registered == []
        assert not registry._workers


class TestErrorSanitization:
    def test_sanitize_error_redacts_home_path(self) -> None:
        from all_tomorrow.adapters.workers import _sanitize_error

        error = Exception(f"Error in {os.environ.get('HOME', '/home/user')}/project/file.py")
        sanitized = _sanitize_error(error)
        assert "<HOME>" in sanitized or "<USERPROFILE>" in sanitized

    def test_sanitize_error_redacts_env_secrets(self) -> None:
        from all_tomorrow.adapters.workers import _sanitize_error

        with patch.dict(os.environ, {"API_KEY": "secret123", "TOKEN": "token456"}):
            error = Exception("Failed with API_KEY=secret123 and TOKEN=token456")
            sanitized = _sanitize_error(error)
            assert "secret123" not in sanitized
            assert "token456" not in sanitized
            assert "<REDACTED>" in sanitized


import os