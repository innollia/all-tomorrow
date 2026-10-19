"""Idea factory as a console feature: mounted by create_app, behind login, DBOS inside the app lifespan."""
import importlib
import sys
import time
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from all_tomorrow.idea_factory.config import load_roster
from all_tomorrow.idea_factory.store import Store
from all_tomorrow.web import Auth, create_app

LOGIN = {"username": "owner", "password": "correct horse"}


def make_app(tmp_path, **kwargs):
    return create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path / "console"), **kwargs)


@pytest.fixture(autouse=True)
def factory_env(tmp_path, monkeypatch):
    monkeypatch.setenv("IDEA_FACTORY_STORE", str(tmp_path / "factory.sqlite"))
    monkeypatch.setenv("IDEA_FACTORY_DBOS_URL", f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}")
    monkeypatch.setenv("IDEA_FACTORY_KEY_POOL", str(tmp_path / "no-key-pool.env"))
    for name in ("IDEA_FACTORY_ENABLED", "IDEA_FACTORY_ROSTER", "IDEA_FACTORY_PATENTS", "KIPRIS_API_KEY", "NOTION_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def seeded_store(tmp_path) -> Store:
    store = Store(tmp_path / "factory.sqlite")
    for m in load_roster().staff:
        store.hire(m["role"], m["name"], m["model_group"], access_level=m.get("access_level", 0),
                   access_scopes=m.get("access_scopes", []))
    store.add_topic("t1", "주제")
    store.put_idea({"id": "t1-i1", "topic_id": "t1", "idx": 1, "title": "x", "problem": "", "approach": "",
                    "ideator_id": "ideator-g1"})
    store.set_idea_verdict("t1-i1", "KILLED", synth_id="synthesizer-g1", evidence=[], reason="r")
    store.put_proposal("t1-p", "t1", "t1-i1", {"title": "x"})
    return store


def test_read_only_factory_controls_loop_and_records_decisions(tmp_path) -> None:
    seeded_store(tmp_path)
    with TestClient(make_app(tmp_path), base_url="https://testserver") as client:
        assert client.get("/api/factory/state").status_code == 401
        client.post("/api/login", json=LOGIN)
        assert "통제면" in client.get("/static/console/pages/factory.js").text
        assert "/static/console/pages/factory.js" in client.get("/").text
        assert client.get("/api/factory/state").json()["runtime"] is False
        assert client.post("/api/factory/control", json={"action": "pause"}).json()["loop"] == "PAUSED"
        assert client.post("/api/factory/control", json={"action": "kill"}).json() == {"loop": "KILLED", "cancelled": 0}
        assert client.post("/api/factory/control", json={"action": "resume"}).status_code == 409
        assert client.post("/api/factory/control", json={"action": "pause"}).status_code == 409
        assert client.post("/api/factory/control", json={"action": "reset"}).json()["loop"] == "RUN"
        assert client.post("/api/factory/topics", json={"text": "x"}).status_code == 503
        assert client.post("/api/factory/proposals/t1-p/decision", json={"decision": "REJECTED", "reason": "별로"}).status_code == 200
        assert client.post("/api/factory/proposals/nope/decision", json={"decision": "APPROVED"}).status_code == 404
        assert client.post("/api/factory/ideas/t1-i1/review", json={"verdict": "overkill"}).status_code == 200
        assert client.post("/api/factory/ideas/t1-i1/review", json={"verdict": "nonsense"}).status_code == 422
        state = client.get("/api/factory/state").json()
        assert state["counts"]["REJECTED"] == 1 and len(state["staff"]) == 6
        assert client.get("/api/factory/topics/t1").json()["ideas"][0]["status"] == "KILLED"
        assert client.get("/api/factory/topics/missing").status_code == 404
        assert client.get("/api/factory/killed").json()[0]["review"] == "overkill"
        assert client.get("/api/factory/staff").json()["policy"]["min_samples"] == load_roster().evaluation_min_samples
        actions = [a["action"] for a in client.get("/api/factory/audit").json()]
        assert {"loop_state", "proposal_decision", "kill_review"} <= set(actions)


def test_missing_roster_keeps_the_console_up_without_evaluation(tmp_path, monkeypatch) -> None:
    # The container image ships src/ only; an optional feature's config must not take the console down.
    seeded_store(tmp_path)
    monkeypatch.setenv("IDEA_FACTORY_ROSTER", str(tmp_path / "missing.yaml"))
    with TestClient(make_app(tmp_path), base_url="https://testserver") as client:
        client.post("/api/login", json=LOGIN)
        assert client.get("/api/factory/staff").json()["policy"] is None
        assert client.post("/api/factory/proposals/t1-p/decision", json={"decision": "APPROVED"}).json() == {"actions": []}
        assert client.get("/api/factory/proposals?status=APPROVED").json()[0]["id"] == "t1-p"


def fake_chat_json(group, system, user, **kwargs):
    if "아이디어 담당" in system:
        return {"ideas": [{"title": "세션 요약 봇", "problem": "p", "approach": "a"}]}, "fake"
    if "회의" in system and "기획안" not in system:
        return {"stance": "support", "reason": "좋다"}, "fake"
    return {"title": "세션 요약 봇", "problem": "p", "approach": "a", "dod": ["d"], "risks": ["r"],
            "market": "m", "effort": "S", "first_step": "f"}, "fake"


def test_enabled_factory_runs_dbos_inside_the_app_lifespan(tmp_path, monkeypatch) -> None:
    # Fresh import: bind the workflows to the live DBOS registry even if another suite destroyed it
    # (see the pipeline fixture in tests/test_idea_factory.py). console.factory imports this same module.
    sys.modules.pop("all_tomorrow.idea_factory.pipeline", None)
    pipeline = importlib.import_module("all_tomorrow.idea_factory.pipeline")

    monkeypatch.setenv("IDEA_FACTORY_ENABLED", "1")
    monkeypatch.setenv("IDEA_FACTORY_PATENTS", "unchecked")
    monkeypatch.setattr(pipeline.llm, "chat_json", fake_chat_json)
    order: list[str] = []
    real_launch, real_shutdown = pipeline.launch, pipeline.shutdown
    monkeypatch.setattr(pipeline, "launch", lambda *a, **k: (order.append("dbos-launch"), real_launch(*a, **k)))
    monkeypatch.setattr(pipeline, "shutdown", lambda: (order.append("dbos-shutdown"), real_shutdown()))

    @asynccontextmanager
    async def app_lifespan(_app):  # stands in for web.py's Postgres open/migrate lifespan
        order.append("app-start")
        yield
        order.append("app-stop")

    app = make_app(tmp_path, lifespan=app_lifespan)
    assert order == []  # building the app launches nothing
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert order == ["app-start", "dbos-launch"]
            client.post("/api/login", json=LOGIN)
            assert client.get("/api/factory/state").json()["runtime"] is True
            topic_id = client.post("/api/factory/topics", json={"text": "TRPG 유틸리티"}).json()["topic_id"]
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and client.get(f"/api/factory/topics/{topic_id}").json()["status"] == "RUNNING":
                time.sleep(0.1)
            topic = client.get(f"/api/factory/topics/{topic_id}").json()
            assert topic["status"] == "DONE" and [i["status"] for i in topic["ideas"]] == ["PROPOSED"]
            assert len(topic["ideas"][0]["votes"]) == 8
            assert client.get("/api/factory/proposals").json()[0]["body"]["patent_check"].startswith("특허 미검사")

            assert client.post("/api/factory/control", json={"action": "pause"}).json()["loop"] == "PAUSED"
            paused = client.post("/api/factory/topics", json={"text": "멈춘 동안의 주제"}).json()["topic_id"]
            time.sleep(0.5)
            assert client.post("/api/factory/control", json={"action": "kill"}).json() == {"loop": "KILLED", "cancelled": 1}
            assert client.get(f"/api/factory/topics/{paused}").json()["status"] == "KILLED"
            assert client.post("/api/factory/topics", json={"text": "x"}).status_code == 409
            assert client.post("/api/factory/control", json={"action": "reset"}).json()["loop"] == "RUN"
            time.sleep(5.5)  # the cancelled workflow wakes from its 5 s pause sleep and exits before DBOS goes away
        assert order == ["app-start", "dbos-launch", "dbos-shutdown", "app-stop"]
    finally:
        real_shutdown()  # no-op when the lifespan already shut DBOS down
