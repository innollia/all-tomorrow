from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from all_tomorrow.adapters.workers import (
    AntigravityWorker,
    OpenCodeWorker,
    _build_worker_prompt,
    _check_executable_available,
    _sanitize_error,
    register_available_workers,
)
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

        mock_exec = AsyncMock(return_value=fake_proc)
        with patch("asyncio.create_subprocess_exec", new=mock_exec):
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
        assert fake_proc.communicate_called is True

        # Verify command construction
        mock_exec.assert_called_once()
        called_args = mock_exec.call_args[0]
        assert called_args[0] == "antigravity"
        assert "--mode" in called_args
        assert called_args[called_args.index("--mode") + 1] == "accept-edits"
        assert "--effort" in called_args
        assert called_args[called_args.index("--effort") + 1] == "high"
        assert "--output-format" in called_args
        assert called_args[called_args.index("--output-format") + 1] == "json"
        assert "--print" in called_args
        prompt = called_args[called_args.index("--print") + 1]
        assert request.request_id in prompt
        assert request.trace_id in prompt
        assert "--json" not in called_args

    @pytest.mark.asyncio
    async def test_real_antigravity_envelope_parsed(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        envelope = {
            "conversation_id": "conv-42",
            "status": "SUCCESS",
            "response": "Refactored module successfully.",
            "duration_seconds": 2.1,
            "usage": {"total_tokens": 500},
        }
        fake_proc = FakeProcess(returncode=0, stdout=json.dumps(envelope))

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.SUCCESS
        assert result.payload is not None
        assert result.payload["conversation_id"] == "conv-42"
        assert result.payload["response"] == "Refactored module successfully."
        assert result.payload["status"] == "SUCCESS"

    @pytest.mark.asyncio
    async def test_command_construction_options(self, tmp_path: Path) -> None:
        worker = AntigravityWorker(
            argv=["agy.exe"],
            allowed_roots=(str(tmp_path),),
            mode="plan",
            dangerously_skip_permissions=True,
            effort="low",
            model="gemini-3.8-flash-high",
            output_format="json",
        )
        cmd = worker.build_argv("do task")
        assert cmd == [
            "agy.exe",
            "--mode",
            "plan",
            "--dangerously-skip-permissions",
            "--effort",
            "low",
            "--model",
            "gemini-3.8-flash-high",
            "--output-format",
            "json",
            "--print",
            "do task",
        ]

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
    async def test_text_output_format_mode(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(returncode=0, stdout="Plain text result.")

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
                output_format="text",
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.SUCCESS
        assert result.payload == {
            "output": "Plain text result.",
            "text": "Plain text result.",
            "response": "Plain text result.",
        }

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
                argv=["nonexistent_executable_12345"],
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

        mock_exec = AsyncMock(return_value=fake_proc)
        with patch("asyncio.create_subprocess_exec", new=mock_exec):
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
        assert fake_proc.communicate_called is True

        # Verify command construction: format json present, no fake model/agent defaults
        mock_exec.assert_called_once()
        called_args = mock_exec.call_args[0]
        assert called_args[0] == "opencode"
        assert "--format" in called_args
        assert called_args[called_args.index("--format") + 1] == "json"
        assert "--model" not in called_args
        assert "--agent" not in called_args
        # Prompt is positional argument at the end
        prompt = called_args[-1]
        assert request.request_id in prompt

    @pytest.mark.asyncio
    async def test_ndjson_events_parsed(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        event1 = json.dumps({"event": "step_start", "step": 1})
        event2 = json.dumps({"event": "step_finish", "step": 1, "output": "ok"})
        ndjson_stdout = f"{event1}\n{event2}\n"
        fake_proc = FakeProcess(returncode=0, stdout=ndjson_stdout)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = OpenCodeWorker(
                argv_prefix=["opencode"],
                allowed_roots=(str(tmp_path),),
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.SUCCESS
        assert result.payload is not None
        assert len(result.payload["events"]) == 2
        assert result.payload["events"][0]["event"] == "step_start"
        assert result.payload["events"][1]["event"] == "step_finish"

    @pytest.mark.asyncio
    async def test_command_construction_options(self, tmp_path: Path) -> None:
        worker = OpenCodeWorker(
            argv_prefix=["npx", "-y", "opencode-ai", "run"],
            allowed_roots=(str(tmp_path),),
            model="anthropic/claude-3-5-sonnet",
            agent="programmer",
            auto=True,
            format="json",
        )
        cmd = worker.build_argv("write tests")
        assert cmd == [
            "npx",
            "-y",
            "opencode-ai",
            "run",
            "--format",
            "json",
            "--model",
            "anthropic/claude-3-5-sonnet",
            "--agent",
            "programmer",
            "--auto",
            "write tests",
        ]

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


class TestProcessRunnerRobustness:
    @pytest.mark.asyncio
    async def test_executable_not_found_maps_to_status(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("binary not found")):
            worker = AntigravityWorker(
                argv=["nonexistent_tool"],
                allowed_roots=(str(tmp_path),),
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.EXECUTABLE_NOT_FOUND
        assert result.error is not None
        assert "Executable not found" in result.error
        assert "nonexistent_tool" in result.error

    @pytest.mark.asyncio
    async def test_combined_output_limit_includes_stderr(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # stdout is small (100B), but stderr is large (2MiB)
        fake_proc = FakeProcess(
            returncode=0,
            stdout="small output",
            stderr="e" * (2 * 1024 * 1024),
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            worker = AntigravityWorker(
                argv=["antigravity"],
                allowed_roots=(str(tmp_path),),
                output_limit_bytes=1024 * 1024,
            )
            request = make_worker_request(payload={"cwd": str(project_dir)})
            result = await worker.execute(request)

        assert result.status is WorkerStatus.OUTPUT_TOO_LARGE
        assert result.error is not None
        assert "exceeds" in result.error

    @pytest.mark.asyncio
    async def test_stderr_secret_redacted_on_failure(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        fake_proc = FakeProcess(
            returncode=1,
            stderr="Auth failed with TOKEN=super_secret_token_12345 in response",
        )

        with patch.dict(os.environ, {"TOKEN": "super_secret_token_12345"}):
            with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
                worker = OpenCodeWorker(
                    argv_prefix=["opencode"],
                    allowed_roots=(str(tmp_path),),
                )
                request = make_worker_request(payload={"cwd": str(project_dir)})
                result = await worker.execute(request)

        assert result.status is WorkerStatus.FAILED
        assert result.error is not None
        assert "super_secret_token_12345" not in result.error
        assert "<REDACTED>" in result.error

    def test_prompt_preserves_all_contract_fields(self) -> None:
        request = WorkerRequest(
            request_id="req-999",
            trace_id="trace-888",
            project_id="proj-777",
            capabilities=frozenset({"coding", "analysis"}),
            payload={
                "cwd": "/workspace",
                "task": "Implement feature X",
                "constraints": ["no external dependencies", "must pass type check"],
                "acceptance_criteria": ["100% unit test coverage"],
                "expected_result_format": "JSON summary with diff",
            },
        )
        prompt = _build_worker_prompt(request)
        assert "req-999" in prompt
        assert "trace-888" in prompt
        assert "proj-777" in prompt
        assert "coding" in prompt
        assert "analysis" in prompt
        assert "Implement feature X" in prompt
        assert "no external dependencies" in prompt
        assert "must pass type check" in prompt
        assert "100% unit test coverage" in prompt
        assert "JSON summary with diff" in prompt


class TestErrorSanitization:
    def test_sanitize_error_redacts_home_path(self) -> None:
        with patch.dict(os.environ, {"HOME": "/custom/test/home"}):
            error = Exception("Error in /custom/test/home/project/file.py")
            sanitized = _sanitize_error(error)
            assert "<HOME>" in sanitized
            assert "/custom/test/home" not in sanitized

    def test_sanitize_error_redacts_userprofile(self) -> None:
        with patch.dict(os.environ, {"USERPROFILE": "C:\\Users\\TestProfile"}):
            error = Exception("Error in C:\\Users\\TestProfile\\file.py")
            sanitized = _sanitize_error(error)
            assert "<USERPROFILE>" in sanitized
            assert "C:\\Users\\TestProfile" not in sanitized

    def test_sanitize_error_when_home_and_profile_unset_does_not_corrupt(self) -> None:
        env = dict(os.environ)
        env.pop("HOME", None)
        env.pop("USERPROFILE", None)
        with patch.dict(os.environ, env, clear=True):
            error = Exception("Normal error message without empty string replacement")
            sanitized = _sanitize_error(error)
            assert sanitized == "Normal error message without empty string replacement"
            assert "<HOME>" not in sanitized
            assert "<USERPROFILE>" not in sanitized

    def test_sanitize_error_redacts_env_secrets(self) -> None:
        with patch.dict(os.environ, {"API_KEY": "secret123", "TOKEN": "token456"}):
            error = Exception("Failed with API_KEY=secret123 and TOKEN=token456")
            sanitized = _sanitize_error(error)
            assert "secret123" not in sanitized
            assert "token456" not in sanitized
            assert "<REDACTED>" in sanitized


class TestWindowsCommandNames:
    def test_check_executable_available_finds_pathext(self) -> None:
        with patch("os.name", "nt"), patch.dict(os.environ, {"PATHEXT": ".COM;.EXE;.BAT;.CMD"}):
            with patch("shutil.which", side_effect=lambda name: "C:\\bin\\agy.exe" if name in ("agy.exe", "agy.EXE") else None):
                assert _check_executable_available(["agy"]) is True
                assert _check_executable_available(["agy.exe"]) is True

    def test_check_executable_available_returns_false_when_missing(self) -> None:
        with patch("shutil.which", return_value=None):
            assert _check_executable_available(["completely_missing_bin"]) is False


class TestRegisterAvailableWorkers:
    @pytest.mark.asyncio
    async def test_registers_only_available_workers(self, tmp_path: Path) -> None:
        from all_tomorrow.registry import CapabilityRegistry

        registry = CapabilityRegistry()

        with patch("shutil.which", side_effect=lambda exe: "/usr/bin/antigravity" if "antigravity" in exe else None):
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


class TestRealCliSmoke:
    """Minimal harmless smoke tests querying CLI help text if installed on the host."""

    def test_antigravity_cli_help_smoke(self) -> None:
        exe = shutil.which("agy.exe") or shutil.which("agy")
        if not exe:
            pytest.skip("Antigravity CLI (agy/agy.exe) not found on PATH")

        import subprocess
        result = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0
        assert "--print" in result.stdout or "--print" in result.stderr
        assert "--output-format" in result.stdout or "--output-format" in result.stderr

    def test_opencode_cli_help_smoke(self) -> None:
        # A Windows PATH entry is visible in WSL, but .cmd files are not POSIX executables.
        npx = (shutil.which("npx.cmd") or shutil.which("npx")) if os.name == "nt" else shutil.which("npx")
        if not npx:
            pytest.skip("npx/npx.cmd not found on PATH")
        if os.name != "nt" and npx.startswith("/mnt/"):
            pytest.skip("Only a Windows-mounted npx is available to this Linux test process")

        import subprocess
        result = subprocess.run(
            [npx, "-y", "opencode-ai", "run", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "opencode run" in combined
        assert "--format" in combined
