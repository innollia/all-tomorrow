import json

from all_tomorrow.console import servers
from all_tomorrow.overseer import api_watchdog, metacog_session as ms, server_watch as watch
from all_tomorrow.overseer.redact import Redactor

SECRET = "sk-" + "Z9y8X7w6V5u4T3s2R1q0P9o8"


def incident(fp="quote-vn-desk:FileNotFoundError"):
    return ms.Incident(fingerprint=fp, source="server_watch", title="서버 작업판 자동 시작 3번 실패", detail="HTTP 응답 없음")


def test_same_fingerprint_wakes_once_until_state_changes(tmp_path):
    launched = []
    launch = lambda base, fp: launched.append(fp)
    idle = lambda base: False
    assert ms.wake(tmp_path, incident(), launch=launch, running=idle, now=1000) == "woken"
    for t in range(1, 30):                       # 매 점검마다 불러도 한 번만
        assert ms.wake(tmp_path, incident(), launch=launch, running=idle, now=1000 + t * 300) == "duplicate"
    assert launched == ["quote-vn-desk:FileNotFoundError"]
    assert ms.resolve(tmp_path, "quote-vn-desk") == ["quote-vn-desk:FileNotFoundError"]
    assert ms.resolve(tmp_path, "quote-vn-desk") == []
    assert ms.wake(tmp_path, incident(), launch=launch, running=idle, now=20000) == "woken"
    assert len(launched) == 2


def test_busy_paused_and_daily_budget(tmp_path, monkeypatch):
    launched = []
    launch = lambda base, fp: launched.append(fp)
    assert ms.wake(tmp_path, incident(), launch=launch, running=lambda b: True, now=1) == "busy"
    assert ms.wake(tmp_path, incident(), launch=launch, running=lambda b: False, now=2) == "woken"
    (tmp_path / ms.PAUSE).write_text("")
    assert ms.wake(tmp_path, incident("api:restart_blocked"), launch=launch, running=lambda b: False, now=3) == "paused"
    (tmp_path / ms.PAUSE).unlink()
    monkeypatch.setenv("ALL_TOMORROW_METACOG_SESSION_DAILY", "2")
    assert ms.wake(tmp_path, incident("api:restart_blocked"), launch=launch, running=lambda b: False, now=4) == "woken"
    for t in (5, 6):
        assert ms.wake(tmp_path, incident("x:y"), launch=launch, running=lambda b: False, now=t) == "budget"
    assert len(launched) == 2
    assert len(list((tmp_path / "reports").glob("metacog-session-budget-*.json"))) == 1   # 상한 보고도 하루 한 번
    assert ms.wake(tmp_path, incident("x:y"), launch=launch, running=lambda b: False, now=4 + 86401) == "woken"


def test_fingerprint_ignores_numbers():
    assert ms.fingerprint("desk", "HTTP 503") == ms.fingerprint("desk", "HTTP 502") == "desk:HTTP N"


def only(*ids):
    r = servers.load_registry()
    r.services = [s for s in r.services if s.id in ids]
    for s in r.services:
        s.host_id = watch.local_host()
    return r


def test_server_watch_wakes_once_on_block_and_again_after_recovery(tmp_path, _no_real_metacog_session):
    launched = _no_real_metacog_session
    queued = []

    def broken(service):
        raise FileNotFoundError("작업 폴더 없음")

    def sweep(status, now):
        return watch.sweep(tmp_path, registry=only("quote-vn-desk"), probe=lambda s: status, starter=broken,
                           logged_on=lambda: True, now=now, interval=240,
                           enqueue=lambda base, rid, text: queued.append((rid, text)))
    for tick in range(10):
        sweep(("failed", "HTTP 응답 없음"), 1000 + tick * 300)
    assert [fp for _, fp in launched] == ["quote-vn-desk:FileNotFoundError"]
    assert len(queued) == 1 and "메타인지 세션을 깨워" in queued[0][1]
    state = ms.load_state(tmp_path)
    assert state["incidents"]["quote-vn-desk:FileNotFoundError"]["facts"]["ports"] == [8765]
    sweep(("ok", "HTTP 200"), 5000)
    assert ms.load_state(tmp_path)["incidents"] == {}
    for tick in range(5):
        sweep(("failed", "HTTP 응답 없음"), 6000 + tick * 300)
    assert len(launched) == 2 and len(queued) == 2


def test_api_watchdog_block_wakes_once(tmp_path):
    woke = []
    wake = lambda base, inc: woke.append(inc.fingerprint) or "woken"
    for tick in range(15):
        api_watchdog.check_once(tmp_path, probe=lambda: False, recover=lambda t: None,
                                diagnostics=lambda: {}, now=tick * 60, wake=wake)
    assert set(woke) == {"api:restart_blocked"}       # 막힌 동안 매번 불러도 지문은 하나(중복은 wake가 거른다)
    assert len(list((tmp_path / "reports").glob("api-watchdog-limit-*.json"))) == 1


TEXT = """### 본 것
감시가 쓰는 서버 목록 사본의 작업 폴더가 없는 경로였다. 토큰 """ + SECRET + """
### 한 것
cwd를 C:\\projects\\TINProject로 고치고 blocked를 지웠다.
### 결과
해결 — 8765 HTTP 200 확인
### 남은 것
없음
### 물을 것
없음
"""


def test_run_writes_journal_on_top_and_one_report(tmp_path):
    (tmp_path / ms.JOURNAL).write_text("# 메타인지 일지\n\n최신이 위.\n\n## 2026-10-26 10:00\n\n- 예전 기록\n", encoding="utf-8")
    ms.wake(tmp_path, incident(), launch=lambda b, f: None, running=lambda b: False, now=1000)
    seen = {}

    def runner(prompt, argv, *, cwd, timeout):
        seen.update(prompt=prompt, argv=argv, timeout=timeout)
        return {"ok": True, "text": TEXT, "turns": 17, "duration_s": 240, "cost_usd": 0.91, "session_id": "s-1"}

    summary = ms.run(tmp_path, "quote-vn-desk:FileNotFoundError", runner=runner, redact=Redactor({SECRET}))
    assert summary["result"].startswith("해결") and summary["turns"] == 17
    journal = (tmp_path / ms.JOURNAL).read_text(encoding="utf-8")
    assert journal.index("메타인지 세션") < journal.index("예전 기록") and SECRET not in journal
    assert "17턴" in journal and "240초" in journal
    assert "관제" in seen["prompt"] and "물을 것" in seen["prompt"] and seen["timeout"] == 20 * 60
    reports = list((tmp_path / "reports").glob("metacog-session-*.json"))
    assert len(reports) == 1 and "해결" in json.loads(reports[0].read_text(encoding="utf-8"))["content"]
    ms.run(tmp_path, "quote-vn-desk:FileNotFoundError", runner=runner, redact=Redactor({SECRET}))
    assert len(list((tmp_path / "reports").glob("metacog-session-*.json"))) == 1     # 같은 이상의 보고는 한 번
    assert len((tmp_path / ms.RUNS).read_text(encoding="utf-8").splitlines()) == 2


def test_argv_is_headless_allowlisted_and_default_model(tmp_path, monkeypatch):
    monkeypatch.delenv("ALL_TOMORROW_METACOG_SESSION_MODEL", raising=False)
    argv = ms.build_argv(tmp_path, ms.settings())
    assert "-p" in argv and "--model" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--max-turns") + 1] == "40"
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    assert "mcp__oracle__oracle_ask" in allowed and "mcp__all-tomorrow__dispatch_task" in allowed
    assert not any("notion" in a.lower() for a in allowed)
    assert "Bash(git push:*)" in argv[argv.index("--disallowedTools") + 1]
    config = json.loads((tmp_path / "metacog-mcp.json").read_text(encoding="utf-8"))
    assert set(config["mcpServers"]) == {"oracle", "all-tomorrow"}


def test_session_env_drops_key_pool_names(tmp_path, monkeypatch):
    pool = tmp_path / "key-pool.env"
    pool.write_text("ALL_TOMORROW_EDGE_TOKEN=abc\n# NOTE=x\n", encoding="utf-8")
    monkeypatch.setenv("ALL_TOMORROW_EDGE_TOKEN", "abc")
    monkeypatch.setenv("KEEP_ME", "1")
    env = ms.session_env(pool)
    assert "ALL_TOMORROW_EDGE_TOKEN" not in env and env["KEEP_ME"] == "1"


def test_registry_override_for_rehearsal(tmp_path, monkeypatch):
    data = json.loads(servers.REGISTRY.read_text(encoding="utf-8"))
    for s in data["services"]:
        if s["id"] == "quote-vn-desk":
            s["start"]["cwd"] = str(tmp_path / "missing")
    copy = tmp_path / "infra.json"
    copy.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("ALL_TOMORROW_SERVER_REGISTRY", str(copy))
    monkeypatch.setenv("ALL_TOMORROW_SERVER_SWEEP_SECONDS", "50")
    desk = next(s for s in watch.load_registry().services if s.id == "quote-vn-desk")
    assert desk.start.cwd.endswith("missing") and watch.sweep_seconds() == 50
    assert ms.registry_path() == copy


def test_summary_kept_when_watch_resolves_before_session_ends(tmp_path):
    ms.wake(tmp_path, incident(), launch=lambda b, f: None, running=lambda b: False, now=1000)

    def runner(prompt, argv, *, cwd, timeout):
        ms.resolve(tmp_path, "quote-vn-desk")          # 세션이 고치는 사이 감시가 회복을 본다
        return {"ok": True, "text": TEXT, "turns": 3, "duration_s": 9}

    ms.run(tmp_path, "quote-vn-desk:FileNotFoundError", runner=runner, redact=Redactor())
    closed = ms.load_state(tmp_path)["closed"][-1]
    assert closed["session"]["result"].startswith("해결")


def test_watch_tolerates_cleared_starts_key(tmp_path):
    (tmp_path / "server-watch.json").write_text(json.dumps({"servers": {"quote-vn-desk": {"blocked": False}}}), encoding="utf-8")
    started = []
    r = watch.sweep(tmp_path, registry=only("quote-vn-desk"), probe=lambda s: ("failed", "x"),
                    starter=lambda s: started.append(s.id), logged_on=lambda: True, now=1000, interval=240)
    assert r == {"quote-vn-desk": "started"} and started == ["quote-vn-desk"]
