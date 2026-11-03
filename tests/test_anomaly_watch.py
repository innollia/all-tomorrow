import json
import subprocess

from all_tomorrow.console import servers
from all_tomorrow.overseer import anomaly_watch, metacog_session


def obs(target="api", kind="health_flapping", now=False):
    return {"target": target, "kind": kind, "title": f"{target} {kind}", "detail": "d", "facts": {}, "now": now}


def test_opens_after_streak_wakes_once_and_closes_after_quiet(tmp_path):
    woke, resolved = [], []
    def wake(base, incident):
        woke.append(incident.fingerprint)
        return "woken"
    run = lambda t, found: anomaly_watch.check(tmp_path, now=t, found=found, wake=wake,
                                                resolve=lambda b, s, only=None: resolved.append(only))
    for minute in range(anomaly_watch.STREAK - 1):
        assert run(minute, [obs(kind="unknown")]) == {}
    assert run(10, [obs(kind="unknown")]) == {"watch.api:unknown": "opened"}
    run(11, [obs(kind="unknown")])
    assert woke == ["watch.api:unknown"]                     # 열린 동안 다시 깨우지 않는다
    item = json.loads((tmp_path / "anomalies.json").read_text(encoding="utf-8"))["items"]["watch.api:unknown"]
    assert item["open"] and item["woke"] == "woken"
    for minute in range(anomaly_watch.RECOVER - 1):
        assert run(20 + minute, []) == {}
    assert run(40, []) == {"watch.api:unknown": "closed"} and resolved == ["watch.api:unknown"]


def test_windowed_signal_opens_at_once_and_busy_wake_retries(tmp_path):
    answers = iter(["busy", "woken"])
    calls = []
    def wake(base, incident):
        calls.append(incident.source)
        return next(answers)
    anomaly_watch.check(tmp_path, now=1, found=[obs(now=True)], wake=wake)
    anomaly_watch.check(tmp_path, now=2, found=[obs(now=True)], wake=wake)
    anomaly_watch.check(tmp_path, now=3, found=[obs(now=True)], wake=wake)
    assert calls == ["anomaly_watch", "anomaly_watch"]


def test_fingerprint_survives_api_resolve(tmp_path):
    metacog_session.wake(tmp_path, metacog_session.Incident("watch.api:health_flapping", "anomaly_watch", "t", "d"),
                         launch=lambda *a: None, running=lambda b: False)
    metacog_session.resolve(tmp_path, "api")                 # API가 살 때마다 api_watchdog가 부른다
    assert "watch.api:health_flapping" in metacog_session.load_state(tmp_path)["incidents"]


def test_detects_health_logs_unknown_and_memory(tmp_path):
    now = 1_800_000_000.0
    with (tmp_path / "api-watchdog.jsonl").open("w", encoding="utf-8") as file:
        file.write("first line is skipped as partial\n")
        for i in range(anomaly_watch.HEALTH_FAILS):
            file.write(json.dumps({"at": now - 60 * i, "event": "health_failed", "failures": 1}) + "\n")
        file.write(json.dumps({"at": now - 7200, "event": "health_failed"}) + "\n")
    import time
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 120))
    (tmp_path / "overseer.log").write_text(
        "x\n" + "".join(f"{stamp},1 WARNING 사용량 push 실패: TimeoutError\n" for _ in range(anomaly_watch.LOG_REPEATS)),
        encoding="utf-8")
    (tmp_path / "server-watch.json").write_text(json.dumps(
        {"servers": {"executor": {"status": "unknown", "detail": "Windows 조회 불가"}, "collect": {"status": "ok"}}}),
        encoding="utf-8")
    high = lambda: anomaly_watch.memory_pressure(
        probe=lambda: {"commit_ratio": 0.9, "commit_gb": 57, "commit_limit_gb": 63, "avail_mb": 600},
        counts=lambda: {"claude.exe": 45})
    kinds = {(o["target"], o["kind"]) for o in anomaly_watch.observations(tmp_path, now, memory_probe=high)}
    assert kinds == {("api", "health_flapping"), ("overseer", "log:사용량 push 실패: TimeoutError"),
                     ("executor", "unknown"), ("host", "memory_pressure")}
    calm = lambda: {"commit_ratio": 0.5, "commit_gb": 30, "commit_limit_gb": 63, "avail_mb": 8000}
    assert anomaly_watch.memory_pressure(probe=calm) is None


def test_windows_task_uses_com_before_powershell(monkeypatch):
    def no_powershell(*a, **k):
        raise AssertionError("PowerShell should not run")
    monkeypatch.setattr(subprocess, "run", no_powershell)
    monkeypatch.setattr(servers, "task_via_com", lambda name: {"state": "Running", "result": 0, "ran": True})
    assert servers.windows_observation(servers.Health(kind="windows_task", target="t"))[0] == "ok"


def test_tailscale_timeout_is_unknown_not_failed(monkeypatch):
    def slow(argv, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)
    monkeypatch.setattr(servers, "_run", slow)
    monkeypatch.setattr(servers, "_exe", lambda *a: "tailscale")
    assert servers.observe_tailscale()[0] == "unknown"


def test_http_timeout_is_unknown_refused_is_failed(monkeypatch):
    import httpx
    from all_tomorrow.overseer import server_watch
    service = type("S", (), {"health": servers.Health(kind="http", target="http://127.0.0.1:1/")})()
    for error, want in ((httpx.ReadTimeout("slow"), "unknown"), (httpx.ConnectError("refused"), "failed")):
        def get(self, url, error=error):
            raise error
        monkeypatch.setattr(httpx.Client, "get", get)
        assert server_watch.observe(service)[0] == want
