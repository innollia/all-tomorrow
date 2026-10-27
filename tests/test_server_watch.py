import json

import pytest
from pydantic import ValidationError

from all_tomorrow.console import servers
from all_tomorrow.overseer import server_watch as watch


def registry():
    return servers.load_registry()


def only(*ids):
    r = registry()
    r.services = [s for s in r.services if s.id in ids]
    for s in r.services:
        s.host_id = watch.local_host()
    return r


def test_registry_start_methods():
    by = {s.id: s for s in registry().services}
    desk, tail, docker = by["quote-vn-desk"], by["tailscale"], by["docker-desktop"]
    assert desk.autostart == "boot" and desk.start.kind == "command" and desk.health.target.endswith(":8765/")
    assert desk.start.command[0] == "{python}" and "--no-open" in desk.start.command
    assert tail.autostart == "logon" and tail.health.kind == "tailscale" and tail.start.task == "AllTomorrow-DP7-tailscale-ipn"
    assert docker.autostart == "manual" and docker.health.kind == "docker"
    assert by["api"].autostart == "boot" and by["api-watchdog"].autostart is None


def test_autostart_needs_start_and_health():
    d = registry().model_dump()
    svc = next(s for s in d["services"] if s["id"] == "quote-vn-desk")
    svc["start"] = None
    with pytest.raises(ValidationError):
        servers.Registry.model_validate(d)
    svc["start"] = {"kind": "task"}
    with pytest.raises(ValidationError):
        servers.Registry.model_validate(d)


def run_sweep(tmp_path, statuses, now, started, **kw):
    return watch.sweep(tmp_path, registry=only("quote-vn-desk"), probe=lambda s: statuses(), now=now,
                       starter=lambda s: started.append(s.id), logged_on=lambda: True, **kw)


def test_dead_server_is_started_then_recovers(tmp_path):
    started = []
    assert run_sweep(tmp_path, lambda: ("failed", "HTTP 응답 없음"), 1000, started) == {"quote-vn-desk": "started"}
    assert started == ["quote-vn-desk"]
    # 5분 간격 전에는 아무것도 하지 않는다.
    assert run_sweep(tmp_path, lambda: ("failed", "x"), 1100, started) is None
    assert run_sweep(tmp_path, lambda: ("ok", "HTTP 200"), 1300, started) == {"quote-vn-desk": "healthy"}
    state = json.loads((tmp_path / "server-watch.json").read_text(encoding="utf-8"))
    assert state["servers"]["quote-vn-desk"]["starts"] == 0


def test_stops_after_three_failed_starts_and_reports_once(tmp_path):
    started, queued = [], []
    for tick in range(8):
        run_sweep(tmp_path, lambda: ("failed", "HTTP 응답 없음"), 1000 + tick * 300, started,
                  enqueue=lambda base, rid, text: queued.append((rid, text)))
    assert len(started) == 3
    assert len(queued) == 1 and "quote-vn-desk" in queued[0][1] and "tools/quote_vn_desk/server.py" in queued[0][1]
    assert queued[0][0].startswith("server-watch-quote-vn-desk-")
    # 살아나면 다시 감시한다.
    run_sweep(tmp_path, lambda: ("ok", "HTTP 200"), 9000, started)
    assert run_sweep(tmp_path, lambda: ("failed", "x"), 9300, started) == {"quote-vn-desk": "started"}


def test_start_failure_counts_and_unknown_is_left_alone(tmp_path):
    def boom(service):
        raise OSError("secret-path")
    r = watch.sweep(tmp_path, registry=only("quote-vn-desk"), probe=lambda s: ("failed", "x"), starter=boom,
                    logged_on=lambda: True, now=1000)
    assert r == {"quote-vn-desk": "start_failed"}
    assert "secret-path" not in (tmp_path / "server-watch.jsonl").read_text(encoding="utf-8")
    started = []
    assert run_sweep(tmp_path, lambda: ("unknown", "?"), 2000, started) == {"quote-vn-desk": "unknown"} and not started


def test_logon_server_waits_for_login_and_manual_is_observed_only(tmp_path):
    started = []
    r = watch.sweep(tmp_path, registry=only("tailscale", "docker-desktop"), probe=lambda s: ("failed", "BackendState=NoState"),
                    starter=lambda s: started.append(s.id), logged_on=lambda: False, now=1000)
    assert r == {"tailscale": "waiting_logon"} and not started
    r = watch.sweep(tmp_path, registry=only("tailscale", "docker-desktop"), probe=lambda s: ("failed", "BackendState=NoState"),
                    starter=lambda s: started.append(s.id), logged_on=lambda: True, now=2000)
    assert r == {"tailscale": "started"} and started == ["tailscale"]


def test_api_is_left_to_api_watchdog(tmp_path):
    r = watch.sweep(tmp_path, registry=only("api"), probe=lambda s: pytest.fail("api"), now=1000)
    assert r == {}


def test_boot_report_after_ten_minutes_once(tmp_path):
    reg = only("quote-vn-desk", "docker-desktop", "tailscale")
    queued = []
    def probe(s):
        return {"quote-vn-desk": ("failed", "HTTP 응답 없음"), "docker-desktop": ("failed", "Docker 엔진 응답 없음"),
                "tailscale": ("ok", "BackendState=Running")}[s.id]
    def call(now, uptime):
        return watch.boot_report(tmp_path, registry=reg, probe=probe, now=now, uptime=uptime,
                                 enqueue=lambda b, rid, text: queued.append((rid, text)))
    assert call(10_000, 70) == "waiting"           # 첫 실행, 부팅 1분 뒤
    for minute in range(1, 9):
        assert call(10_000 + 60 * minute, 70 + 60 * minute) == "waiting"
    assert call(10_000 + 540 + 60, 670) == "written"
    assert call(10_000 + 660, 730) == "done"
    text = (tmp_path / "boot-report.md").read_text(encoding="utf-8")
    assert "요약: 살아남 1 / 죽음 1 (인용된 사랑 작업판)" in text and "Docker Desktop" in text
    assert "관찰만 하는 서버" in text
    assert len(queued) == 1 and queued[0][0].startswith("boot-report-") and "인용된 사랑 작업판" in queued[0][1]
    assert "Docker" not in queued[0][1]  # 수동 서버는 보고하지 않는다
    assert watch.boot_summary(tmp_path).endswith("살아남 1 / 죽음 1 (인용된 사랑 작업판)")


def test_boot_report_all_alive_enqueues_nothing_and_gap_means_new_boot(tmp_path):
    reg = only("quote-vn-desk")
    queued = []
    def call(now, uptime):
        return watch.boot_report(tmp_path, registry=reg, probe=lambda s: ("ok", "HTTP 200"), now=now, uptime=uptime,
                                 enqueue=lambda *a: queued.append(a))
    assert call(100_000, 100_000) == "done"            # 이미 오래 켜져 있던 첫 실행은 보고하지 않는다
    assert call(100_060, 100_060) == "done"
    assert call(200_000, 100_000) == "waiting"         # 하루 넘게 안 돌았다 = 재부팅(tick은 그대로)
    for minute in range(1, 10):
        assert call(200_000 + 60 * minute, 100_000 + 60 * minute) == "waiting"
    assert call(200_600, 100_600) == "written" and not queued
    assert "죽음 0" in (tmp_path / "boot-report.md").read_text(encoding="utf-8")


def test_observe_tailscale_states(monkeypatch):
    class R:
        def __init__(self, out): self.stdout = out
    for out, want in ((json.dumps({"BackendState": "Running"}), "ok"), (json.dumps({"BackendState": "NoState"}), "failed"),
                      ("not json", "failed")):
        monkeypatch.setattr(servers, "_run", lambda argv, timeout, out=out: R(out))
        monkeypatch.setattr(servers, "_exe", lambda *a: "tailscale")
        assert servers.observe_tailscale()[0] == want
