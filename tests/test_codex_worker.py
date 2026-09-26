"""04B — Codex Worker verification (offline, FakeProcess-backed)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from all_tomorrow.adapters.workers import CodexWorker, _allowlisted_env
from all_tomorrow.contracts import WorkerRequest, WorkerStatus


class FakeProcess:
    def __init__(self, returncode=0, stdout="", stderr="", should_timeout=False):
        self._rc = returncode
        self._out = stdout.encode()
        self._err = stderr.encode()
        self._timeout = should_timeout
        self.killed = False

    async def communicate(self, input=None):
        if self._timeout:
            raise asyncio.TimeoutError()
        await asyncio.sleep(0.001)
        return self._out, self._err

    async def wait(self):
        return self._rc

    def kill(self):
        self.killed = True

    @property
    def returncode(self):
        return self._rc


def _req(tmp_path: Path) -> WorkerRequest:
    return WorkerRequest(
        request_id="r1", trace_id="t1", project_id="p1",
        capabilities=frozenset({"coding"}),
        payload={"task": "do the thing", "cwd": str(tmp_path)},
    )


def _worker(tmp_path: Path, **kw) -> CodexWorker:
    return CodexWorker(argv_prefix=["codex"], allowed_roots=(str(tmp_path),), **kw)


async def test_jsonl_success_normalized(tmp_path: Path) -> None:
    stream = "\n".join([
        json.dumps({"type": "reasoning", "text": "thinking"}),
        json.dumps({"type": "usage", "input_tokens": 5, "output_tokens": 7}),
        json.dumps({"type": "task_complete", "text": "done: edited main.py"}),
    ])
    fake = FakeProcess(returncode=0, stdout=stream)
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        res = await _worker(tmp_path).execute(_req(tmp_path))
    assert res.status is WorkerStatus.SUCCESS
    assert res.payload["final_output"] == "done: edited main.py"
    assert res.payload["event_count"] == 3
    assert res.payload["usage"]["input_tokens"] == 5
    # raw stream not stored wholesale
    assert "reasoning" in res.payload["opaque_event_refs"]
    assert "thinking" not in json.dumps(res.payload)


def test_workspace_write_is_default_never_full_access(tmp_path: Path) -> None:
    w = _worker(tmp_path)
    argv = w.build_argv("prompt")
    assert "--sandbox" in argv
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert "danger-full-access" not in argv
    assert "exec" in argv and "--json" in argv


def test_danger_full_access_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _worker(tmp_path, sandbox_mode="danger-full-access")


async def test_timeout(tmp_path: Path) -> None:
    fake = FakeProcess(should_timeout=True)
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        res = await _worker(tmp_path, timeout_seconds=0.05).execute(_req(tmp_path))
    assert res.status is WorkerStatus.TIMEOUT
    assert fake.killed


async def test_nonzero_exit(tmp_path: Path) -> None:
    fake = FakeProcess(returncode=1, stderr="boom")
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        res = await _worker(tmp_path).execute(_req(tmp_path))
    assert res.status is WorkerStatus.FAILED


async def test_missing_executable(tmp_path: Path) -> None:
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=FileNotFoundError())):
        res = await _worker(tmp_path).execute(_req(tmp_path))
    assert res.status is WorkerStatus.EXECUTABLE_NOT_FOUND


async def test_invalid_jsonl(tmp_path: Path) -> None:
    fake = FakeProcess(returncode=0, stdout="not json at all\n{broken")
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        res = await _worker(tmp_path).execute(_req(tmp_path))
    assert res.status is WorkerStatus.INVALID_OUTPUT


async def test_oversize_output(tmp_path: Path) -> None:
    big = json.dumps({"type": "task_complete", "text": "x" * 2_000_000})
    fake = FakeProcess(returncode=0, stdout=big)
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        res = await _worker(tmp_path, output_limit_bytes=1024).execute(_req(tmp_path))
    assert res.status is WorkerStatus.OUTPUT_TOO_LARGE


async def test_traversal_blocked(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_root"
    outside.mkdir(exist_ok=True)
    req = WorkerRequest(
        request_id="r", trace_id="t", project_id="p",
        capabilities=frozenset({"coding"}),
        payload={"task": "x", "cwd": str(outside)},
    )
    res = await _worker(tmp_path).execute(req)
    assert res.status is WorkerStatus.TRAVERSAL_BLOCKED


def test_env_allowlist_drops_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-pass")
    monkeypatch.setenv("MY_FLAG", "ok")
    env = _allowlisted_env({}, frozenset({"OPENAI_API_KEY", "MY_FLAG"}))
    assert "OPENAI_API_KEY" not in env          # credential-looking var never forwarded
    assert env.get("MY_FLAG") == "ok"           # benign allow-listed var passes
    assert "sk-should-not-pass" not in json.dumps(env)


def test_capabilities_for_registry_selection(tmp_path: Path) -> None:
    w = _worker(tmp_path)
    assert w.worker_id == "codex"
    assert {"coding", "repo_edit", "analysis", "terminal"} <= w.capabilities
