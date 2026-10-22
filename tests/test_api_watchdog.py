import json
import logging
import subprocess

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from all_tomorrow.overseer import api_watchdog as watchdog
from all_tomorrow.api_logging import FailureLogMiddleware


def test_consecutive_failures_reset_and_persist(tmp_path):
    calls = []
    def check(ok, now):
        return watchdog.check_once(tmp_path, probe=lambda: ok, recover=calls.append,
                                   diagnostics=lambda: {"connections": 12}, now=now)
    assert check(False, 1) == "unhealthy"
    assert check(False, 2) == "unhealthy"
    assert check(True, 3) == "healthy"
    assert check(False, 4) == "unhealthy"
    assert check(False, 5) == "unhealthy"
    assert not calls
    assert check(False, 6) == "restarted"
    assert calls == ["AllTomorrow-DP7-api"]
    state = json.loads((tmp_path / "api-watchdog.json").read_text())
    assert state == {"failures": 0, "attempts": [6]}
    for name in ("api.log", "api-watchdog.jsonl"):
        lines = [json.loads(line) for line in (tmp_path / name).read_text().splitlines()]
        assert lines[-2]["diagnostics"] == {"connections": 12}
        assert lines[-1]["event"] == "restart_started"


@pytest.mark.parametrize("restart_fails", [False, True])
def test_hourly_limit_counts_attempts_and_latches(tmp_path, restart_fails):
    calls = []
    def recover(task):
        calls.append(task)
        if restart_fails:
            raise subprocess.TimeoutExpired("secret-command", 25)
    for tick in range(12):
        result = watchdog.check_once(tmp_path, probe=lambda: False, recover=recover,
                                     diagnostics=lambda: {}, now=tick * 60)
    assert result == "blocked" and len(calls) == 3
    reports = list((tmp_path / "reports").glob("*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["content"].startswith("[보고] 중앙 API")
    assert watchdog.check_once(tmp_path, probe=lambda: pytest.fail("latched"), now=10000) == "blocked"
    assert "secret-command" not in (tmp_path / "api.log").read_text()


def test_hour_window_expires_before_limit(tmp_path):
    (tmp_path / "api-watchdog.json").write_text(json.dumps({"failures": 2, "attempts": [0, 60, 120]}))
    calls = []
    assert watchdog.check_once(tmp_path, probe=lambda: False, recover=calls.append,
                               diagnostics=lambda: {}, now=3600) == "restarted"
    assert len(calls) == 1
    assert json.loads((tmp_path / "api-watchdog.json").read_text())["attempts"] == [60, 120, 3600]


def test_diagnostic_failure_does_not_prevent_recovery(tmp_path):
    (tmp_path / "api-watchdog.json").write_text('{"failures":2}')
    calls = []
    def diagnose():
        raise PermissionError("sensitive")
    assert watchdog.check_once(tmp_path, probe=lambda: False, recover=calls.append,
                               diagnostics=diagnose) == "restarted"
    assert len(calls) == 1
    assert "PermissionError" in (tmp_path / "api.log").read_text()
    assert "sensitive" not in (tmp_path / "api.log").read_text()


@pytest.mark.parametrize("status,body,expected", [(200, {"ok": True}, True), (200, {"ok": False}, False),
    (200, [], False), (200, "bad json", False), (503, {"ok": True}, False), (302, {}, False)])
def test_health_probe(monkeypatch, status, body, expected):
    real_client = httpx.Client
    def handler(request):
        assert request.url.path == "/healthz"
        assert request.url.host == "127.0.0.1"
        assert request.extensions["timeout"]["read"] == 3
        return httpx.Response(status, json=body) if body != "bad json" else httpx.Response(status, text=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False
        return real_client(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(watchdog.httpx, "Client", client)
    assert watchdog.healthy() is expected


def test_probe_timeout(monkeypatch):
    real_client = httpx.Client
    def handler(request):
        raise httpx.ReadTimeout("secret")
    monkeypatch.setattr(watchdog.httpx, "Client", lambda **kw: real_client(
        **kw, transport=httpx.MockTransport(handler)))
    assert watchdog.healthy() is False


def test_restart_is_scoped_and_bounded(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="")
    monkeypatch.setattr(watchdog.subprocess, "run", run)
    watchdog.restart("Custom-api")
    script = calls[0][0][-1]
    assert "Stop-ScheduledTask" in script and "Start-ScheduledTask" in script
    assert script.index("Stop-ScheduledTask") < script.index("Start-ScheduledTask")
    assert "Custom-api" in script and "stop timeout" in script
    assert calls[0][1]["timeout"] == 25 and calls[0][1]["check"]
    assert calls[0][1]["encoding"] == "utf-8"
    with pytest.raises(ValueError):
        watchdog.restart("api';Write-Output secret")
    assert len(calls) == 1


def test_failure_only_logging_hides_request_data(caplog):
    app = FastAPI()
    app.add_middleware(FailureLogMiddleware)
    @app.get("/ok")
    def ok():
        return {"ok": True}
    @app.get("/boom")
    def boom():
        raise ValueError("secret-body")
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.WARNING, logger="all_tomorrow.api"):
        assert client.get("/ok").status_code == 200
        assert not caplog.records
        assert client.get("/missing-secret?token=secret-token").status_code == 404
        assert client.get("/boom").status_code == 500
    messages = [r.message for r in caplog.records if r.name == "all_tomorrow.api"]
    assert len(messages) == 2
    assert "status=404" in messages[0] and "ValueError" in messages[1]
    assert "secret" not in " ".join(messages)


def test_uvicorn_and_asyncio_errors_reach_file(tmp_path):
    import sys
    # 새 프로세스로 실제 runtime과 같은 root logging/uvicorn 설정을 검증한다.
    script = '''
import asyncio, logging, sys, uvicorn
logging.basicConfig(filename=sys.argv[1], encoding="utf-8", level=logging.INFO)
uvicorn.Config(object(), log_config=None, access_log=False)
logging.getLogger("uvicorn.error").error("protocol-failure-proof")
async def probe():
    loop = asyncio.get_running_loop()
    loop.call_exception_handler({"message": "socket.accept() out of system resource",
                                 "exception": OSError(24, "accept-proof")})
asyncio.run(probe())
'''
    path = tmp_path / "api.log"
    subprocess.run([sys.executable, "-c", script, str(path)], check=True, capture_output=True, timeout=15)
    content = path.read_text(encoding="utf-8")
    assert "protocol-failure-proof" in content
    assert "socket.accept() out of system resource" in content
    assert "accept-proof" in content
