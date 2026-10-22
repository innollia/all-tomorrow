"""Work 실패 진단과 무변경 깨어남 회귀시험. 외부 모델은 호출하지 않는다."""
import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from all_tomorrow.adapters.workers import CodexWorker
from all_tomorrow.contracts import WorkerRequest, WorkerStatus
from all_tomorrow.overseer import loop, metacog, runtime
from all_tomorrow.overseer.redact import Redactor
from all_tomorrow.overseer.store import SessionStore
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore
from test_overseer_loop import project, make_work


SECRET = "hands-test-secret-value"


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setattr("all_tomorrow.overseer.environment.load_key_pool", lambda: None)
    monkeypatch.setattr(runtime, "load_key_pool", lambda: None)
    monkeypatch.setattr("all_tomorrow.overseer.reports.flush", lambda *a: 0)
    monkeypatch.setattr("all_tomorrow.overseer.redact.Redactor.from_files", lambda files: Redactor({SECRET}))
    monkeypatch.setattr("all_tomorrow.usage.collect_codex", lambda home: {"windows": []})


def worker_config(tmp_path, monkeypatch, workers):
    path = tmp_path / "workers.json"
    path.write_text(json.dumps({"workers": workers}), encoding="utf-8")
    monkeypatch.setenv("ALL_TOMORROW_WORKERS", str(path))


def cli(tmp_path, name, code):
    path = tmp_path / (name + ".py")
    path.write_text(code, encoding="utf-8")
    return [sys.executable, str(path)]


async def test_all_workers_fail_preserving_redacted_diagnostics_and_original(tmp_path, monkeypatch, caplog):
    root, base, registry = project(tmp_path)
    # Actual CLI subprocess: nonzero exit, partial edit, stderr containing a pool secret.
    codex = cli(tmp_path, "codex", "from pathlib import Path\nimport sys\n"
        f"Path('partial.txt').write_text('partial')\nprint('runner pipe failed {SECRET}', file=sys.stderr)\nsys.exit(7)")
    agy = cli(tmp_path, "agy", "from pathlib import Path\n"
        "assert not Path('partial.txt').exists()\n"
        "print('{\"status\":\"SUCCESS\",\"response\":\"not JSON\"}')")
    worker_config(tmp_path, monkeypatch, {"codex": {"argv": codex}, "antigravity": {"argv": agy}})
    monkeypatch.setattr("all_tomorrow.idea_factory.llm.chat", lambda *a, **kw: (f"no JSON {SECRET}", "fake"))
    caplog.set_level(logging.INFO, logger="all_tomorrow.overseer")
    store = InMemoryGoalWorkRunStore()
    await make_work(store, registry)
    assert await loop.execute_pending(store, base, registry=registry, redact=Redactor({SECRET})) == 1
    events = await store.list_events()
    rolled = next(e for e in events if e.type == "metacog.rolled_back")
    attempts = rolled.payload["attempts"]
    assert [a["worker"] for a in attempts] == ["codex", "antigravity", "free"]
    assert attempts[0]["exit_code"] == 7 and "runner pipe failed" in attempts[0]["stderr"]
    assert attempts[1]["exit_code"] == 0  # The CLI succeeded; parsing its edit plan failed.
    assert all(a["stage"] == "작업" and not a["timed_out"] for a in attempts)
    assert len([e for e in events if e.type == "metacog.execution_attempt"]) == 3
    assert "codex/작업" in rolled.payload["reason"] and "free/작업" in rolled.payload["report"]
    assert (root / "src/demo.py").read_text() == "answer = 1\n"
    artifact = Path(rolled.payload["artifact"])
    assert loop.tree(artifact / "candidate") == loop.tree(artifact / "before")
    saved = (artifact / "worker-attempts.json").read_text(encoding="utf-8")
    assert SECRET not in saved + json.dumps(rolled.payload) + caplog.text
    assert "REDACTED" in saved
    started = next(e for e in events if e.type == "metacog.run_started")
    assert started.payload["pid"] > 0 and started.payload["parent_pid"] > 0


@pytest.mark.parametrize("mode", ["no_change", "exception", "unavailable", "quota"])
async def test_fallback_after_unsuccessful_codex(tmp_path, monkeypatch, mode):
    from all_tomorrow import local_workers
    from all_tomorrow.contracts import WorkerResult
    root, base, _ = project(tmp_path)
    change = loop.ProjectChange(root, base / "change")
    change.prepare()
    worker_config(tmp_path, monkeypatch, {})

    class Adapter:
        capabilities = frozenset()

        async def is_available(self):
            return mode != "unavailable"

        async def execute(self, request):
            if mode == "exception":
                (change.candidate / "partial.txt").write_text("partial")
                raise OSError("launch failure")
            assert mode == "no_change"
            return WorkerResult("r", "t", WorkerStatus.SUCCESS, payload={"output": "완료"})

    monkeypatch.setattr(local_workers, "configured_adapters", lambda c: {"codex": Adapter()})
    if mode == "quota":
        monkeypatch.setattr("all_tomorrow.usage.collect_codex", lambda p: {"windows": [{"percent": 100}]})
    monkeypatch.setattr("all_tomorrow.idea_factory.llm.chat", lambda *a, **kw:
        ('{"edits":[{"file":"src/demo.py","content":"answer = 2\\n"}]}', "fake"))
    result = await loop.run_worker({"objective": "계산 수정", "project_id": "demo"}, change.candidate)
    assert result["worker"] == "free" and len(result["attempts"]) == 2
    assert result["attempts"][0]["status"] != "SUCCESS"
    assert not (change.candidate / "partial.txt").exists()
    assert (change.candidate / "src/demo.py").read_text() == "answer = 2\n"


async def test_cli_timeout_retains_exit_and_redacted_partial_stderr(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER_TOKEN", SECRET)
    argv = cli(tmp_path, "slow", f"import sys,time\nprint('waiting {SECRET}', file=sys.stderr, flush=True)\ntime.sleep(30)")
    adapter = CodexWorker(allowed_roots=(str(tmp_path),), argv=argv, timeout_seconds=0.5)
    result = await adapter.execute(WorkerRequest("r", "t", "demo", frozenset(), {"cwd": str(tmp_path), "task": "시험"}))
    assert result.status == WorkerStatus.TIMEOUT
    assert result.payload["timed_out"] and result.payload["exit_code"] is not None
    assert "waiting" in result.payload["stderr"] and SECRET not in result.payload["stderr"]


@pytest.mark.parametrize("stage", ["작업", "심사", "시험", "반영"])
async def test_stage_exception_has_redacted_event_and_rollback_summary(tmp_path, monkeypatch, stage):
    _, base, registry = project(tmp_path)
    store = InMemoryGoalWorkRunStore()
    await make_work(store, registry)

    def fail(*a, **kw):
        raise subprocess.CalledProcessError(23, "safe-command", stderr=f"failed {SECRET}")

    async def worker(task, candidate):
        if stage == "작업":
            fail()
        (candidate / "src/demo.py").write_text("answer = 2\n")
        return {"worker": "fake"}

    if stage == "반영":
        monkeypatch.setattr(loop.Promoter, "promote", fail)
    await loop.execute_pending(store, base, registry=registry, redact=Redactor({SECRET}), worker=worker,
        reviewer=fail if stage == "심사" else lambda *a: True,
        verifier=fail if stage == "시험" else lambda *a: True)
    rolled = next(e for e in await store.list_events() if e.type == "metacog.rolled_back")
    failure = rolled.payload["attempts"][-1]
    assert failure["stage"] == stage and failure["exit_code"] == 23
    assert SECRET not in json.dumps(rolled.payload) and stage in rolled.payload["report"]


def test_verifier_captures_nonzero_and_timeout(tmp_path, monkeypatch):
    diagnostics = []
    task = {"verify_argv": ["{python}", "-c", f"import sys; print('test failed {SECRET}', file=sys.stderr); sys.exit(9)"]}
    assert not loop.verify(task, tmp_path, diagnostics=diagnostics, redact=Redactor({SECRET}))
    assert diagnostics[-1]["exit_code"] == 9 and "test failed" in diagnostics[-1]["stderr"]
    assert SECRET not in json.dumps(diagnostics)

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("tests", 600)

    monkeypatch.setattr(subprocess, "run", timeout)
    assert not loop.verify(task, tmp_path, diagnostics=diagnostics)
    assert diagnostics[-1]["timed_out"] and diagnostics[-1]["stage"] == "시험"


def test_gateway_timeout_is_identified_and_redacted():
    import httpx
    item = loop.exception_diagnostic("free", "작업", httpx.ReadTimeout(f"gateway timeout {SECRET}"))
    assert item["timed_out"] and SECRET not in json.dumps(item)


async def test_observe_does_not_wake_itself_from_applied_marker(tmp_path):
    store = InMemoryGoalWorkRunStore()
    sessions = SessionStore(tmp_path / "sessions.sqlite")
    calls = []

    def reasoner(*a):
        calls.append(1)
        return '{"observations":[],"actions":[],"notes":""}'

    try:
        await loop.observe(store, sessions, tmp_path, registry={}, redact=lambda t: t, reasoner=reasoner, force=True)
        for _ in range(3):
            result = await loop.observe(store, sessions, tmp_path, registry={}, redact=lambda t: t, reasoner=reasoner)
            assert result["status"] == "skipped"
        assert calls == [1]
        await store.append_event(loop.event("metacog.rolled_back", payload={"reason": "새 실패"}))
        result = await loop.observe(store, sessions, tmp_path, registry={}, redact=lambda t: t, reasoner=reasoner)
        assert result["status"] == "done" and calls == [1, 1]
    finally:
        sessions.close()


def test_open_work_is_actionable_but_waiting_and_closed_work_are_not():
    snap = {"since": "2026-10-21", "changed_sessions": [], "new_cards": [], "oracle_questions": [],
            "system": {"own_log_errors": []}, "central": {"events": [], "work": []}}
    for status in ("PENDING", "RUNNING"):
        snap["central"]["work"] = [{"status": status}]
        assert not metacog.nothing_new(snap)
    for status in ("WAITING", "SUCCEEDED", "FAILED"):
        snap["central"]["work"] = [{"status": status}]
        assert metacog.nothing_new(snap)


async def test_runtime_scheduled_wake_never_forces_reasoner(tmp_path, monkeypatch):
    from all_tomorrow.overseer import schedule
    monkeypatch.setattr("all_tomorrow.usage.collect", lambda: {"providers": []})
    monkeypatch.setattr("all_tomorrow.usage.collector_token", lambda *a: None)
    monkeypatch.setattr(schedule, "idle_seconds", lambda p: 900)
    monkeypatch.setattr(schedule, "wake_delay", lambda *a: (60, "사용 가능"))
    seen = []

    async def observe(*a, **kw):
        seen.append(kw)

    async def with_store(callback):
        return await callback(object())

    async def stop(*a):
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime, "observe_once", observe)
    monkeypatch.setattr(runtime, "with_store", with_store)
    monkeypatch.setattr(asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await runtime.serve("overseer", tmp_path)
    assert len(seen) == 1 and seen[0].get("force", False) is False


def test_winget_antigravity_is_discovered_without_path(tmp_path, monkeypatch):
    import os
    from all_tomorrow import local_workers
    link = tmp_path / "Microsoft/WinGet/Links/agy.EXE"
    link.parent.mkdir(parents=True)
    link.write_text("exe")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(local_workers.shutil, "which", lambda *a: None)
    monkeypatch.setattr(os, "name", "nt")
    assert Path(local_workers.discover_executable("antigravity")) == link


def test_korean_prompt():
    assert "자연어 출력은 모두 한국어" in metacog.PROMPT


@pytest.mark.skipif(sys.platform != "win32", reason="Windows task registration")
def test_registration_uses_interactive_session_and_restarts_stopped_workers(tmp_path):
    # Execute the actual script with scheduler cmdlets replaced: never registers a real task.
    harness = tmp_path / "register.ps1"
    harness.write_text(r'''
param($Repo, $Python)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$script:tasks = @()
$script:starts = @()
function Test-Path { return $false } # Do not read the real key pool.
function New-ScheduledTaskPrincipal { param($UserId,$LogonType,$RunLevel); return $PSBoundParameters }
function New-ScheduledTaskSettingsSet {
    param([switch]$StartWhenAvailable,$MultipleInstances,$RestartCount,$RestartInterval,$ExecutionTimeLimit,
          [switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries)
    return $PSBoundParameters
}
function New-ScheduledTaskTrigger {
    param([switch]$AtStartup,[switch]$AtLogOn,$User,[switch]$Once,$At,$RepetitionInterval)
    return $PSBoundParameters
}
function New-ScheduledTaskAction { param($Execute,$Argument,$WorkingDirectory); return $PSBoundParameters }
function Register-ScheduledTask {
    param($TaskName,$Action,$Trigger,$Principal,$Settings,[switch]$Force)
    $script:tasks += @{name=$TaskName; principal=$Principal; triggers=@($Trigger);
        settings=$Settings; action=$Action}
}
function Start-ScheduledTask { param($TaskName); $script:starts += $TaskName }
foreach ($name in @('ALL_TOMORROW_DATABASE_URL','ALL_TOMORROW_ADMIN_USER','ALL_TOMORROW_ADMIN_PASSWORD','ALL_TOMORROW_SESSION_SECRET')) {
    [Environment]::SetEnvironmentVariable($name,'fake-test-value','Process')
}
$source = Get-Content -LiteralPath (Join-Path $Repo 'scripts/dp7-up.ps1') -Encoding UTF8 -Raw
$source = $source -replace '(?m)^#Requires -RunAsAdministrator\r?\n', ''
& ([scriptblock]::Create($source)) -Repo $Repo -Python $Python -TaskPrefix 'Fake-DP7'
@{tasks=$script:tasks; starts=$script:starts} | ConvertTo-Json -Depth 8 -Compress
''', encoding="utf-8-sig")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(harness),
        "-Repo", str(Path.cwd()), "-Python", sys.executable], capture_output=True, timeout=30,
        encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    tasks = {t["name"].removeprefix("Fake-DP7-"): t for t in data["tasks"]}
    assert len(data["starts"]) == len(tasks) == 6
    for component in ("executor", "overseer"):
        task = tasks[component]
        assert task["principal"]["LogonType"] == "Interactive"
        assert task["principal"]["RunLevel"] == "Limited"
        assert any(t.get("RepetitionInterval", {}).get("TotalSeconds") == 60 for t in task["triggers"])
        assert task["settings"]["ExecutionTimeLimit"]["TotalSeconds"] == 0
        assert task["settings"]["MultipleInstances"] == "IgnoreNew"
        assert task["settings"]["RestartCount"] == 99
        assert task["action"]["Argument"].endswith("runtime " + component)
    assert tasks["api"]["principal"]["LogonType"] == tasks["collect"]["principal"]["LogonType"] == "S4U"
    watchdog = tasks["api-watchdog"]
    assert watchdog["principal"]["LogonType"] == "S4U"
    assert watchdog["settings"]["MultipleInstances"] == "IgnoreNew"
    assert watchdog["settings"]["ExecutionTimeLimit"]["TotalSeconds"] == 60
    assert "RestartCount" not in watchdog["settings"]
    assert any(t.get("RepetitionInterval", {}).get("TotalSeconds") == 60 for t in watchdog["triggers"])
    assert watchdog["action"]["Argument"] == '-m all_tomorrow.overseer.runtime api-watchdog --api-task "Fake-DP7-api"'


async def test_restart_keeps_previous_worker_failure_diagnostic(tmp_path):
    _, base, registry = project(tmp_path)
    store = InMemoryGoalWorkRunStore()
    await make_work(store, registry)
    created = next(e for e in await store.list_events() if e.type == "researcher.create_work")
    work = await store.get_work(created.work_id)
    from all_tomorrow.domain.state import WorkStatus
    await store.transition_work_status(work.work_id, WorkStatus.RUNNING, work.revision, loop.event("started"))
    artifact = base / "changes" / str(work.work_id)
    artifact.mkdir(parents=True)
    (artifact / "worker-attempts.json").write_text(json.dumps({"attempts": [
        loop.diagnostic("codex", "작업", timed_out=True, error="runner pipe timed out")]}), encoding="utf-8")
    await loop.execute_pending(store, base, registry=registry, redact=lambda t: t)
    rolled = next(e for e in await store.list_events() if e.type == "metacog.rolled_back")
    assert rolled.payload["attempts"][0]["timed_out"]
    assert "runner pipe timed out" in rolled.payload["report"]
