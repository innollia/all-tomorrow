from fastapi.testclient import TestClient

from all_tomorrow.console.research import ResearchStore, TopicPatch, TopicRequest, save_runs
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
