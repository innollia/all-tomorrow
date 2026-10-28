import pytest
from fastapi.testclient import TestClient

from all_tomorrow.console.research import ResearchStore, TopicPatch, TopicRequest, save_runs
from all_tomorrow.overseer import research_mcp
from all_tomorrow.web import Auth, create_app


def login(tmp_path) -> TestClient:
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path))
    client = TestClient(app, base_url="https://testserver")
    client.__enter__()
    client.post("/api/login", json={"username": "owner", "password": "correct horse"})
    return client


def test_research_api_crud_move_and_result(tmp_path) -> None:
    anon = TestClient(create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path)),
                      base_url="https://testserver")
    assert anon.get("/api/research").status_code == 401
    c = login(tmp_path)
    assert "/static/console/pages/research.js" in c.get("/").text
    a = c.post("/api/research", json={"ask": "첫째 주제\n자세히"}).json()
    b = c.post("/api/research", json={"title": "둘째", "ask": "둘째 요청", "project_id": "p2", "repeat_days": 7}).json()
    assert a["title"] == "첫째 주제" and a["project_id"] == "all-tomorrow" and a["enabled"] and a["run_now_at"] is None
    assert [t["id"] for t in c.get("/api/research").json()] == [a["id"], b["id"]]
    assert c.post("/api/research", json={"ask": "   "}).status_code == 422

    assert c.put(f"/api/research/{b['id']}", json={"move": -1}).status_code == 200
    assert [t["id"] for t in c.get("/api/research").json()] == [b["id"], a["id"]]
    c.put(f"/api/research/{b['id']}", json={"move": -1})            # 맨 위에서 더 올려도 그대로
    assert c.get("/api/research").json()[0]["id"] == b["id"]

    off = c.put(f"/api/research/{a['id']}", json={"enabled": False, "title": "  ", "repeat_days": 3}).json()
    assert off["enabled"] is False and off["title"] == "첫째 주제" and off["repeat_days"] == 3
    now = c.put(f"/api/research/{a['id']}", json={"run_now": True}).json()
    assert now["enabled"] is True and now["run_now_at"]
    assert c.put(f"/api/research/{a['id']}", json={"ask": " "}).status_code == 422
    assert c.put("/api/research/nope", json={"enabled": True}).status_code == 404

    folder = tmp_path / "research"
    (folder / "results").mkdir()
    (folder / "results" / "RR-1.md").write_text("# 결과\n본문", encoding="utf-8")
    save_runs(folder, [{"id": "RR-1", "topic_id": a["id"], "started": 1.0, "status": "SUCCESS", "result_file": "RR-1.md"},
                       {"id": "RR-2", "topic_id": a["id"], "started": 2.0, "status": "SUCCESS", "result_file": "../x.md"}])
    shown = {t["id"]: t for t in c.get("/api/research").json()}
    assert [r["id"] for r in shown[a["id"]]["runs"]] == ["RR-2", "RR-1"] and shown[b["id"]]["runs"] == []
    assert c.get("/api/research/runs/RR-1").json()["text"].startswith("# 결과")
    assert c.get("/api/research/runs/RR-2").status_code == 404     # 경로를 벗어나는 이름
    assert c.get("/api/research/runs/none").status_code == 404

    assert c.delete(f"/api/research/{a['id']}").status_code == 204
    assert c.delete(f"/api/research/{a['id']}").status_code == 404
    assert (folder / "results" / "RR-1.md").exists()               # 결과 파일은 남는다


def test_store_survives_missing_or_broken_files(tmp_path) -> None:
    store = ResearchStore(tmp_path / "research")
    assert store.overview() == []
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "agenda.json").write_text("{깨짐", encoding="utf-8")
    assert store.topics() == []
    topic = store.create(TopicRequest(ask="x"))
    assert store.update(topic["id"], TopicPatch(move=1))["id"] == topic["id"]


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
    research_mcp.update_topic(added["id"], reason="새 근거", project_id="new-game")
    listed = research_mcp.list_topics()
    assert listed["topics"][0]["source"] == "metacog" and listed["topics"][0]["reason"] == "새 근거"
    assert listed["topics"][0]["project_id"] == "new-game"
    assert listed["declined_by_user"] == []
