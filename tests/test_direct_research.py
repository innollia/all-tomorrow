import pytest

from all_tomorrow.console import ideas_jev, ideas_rounds
from all_tomorrow.console.ideas import IdeaStore
from all_tomorrow.overseer import direct_research
from tests.test_idea_followup import login, make_idea

BLOCK = """=== 자료봉 결과 ===
아이디어 ID: {iid}
하위과제 ID: {sid}
하위과제: 시장
상태: 완료
---
## 결론 (3줄 이내)
{body}
=== 끝 ===
"""
SPLIT = """1. 질문 풀이
### S1 · 일본 시장 · 독립
```
task_id: S1
결과 형식:
```
=== 자료봉 결과 ===
```
끝까지 조사한다
```

### S2 · 가격 · 독립
```text
task_id: S2
```
"""


class Fake:
    """start_run·read_run 대신: 띄운 일을 적어 두고, 답을 정해 준 대로 돌려준다."""
    def __init__(self):
        self.started, self.status = [], {}

    def start(self, project_id, worker, task, *, cwd, argv_suffix, worker_options):
        run_id = f"run{len(self.started)}"
        self.started.append({"id": run_id, "worker": worker, "task": task, "cwd": cwd, "suffix": argv_suffix, "options": worker_options})
        return {"run_id": run_id}

    def read(self, run_id):
        return self.status.get(run_id, {"status": "RUNNING"})

    def answer(self, n, output, key="output"):
        self.status[self.started[n]["id"]] = {"status": "SUCCESS", "result": {"payload": {key: output}}}


@pytest.fixture
def env(tmp_path):
    store = IdeaStore(tmp_path / "ideas")
    iid = store.create("게임 도구", "AI 게임 도구 아이디어")
    fake = Fake()

    def tick():
        return direct_research.tick(tmp_path / "ov", start=fake.start, read=fake.read, folder=tmp_path / "research")
    (tmp_path / "ov").mkdir()
    return store, iid, fake, tick, tmp_path


def test_task_prompt_takes_the_whole_outer_block() -> None:
    assert ideas_jev.task_prompt(SPLIT, "S1").endswith("끝까지 조사한다") and "=== 자료봉 결과 ===" in ideas_jev.task_prompt(SPLIT, "S1")
    assert ideas_jev.task_prompt(SPLIT, "S2") == "task_id: S2" and ideas_jev.task_prompt(SPLIT, "S9") == ""


def test_chosen_model_splits_then_runs_tasks_together_and_files_results(env) -> None:
    store, iid, fake, tick, tmp_path = env
    assert ideas_rounds.run_new(store, iid, "일본에서도 되나", "antigravity", "gemini-x")["n"] == 1
    with pytest.raises(ValueError, match="쪼개는 중"):
        ideas_rounds.run_new(store, iid, "더", "claude", "claude-opus-5-5")
    assert tick() == "started"
    split = fake.started[0]
    assert "쪼개기만 한다" in split["task"] and "일본에서도 되나" in split["task"]
    assert split["worker"] == "antigravity" and split["options"]["model"] == "gemini-x"
    assert split["cwd"].parent.name == "direct-work" and split["cwd"].is_dir()
    assert ideas_rounds.extras(store, store.get(iid))[0]["state"] == "쪼개는 중"

    fake.answer(0, SPLIT, "response")   # Antigravity answers under another key
    assert tick() == "started"          # both tasks start in the same tick
    assert [s["task"].split("\n")[0] for s in fake.started[1:]] == ["task_id: S1", "task_id: S2"]
    x = ideas_rounds.extras(store, store.get(iid))[0]
    assert x["state"] == "조사 중" and x["tasks"][0]["job"]["worker"] == "antigravity"

    fake.answer(1, BLOCK.format(iid=iid, sid="S1", body="일본도 된다"))
    fake.answer(2, "블록 없이 쓴 답")   # no block: still that task's result
    assert tick() == "finished"
    idea = store.get(iid)
    assert sorted(r["subtask_id"] for r in idea["results"]) == ["S1", "S2"]
    assert ideas_rounds.extras(store, idea)[0]["state"] == "통합 중"
    assert tick() == "none"


def test_answer_without_block_lines_keeps_its_status(env) -> None:
    store, iid, fake, tick, _ = env
    ideas_rounds.run_new(store, iid, "일본", "claude", "claude-haiku-5-5")
    tick()
    fake.answer(0, SPLIT)
    tick()
    fake.answer(1, f"```\n아이디어 ID: {iid}\n하위과제 ID: S1\n상태: 완료\n---\n## 결론\n된다\n```")
    fake.answer(2, "[수집 실패]\n아무것도 못 읽음")
    tick()
    [r] = store.get(iid)["results"]
    assert (r["subtask_id"], r["status"], r["body"]) == ("S1", "완료", "## 결론\n된다")
    assert ideas_rounds.extras(store, store.get(iid))[0]["tasks"][1]["job"]["status"] == "FAILED"


def test_failed_task_shows_why_and_runs_again_with_another_model(env) -> None:
    store, iid, fake, tick, _ = env
    ideas_rounds.run_new(store, iid, "일본", "codex", "gpt-x")
    tick()
    fake.answer(0, SPLIT)
    tick()
    fake.answer(1, BLOCK.format(iid=iid, sid="S1", body="답"))
    fake.status["run2"] = {"status": "FAILED", "result": {"error": "한도"}}
    tick()
    x = ideas_rounds.extras(store, store.get(iid))[0]
    assert x["state"] == "결과 대기" and x["tasks"][1]["job"]["error"] == "한도"
    assert ideas_rounds.run_extra(store, iid, 1, "claude", "claude-haiku-5-5")["tasks"] == ["S2"]   # S1 has its result
    tick()
    assert fake.started[-1]["worker"] == "claude" and "claude-haiku-5-5" in fake.started[-1]["suffix"]
    with pytest.raises(ValueError, match="돌릴 과제가 없다"):
        ideas_rounds.run_extra(store, iid, 1, "claude", "claude-haiku-5-5")


def test_split_without_tasks_fails_and_files_nothing(env) -> None:
    store, iid, fake, tick, _ = env
    ideas_rounds.run_new(store, iid, "일본", "opencode", "opencode/x")
    tick()
    assert fake.started[0]["options"]["auto"] is True
    fake.answer(0, "조사해 봤더니 일본도 된다")
    tick()
    idea = store.get(iid)
    x = ideas_rounds.extras(store, idea)[0]
    assert x["state"] == "쪼개기 실패" and "과제" in x["split"]["error"] and not idea["results"]


def test_paused_keeps_jobs_waiting_and_cap_limits_running(env, monkeypatch) -> None:
    store, iid, fake, tick, tmp_path = env
    ideas_rounds.run_new(store, iid, "일본", "codex", "gpt-x")
    (tmp_path / "ov" / "research.paused").write_text("")
    assert tick() == "paused" and not fake.started
    (tmp_path / "ov" / "research.paused").unlink()
    monkeypatch.setattr(direct_research, "MAX_RUNNING", 1)
    tick()
    fake.answer(0, SPLIT)
    tick()
    assert len(fake.started) == 2      # the finished split freed the one slot, S2 waits
    tick()
    assert len(fake.started) == 2


def test_api_runs_and_refuses(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(direct_research, "models", lambda: [{"id": "claude", "name": "Claude", "models": [{"id": "m", "name": "M"}]}])
    c = login(tmp_path)
    iid = make_idea(c)
    assert c.get("/api/ideas/direct-models").json()[0]["id"] == "claude"
    assert c.post(f"/api/ideas/{iid}/extras/run", json={"text": "일본", "worker": "kiro", "model": "m"}).status_code == 409
    assert c.post(f"/api/ideas/{iid}/extras/run", json={"text": "일본", "worker": "claude", "model": "--evil"}).status_code == 422
    assert c.post(f"/api/ideas/{iid}/extras/run", json={"text": "일본", "worker": "claude", "model": "m"}).json()["tasks"] == [""]
    assert c.get(f"/api/ideas/{iid}").json()["extras"][0]["state"] == "쪼개는 중"
    assert c.post(f"/api/ideas/{iid}/extras/9/run", json={"worker": "claude", "model": "m"}).status_code == 409
