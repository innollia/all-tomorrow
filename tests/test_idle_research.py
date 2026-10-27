import json
import time
from datetime import UTC, datetime

import pytest

from all_tomorrow import mcp_server
from all_tomorrow.console.research import ResearchStore, TopicPatch, TopicRequest, load_runs, save_runs
from all_tomorrow.overseer import idle_research as ir

NOW = 1_800_000_000.0
IDLE = 3600.0


def topic(**kw):
    return {"id": "R-1", "title": "t", "ask": "a", "project_id": "all-tomorrow", "repeat_days": 0,
            "enabled": True, "run_now_at": None, **kw}


def run(status="SUCCESS", started=NOW - 10, **kw):
    return {"id": "RR-1", "topic_id": "R-1", "started": started, "status": status, **kw}


def test_due_rules() -> None:
    assert ir.due(topic(), [], NOW, True)
    assert not ir.due(topic(), [], NOW, False)                       # PC 사용 중
    assert not ir.due(topic(enabled=False), [], NOW, True)
    assert not ir.due(topic(), [run()], NOW, True)                   # 한 번만
    assert not ir.due(topic(repeat_days=1), [run(started=NOW - 3600)], NOW, True)
    assert ir.due(topic(repeat_days=1), [run(started=NOW - 90000)], NOW, True)
    assert not ir.due(topic(repeat_days=1), [run(started=NOW - 90000)], NOW, False)
    assert not ir.due(topic(), [run("FAILED", NOW - 3600)], NOW, True)            # 실패 뒤 6시간
    assert ir.due(topic(), [run("FAILED", NOW - ir.RETRY_AFTER - 1)], NOW, True)
    # 지금 돌리기: PC 사용 중이어도, 이미 돈 주제여도 한 번 더. 그 뒤 새 실행이 생기면 소모된다.
    assert ir.due(topic(run_now_at=NOW - 5), [run(started=NOW - 100)], NOW, False)
    assert not ir.due(topic(run_now_at=NOW - 50), [run(started=NOW - 10)], NOW, False)
    assert ir.due(topic(run_now_at=NOW), [], NOW, False)
    assert not ir.due(topic(run_now_at=NOW, enabled=False), [], NOW, False)


def usage(base, *windows, status="connected"):
    (base / "subscription-usage.json").write_text(json.dumps({"providers": [
        {"id": "claude", "status": "connected", "windows": [{"label": "5h", "percent": 99, "resets_at": None}]},
        {"id": "codex", "status": status, "windows": list(windows)}]}), encoding="utf-8")


def win(percent, reset_in=3600):
    return {"label": "5h", "percent": percent, "resets_at": datetime.fromtimestamp(NOW + reset_in, UTC).isoformat()}


def test_quota_judgement(tmp_path) -> None:
    assert ir.quota_ok(tmp_path, 80, NOW) == (False, "사용량 모름")
    usage(tmp_path, win(79.9), win(10))
    assert ir.quota_ok(tmp_path, 80, NOW)[0] is True                  # claude 99%는 보지 않는다
    usage(tmp_path, win(80))
    assert ir.quota_ok(tmp_path, 80, NOW)[0] is False
    usage(tmp_path, win(95, reset_in=-60))                            # 이미 리셋된 창은 무시
    assert ir.quota_ok(tmp_path, 80, NOW)[0] is True
    usage(tmp_path, win(10), status="error")
    assert ir.quota_ok(tmp_path, 80, NOW)[0] is False


@pytest.fixture()
def env(tmp_path, monkeypatch):
    base, folder = tmp_path / "base", tmp_path / "research"
    base.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr(mcp_server, "load_projects", lambda: {"all-tomorrow": {"path": proj.as_posix()}})
    usage(base, win(10))
    calls = []
    results = {}

    def start(project_id, worker, task, **kw):
        calls.append((project_id, worker, task, kw))
        return {"run_id": f"run{len(calls)}"}

    def read(run_id):
        return results.get(run_id, {"status": "RUNNING"})

    def tick(idle=IDLE, now=NOW):
        return ir.tick(base, idle, now=now, start=start, read=read, folder=folder)

    return base, folder, ResearchStore(folder), calls, results, tick


def test_tick_starts_one_topic_with_web_search_then_collects_result(env) -> None:
    base, folder, store, calls, results, tick = env
    assert tick() == "none"
    first = store.create(TopicRequest(title="첫째", ask="첫 요청"))
    store.create(TopicRequest(title="둘째", ask="둘 요청"))
    assert tick(idle=60) == "idle"
    assert tick() == "started"
    assert len(calls) == 1 and calls[0][1] == "codex" and "첫 요청" in calls[0][2]
    assert calls[0][3]["argv_suffix"] == ["-c", 'web_search="live"']
    assert calls[0][3]["worker_options"] == {"timeout_seconds": 1800, "sandbox": "read-only"}
    assert [r["status"] for r in load_runs(folder)] == ["RUNNING"]
    assert tick() == "running" and len(calls) == 1                     # 한 번에 하나
    results["run1"] = {"status": "SUCCESS", "result": {"payload": {"output": "## 한 줄 결론\n끝"}}}
    assert tick() == "finished"
    done = load_runs(folder)[0]
    assert done["status"] == "SUCCESS" and done["topic_id"] == first["id"]
    assert (folder / "results" / done["result_file"]).read_text(encoding="utf-8").startswith("# 첫째")
    assert len(list((base / "reports").glob("*.json"))) == 1
    assert tick(now=NOW + 60) == "started" and "둘 요청" in calls[1][2]  # 다음 주제는 목록에서 다음 것
    assert store.result(done["id"])["text"].endswith("끝\n")


def test_tick_pause_quota_budget_and_failed_runs(env) -> None:
    base, folder, store, calls, results, tick = env
    store.create(TopicRequest(ask="x"))
    (base / "research.paused").write_text("")
    assert tick() == "paused" and not calls
    (base / "research.paused").unlink()
    usage(base, win(85))
    assert tick() == "quota" and not calls
    usage(base, win(10))
    save_runs(folder, [{"id": f"o{i}", "topic_id": "other", "started": NOW - 100 - i, "status": "SUCCESS"} for i in range(8)])
    assert tick() == "budget" and not calls
    save_runs(folder, [])
    assert tick() == "started"
    results["run1"] = {"status": "SUCCESS", "result": {"payload": {"output": None}}}   # 성공이라는데 본문이 없다
    assert tick() == "finished"
    assert load_runs(folder)[0]["status"] == "FAILED" and "result_file" not in load_runs(folder)[0]
    assert tick(now=NOW + 60) == "none"                                 # 6시간 전에는 재시도 없음
    assert tick(now=NOW + ir.RETRY_AFTER + 60) == "started"
    results["run2"] = {"status": "INTERRUPTED", "stderr_tail": "죽음"}
    assert tick(now=NOW + ir.RETRY_AFTER + 120) == "finished"
    assert load_runs(folder)[-1]["status"] == "INTERRUPTED" and load_runs(folder)[-1]["error"] == "죽음"


def test_run_now_ignores_idle_and_start_failure_is_recorded(env) -> None:
    base, folder, store, calls, results, tick = env
    t = store.create(TopicRequest(ask="x"))
    assert tick(idle=None) == "idle"
    store.update(t["id"], TopicPatch(run_now=True))
    later = time.time() + 1

    def boom(*args, **kwargs):
        raise ValueError("없는 프로젝트")

    assert ir.tick(base, None, now=later, start=boom, read=lambda r: {}, folder=folder) == "failed"
    assert load_runs(folder)[0]["status"] == "FAILED" and "ValueError" in load_runs(folder)[0]["error"]
    # 실패한 실행이 '지금 돌리기'를 소모했으므로 PC 사용 중에는 다시 시도하지 않는다.
    assert ir.tick(base, None, now=later + 1, start=boom, read=lambda r: {}, folder=folder) == "idle"


def test_repeat_topic_carries_previous_result(env) -> None:
    base, folder, store, calls, results, tick = env
    store.create(TopicRequest(ask="반복", repeat_days=1))
    tick()
    results["run1"] = {"status": "SUCCESS", "result": {"payload": {"output": "지난 내용"}}}
    tick()
    assert tick(now=NOW + 3600) == "none"
    assert tick(now=NOW + 90000) == "started"
    assert "지난 내용" in calls[1][2] and "바뀐 것" in calls[1][2]


def test_start_run_adds_argv_suffix_and_keeps_dispatch_unchanged(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "PROJECTS_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(mcp_server, "RUNS_DIR", tmp_path / "runs")
    workers = tmp_path / "workers.json"
    workers.write_text(json.dumps({"allowed_roots": [tmp_path.as_posix()],
                                   "workers": {"codex": {"options": {"timeout_seconds": 600}}}}))
    monkeypatch.setattr(mcp_server, "WORKERS_PATH", workers)
    monkeypatch.setattr(mcp_server, "discover_executable", lambda w: "/bin/codex")
    monkeypatch.setattr(mcp_server, "_spawn_detached", lambda d: (1, "fake"))
    proj = tmp_path / "proj"
    proj.mkdir()
    mcp_server.register_project("proj", str(proj), seed_knowhow=False)
    plain = mcp_server.dispatch_task("proj", "codex", "t")
    cfg = json.loads((tmp_path / "runs" / plain["run_id"] / "workers.json").read_text())
    assert "argv" not in cfg["workers"]["codex"] and cfg["workers"]["codex"]["options"]["timeout_seconds"] == 600
    extra = mcp_server.start_run("proj", "codex", "t", worker_options={"timeout_seconds": 1800},
                                 argv_suffix=["-c", 'web_search="live"'])
    cfg = json.loads((tmp_path / "runs" / extra["run_id"] / "workers.json").read_text())
    assert cfg["workers"]["codex"]["argv"] == ["/bin/codex", "-c", 'web_search="live"']
    assert cfg["workers"]["codex"]["options"]["timeout_seconds"] == 1800
    assert json.loads(workers.read_text())["workers"]["codex"]["options"]["timeout_seconds"] == 600   # 원본 설정은 그대로
