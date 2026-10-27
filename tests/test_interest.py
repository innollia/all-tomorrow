import json
import sqlite3
from datetime import datetime
from functools import partial
from pathlib import Path

import pytest

from all_tomorrow.console.ideas import IdeaStore
from all_tomorrow.console.research import ResearchStore, TopicPatch
from all_tomorrow.overseer import interest, metacog_session, research_mcp


def stamp(day: int, hour: int = 12) -> str:
    return datetime(2026, 10, day, hour).astimezone().isoformat(timespec="seconds")


def epoch(day: int, hour: int = 12) -> float:
    return datetime(2026, 10, day, hour).timestamp()


@pytest.fixture
def console(tmp_path):
    folder = tmp_path / "console"
    IdeaStore(folder / "ideas")
    con = sqlite3.connect(folder / "ideas" / "ideas.sqlite")
    con.execute("INSERT INTO ideas (id, title, text, prompt, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                ("I-1", "게임 개발 툴", "x", "x", stamp(20), stamp(20)))
    con.execute("INSERT INTO pastes (idea_id, raw, created_at) VALUES (?,?,?)", ("I-1", "x", stamp(22)))
    material = ("INSERT INTO materials (idea_id, kind, label, url, title, body, note, task_id, assigned, file, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    con.execute(material, ("I-1", "url", "u", "u", "t", "b", "사용자 크롬(로그인)으로 읽은 원문 · 실행 RR-261024-1", "", "", "", stamp(24)))
    con.commit()
    con.close()
    return folder


def test_metacog_topics_are_marked_and_user_declines_stick(tmp_path):
    store = ResearchStore(tmp_path / "research")
    mine = store.create_followup("I-1", "경쟁 도구 가격")
    topic = store.suggest("엔진 플러그인 시장", "Godot·Unity 에셋 스토어의 AI 도구 현황", "I-1 종합본의 '시장' 칸이 비어 있음", idea_id="I-1")
    assert topic["source"] == "metacog" and topic["idea_id"] == "I-1" and topic["run_now_at"] is None
    with pytest.raises(ValueError):
        store.revise(mine["id"], ask="바꿈")          # 사용자가 넣은 주제는 메타인지가 고치지 않는다
    store.update(topic["id"], TopicPatch(enabled=False))
    assert store.declined()[0]["how"] == "끈"
    with pytest.raises(ValueError):
        store.revise(topic["id"], ask="다시")
    store.delete(topic["id"])
    with pytest.raises(ValueError, match="지운"):
        store.suggest("엔진 플러그인 시장!", "다른 말", "근거")   # 이름만 조금 바꿔 다시 넣지 못한다
    store.delete(mine["id"])
    assert [d["id"] for d in store.declined()] == [topic["id"]]   # 사용자 주제를 지운 것은 거절 기록이 아니다


def test_mcp_lists_source_and_declined(tmp_path, monkeypatch):
    monkeypatch.setattr(research_mcp, "research_dir", lambda: tmp_path / "research")
    added = research_mcp.add_topic("t", "조사", "근거", idea_id="I-1")
    research_mcp.update_topic(added["id"], reason="새 근거")
    listed = research_mcp.list_topics()
    assert listed["topics"][0]["source"] == "metacog" and listed["topics"][0]["reason"] == "새 근거"
    assert listed["declined_by_user"] == []


def test_facts_count_only_the_users_own_activity(console, tmp_path):
    research = ResearchStore(console / "research")
    research._save([{**research.create_followup("I-1", "더 찾아 줘"), "created": epoch(26)}])
    root = tmp_path / "projects"
    (root / "new-game").mkdir(parents=True)
    (root / "_backups").mkdir()
    facts = interest.observe(epoch(27), console=console, root=root)
    idea = facts["ideas"]["I-1"]
    # 10/24 자료는 조사 실행이 넣은 것이라 사용자 활동이 아니다. 오늘은 추가 조사 요청.
    assert "2026-10-24" not in idea["days"] and idea["days"]["2026-10-22"] == ["결과 붙여 넣기"]
    assert idea["days"]["2026-10-26"] == ["추가 조사 요청"]
    assert idea["research"]["topics"] == 1
    assert list(facts["projects"]) == ["new-game"]
    text = interest.render(facts)
    assert "I-1 게임 개발 툴" in text and "new-game" in text and "사용자가 끄거나 지운 메타인지 주제" in text


def test_interest_wakes_once_per_flow_and_again_after_quiet(tmp_path):
    base = tmp_path / "overseer"
    base.mkdir()
    launched = []
    wake = partial(metacog_session.wake, launch=lambda b, fp: launched.append(fp), running=lambda b: False)
    facts = {"today": "2026-10-27", "declined": [], "projects": {"new-game": {"made": "2026-10-26", "path": "p", "commit_days": []}},
             "ideas": {"I-1": {"title": "툴", "days": {"2026-10-25": ["쪼개기"], "2026-10-27": ["추가 조사 요청"]}}}}
    assert interest.check(base, epoch(27), facts=facts, wake=wake) == "woken"
    assert interest.check(base, epoch(27, 13), facts=facts, wake=wake) == "quiet"
    assert len(launched) == 1                     # 바뀐 곳이 둘이어도 세션은 하나
    state = metacog_session.load_state(base)
    assert set(state["incidents"]) == {"interest:idea:I-1", "interest:project:new-game"} and len(state["runs"]) == 1
    later = {**facts, "today": "2026-10-31"}      # 사흘 넘게 조용하면 지문을 닫는다
    assert interest.check(base, epoch(31), facts=later, wake=wake) == "quiet"
    assert "interest:idea:I-1" not in metacog_session.load_state(base)["incidents"]
    again = {**later, "ideas": {"I-1": {"title": "툴", "days": {"2026-10-27": ["x"], "2026-10-31": ["자료 넣기"]}}}}
    assert interest.check(base, epoch(31, 13), facts=again, wake=wake) == "woken"
    assert launched[-1] == "interest:idea:I-1"


def test_interest_session_prompt_states_purpose_and_gets_research_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(interest, "summary", lambda now=None: "- I-1 게임 개발 툴 · 활동한 날 2일")
    entry = {"fingerprint": "interest:idea:I-1", "source": "interest", "title": "아이디어 I-1에 며칠째 손댐",
             "detail": "- 활동한 날 10-25, 10-27", "facts": {}}
    prompt = metacog_session.build_prompt(tmp_path, entry, metacog_session.settings())
    assert "사용자가 돌아와서 '해 뒀으면 좋았을' 일을 미리 해 둔다" in prompt
    assert "I-1 게임 개발 툴" in prompt and "list_research_topics" in prompt
    servers = json.loads(metacog_session.mcp_config(tmp_path).read_text(encoding="utf-8"))["mcpServers"]
    assert servers["research"]["args"][-1] == "all_tomorrow.overseer.research_mcp"
