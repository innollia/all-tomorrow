from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from all_tomorrow.adapters.workers import CodexWorker, KiroWorker, OpenCodeWorker, AntigravityWorker
from all_tomorrow.contracts import ExecutionContext, NodeStatus, RequestEnvelope, WorkerRequest, WorkerStatus
from all_tomorrow.local_workers import build_worker_service, configured_adapters, load_config
from all_tomorrow.pipeline.nodes import WorkerRunNode


def request(cwd: Path) -> WorkerRequest:
    return WorkerRequest("req-local", "trace-local", "project-local", frozenset({"coding"}),
                         {"cwd": str(cwd), "task": "write proof.txt"})


def fixture_cli(tmp_path: Path, code: str) -> list[str]:
    script = tmp_path / "cli.py"
    script.write_text(code, encoding="utf-8")
    return [sys.executable, str(script)]


SUCCESS = {
    "codex": [
        {"type": "thread.started", "thread_id": "thread-proof"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "proof.txt"}},
        {"type": "turn.completed", "usage": {"output_tokens": 1}},
    ],
    "opencode": [
        {"type": "text", "part": {"text": "proof.txt"}},
        {"type": "step_finish", "sessionID": "session-proof", "part": {"reason": "stop"}},
    ],
    "antigravity": [{"status": "SUCCESS", "response": "proof.txt", "conversation_id": "agy-proof"}],
}


@pytest.mark.parametrize("worker_id", ["codex", "kiro", "opencode", "antigravity"])
async def test_configured_service_executes_through_pipeline(worker_id: str, tmp_path: Path) -> None:
    output = "proof.txt" if worker_id == "kiro" else "\n".join(map(json.dumps, SUCCESS[worker_id]))
    argv = fixture_cli(tmp_path, f"""
import sys
from pathlib import Path
assert 'write proof.txt' in sys.argv[-1]
assert 'req-local' in sys.argv[-1]
assert 'trace-local' in sys.argv[-1]
Path('proof.txt').write_text('actual child output')
print({output!r})
""")
    config = {"allowed_roots": [str(tmp_path)], "workers": {worker_id: {"argv": argv}}}
    service = await build_worker_service(config)
    context = ExecutionContext(
        request=RequestEnvelope(message="write proof.txt", source="test", request_id="req-local"),
        user_ref="owner", trace_id="trace-local", project_ref="project-local")
    result = await WorkerRunNode(service).run(context, {}, {"worker_id": worker_id, "cwd": str(tmp_path)})
    assert result.status == NodeStatus.SUCCESS
    assert (tmp_path / "proof.txt").read_text() == "actual child output"
    assert "write proof.txt" not in json.dumps(result.events)


@pytest.mark.parametrize("adapter,output,status", [
    (CodexWorker, '{"type":"turn.started"}\n', WorkerStatus.INVALID_OUTPUT),
    (CodexWorker, '{"type":"turn.failed","error":{"message":"no quota"}}', WorkerStatus.FAILED),
    (CodexWorker, '{"type":"turn.completed"}', WorkerStatus.INVALID_OUTPUT),
    (OpenCodeWorker, '{"type":"error","error":{"name":"AuthError"}}', WorkerStatus.FAILED),
    (OpenCodeWorker, '{"type":"text","part":{"text":"partial"}}', WorkerStatus.INVALID_OUTPUT),
    (OpenCodeWorker, '{"type":"step_start"}\nnot json', WorkerStatus.INVALID_OUTPUT),
    (AntigravityWorker, '{"status":"FAILED","response":"partial"}', WorkerStatus.FAILED),
    (AntigravityWorker, '{"status":"SUCCESS","response":""}', WorkerStatus.INVALID_OUTPUT),
])
async def test_exit_zero_does_not_mask_protocol_failure(adapter, output, status, tmp_path):
    argv = fixture_cli(tmp_path, f"print({output!r})")
    key = "argv_prefix" if adapter is OpenCodeWorker else "argv"
    worker = adapter(allowed_roots=(str(tmp_path),), **{key: argv})
    assert (await worker.execute(request(tmp_path))).status == status


async def test_auth_failure_preserves_actionable_diagnostic(tmp_path):
    argv = fixture_cli(tmp_path, "import sys; print('Not logged in. Run kiro-cli login', file=sys.stderr); sys.exit(1)")
    worker = KiroWorker(argv=argv, allowed_roots=(str(tmp_path),))
    result = await worker.execute(request(tmp_path))
    assert result.status == WorkerStatus.FAILED
    assert "kiro-cli login" in result.error


async def test_environment_and_explicit_credential_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTRAL_SECRET", "central-canary")
    argv = fixture_cli(tmp_path, """
import os,sys
assert 'CENTRAL_SECRET' not in os.environ
print(os.environ['PROVIDER_TOKEN'], file=sys.stderr)
sys.exit(1)
""")
    worker = CodexWorker(argv=argv, allowed_roots=(str(tmp_path),), env={"PROVIDER_TOKEN": "provider-canary"})
    result = await worker.execute(request(tmp_path))
    assert result.status == WorkerStatus.FAILED
    assert "provider-canary" not in result.error
    assert "<REDACTED>" in result.error


async def test_output_limit_terminates_a_running_child(tmp_path):
    argv = fixture_cli(tmp_path, "import sys,time; print('x'*100000, flush=True); time.sleep(30)")
    worker = CodexWorker(argv=argv, allowed_roots=(str(tmp_path),), output_limit_bytes=1000, timeout_seconds=10)
    result = await worker.execute(request(tmp_path))
    assert result.status == WorkerStatus.OUTPUT_TOO_LARGE
    assert result.duration_ms < 10000


async def test_timeout_kills_descendants(tmp_path):
    child = "import time; from pathlib import Path; time.sleep(3); Path('orphan.txt').write_text('bad')"
    argv = fixture_cli(tmp_path, f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)")
    worker = CodexWorker(argv=argv, allowed_roots=(str(tmp_path),), timeout_seconds=1)
    result = await worker.execute(request(tmp_path))
    assert result.status == WorkerStatus.TIMEOUT
    await asyncio.sleep(3)
    assert not (tmp_path / "orphan.txt").exists()


async def test_missing_directory_is_rejected_before_spawn(tmp_path):
    result = await CodexWorker(allowed_roots=(str(tmp_path),)).execute(request(tmp_path / "missing"))
    assert result.status == WorkerStatus.TRAVERSAL_BLOCKED


def test_config_rejects_embedded_credentials(tmp_path):
    config = {"allowed_roots": [str(tmp_path)], "workers": {"codex": {"options": {"env": {"TOKEN": "secret"}}}}}
    with pytest.raises(ValueError, match="env_names"):
        configured_adapters(config)


def test_config_requires_absolute_existing_roots(tmp_path):
    path = tmp_path / "workers.json"
    path.write_text(json.dumps({"allowed_roots": ["."], "workers": {"codex": {}}}))
    with pytest.raises(ValueError, match="absolute"):
        load_config(path)


def test_codex_does_not_fall_back_to_unrestricted_permissions(tmp_path):
    argv = CodexWorker(allowed_roots=(str(tmp_path),)).build_argv("task")
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert "--ephemeral" in argv
    assert "danger-full-access" not in argv
    if os.name == "nt":
        assert 'windows.sandbox="unelevated"' in argv


def test_command_emits_utf8_json_on_windows_too(tmp_path):
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "작업 완료"}},
        {"type": "turn.completed"},
    ]
    output = "\n".join(map(json.dumps, events))
    argv = fixture_cli(tmp_path, f"print({output!r})")
    config = tmp_path / "workers.json"
    config.write_text(json.dumps({"allowed_roots": [str(tmp_path)],
                                  "workers": {"codex": {"argv": argv}}}), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "all_tomorrow.local_workers", "--config", str(config),
                             "run", "codex", "--cwd", str(tmp_path), "--task", "hello"],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.decode("utf-8"))["payload"]["output"] == "작업 완료"
