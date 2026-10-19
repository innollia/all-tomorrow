import time

import pytest
from fastapi.testclient import TestClient

from all_tomorrow.idea_factory import evaluation
from all_tomorrow.idea_factory.config import gateway_config, load_roster
from all_tomorrow.idea_factory.patents import PatentHit
from all_tomorrow.idea_factory.store import Store
from all_tomorrow.idea_factory.web_routes import FactoryRuntime
from all_tomorrow.web import Auth, create_app


class FakePatents:
    name = "fake"

    def search(self, query, limit=8):
        return [PatentHit("KR1", "주사위 굴림 동기화 장치", "dice sync", "fake", "https://example.test/KR1")]


def fake_chat_json(group, system, user, **kwargs):
    if "아이디어 담당" in system:
        return {"ideas": [{"title": "주사위 동기화", "problem": "p", "approach": "a"},
                          {"title": "세션 요약 봇", "problem": "p", "approach": "a"}]}, "fake"
    if "검색어" in user:
        return {"queries": ["q1"]}, "fake"
    if "겹치는 특허가 하나라도" in system:
        overlaps = [{"number": "KR1", "element": "주사위 동기화"}] if user.startswith("아이디어: 주사위") else []
        return {"overlaps": overlaps, "reason": "r"}, "fake"
    if "회의" in system and "기획안" not in system:
        return {"stance": "support", "reason": "좋다"}, "fake"
    return {"title": "세션 요약 봇", "problem": "p", "approach": "a", "dod": ["d"], "risks": ["r"],
            "market": "m", "effort": "S", "first_step": "f"}, "fake"


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "f.sqlite")
    for m in load_roster().staff:
        s.hire(m["role"], m["name"], m["model_group"])
    return s


def test_gateway_config_references_key_names_only() -> None:
    roster = load_roster()
    config = gateway_config(roster, ["OPENROUTER__A", "GROQ__B", "HUGGINGFACE__C", "OTHER__D"])
    keys = {d["litellm_params"]["api_key"] for d in config["model_list"]}
    assert keys == {"os.environ/OPENROUTER__A", "os.environ/GROQ__B", "os.environ/HUGGINGFACE__C"}
    assert all(d["litellm_params"]["model"].endswith(":free") for d in config["model_list"]
               if d["litellm_params"]["model"].startswith("openrouter/"))


def test_paid_openrouter_model_is_rejected(tmp_path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(open("config/idea-factory.yaml", encoding="utf-8").read().replace(
        "nvidia/nemotron-3-ultra-550b-a55b:free", "openai/gpt-5"), encoding="utf-8")
    with pytest.raises(ValueError):
        load_roster(path)


def test_workflow_kills_patented_idea_and_reports_the_other(tmp_path, monkeypatch) -> None:
    from dbos import DBOS
    from all_tomorrow.idea_factory import pipeline

    monkeypatch.setattr(pipeline.llm, "chat_json", fake_chat_json)
    s = Store(tmp_path / "f.sqlite")
    pipeline.launch(s, f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}", patents=FakePatents())
    try:
        topic_id = pipeline.start_topic("TRPG 유틸리티", actor="test")
        for _ in range(100):
            if s.topic(topic_id)["status"] != "RUNNING":
                break
            time.sleep(0.1)
        assert s.topic(topic_id)["status"] == "DONE"
        statuses = {i["title"]: i["status"] for i in s.ideas(topic_id=topic_id)}
        assert statuses == {"주사위 동기화": "KILLED", "세션 요약 봇": "PROPOSED"}
        killed = s.ideas(status="KILLED")[0]
        assert killed["evidence"][0]["number"] == "KR1"
        assert len(s.votes(f"{topic_id}-i2")) == 8
        assert s.proposals("PENDING")[0]["body"]["patent_check"].startswith("관련 특허 없음")

        pipeline.kill_all("test")
        with pytest.raises(RuntimeError):
            pipeline.start_topic("다른 주제")
    finally:
        DBOS.destroy()


def test_killed_topic_stays_killed_after_loop_reset(tmp_path, monkeypatch) -> None:
    from dbos import DBOS
    from all_tomorrow.idea_factory import pipeline

    monkeypatch.setattr(pipeline.llm, "chat_json", fake_chat_json)
    s = Store(tmp_path / "f.sqlite")
    pipeline.launch(s, f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}", patents=FakePatents())
    try:
        s.set_loop_state("PAUSED", "test")
        topic_id = pipeline.start_topic("주제", actor="test")
        time.sleep(1)
        s.set_topic_status(topic_id, "KILLED")  # kill applied to the topic, cancel never reached it
        s.set_loop_state("RUN", "test")
        time.sleep(7)
        assert s.topic(topic_id)["status"] == "KILLED"
        assert s.ideas(topic_id=topic_id) == []
    finally:
        DBOS.destroy()


def test_user_judgments_promote_and_retire_staff(store) -> None:
    roster = load_roster()
    roster.evaluation_min_samples = 2
    for n in range(2):
        store.add_topic(f"t{n}", "주제")
        store.put_idea({"id": f"t{n}-i1", "topic_id": f"t{n}", "idx": 1, "title": "x", "problem": "",
                        "approach": "", "ideator_id": "ideator-g1"})
        store.put_vote(f"t{n}-i1", roster.council_rounds, "skeptic-g1", "support", "")
        store.put_vote(f"t{n}-i1", roster.council_rounds, "visionary-g1", "oppose", "")
        store.put_proposal(f"t{n}-p", f"t{n}", f"t{n}-i1", {"title": "x"})
        store.decide_proposal(f"t{n}-p", "APPROVED", "", "owner")
    actions = {a["staff_id"]: a["action"] for a in evaluation.apply_policy(store, roster)}
    assert actions == {"ideator-g1": "promote", "skeptic-g1": "promote", "visionary-g1": "retire"}
    assert store.active_staff("visionary")["id"] == "visionary-g2"
    assert store.active_staff("ideator")["model_group"] == "g-gpt-oss-120b"
    # promoted members start over: the same samples do not promote them again
    assert evaluation.apply_policy(store, roster) == []


def test_console_api_controls_loop_and_records_decisions(store) -> None:
    runtime = FactoryRuntime(store=store, roster=load_roster())
    app = create_app(auth=Auth("owner", "pw", "s" * 32), factory=runtime)
    store.add_topic("t1", "주제")
    store.put_idea({"id": "t1-i1", "topic_id": "t1", "idx": 1, "title": "x", "problem": "", "approach": "",
                    "ideator_id": "ideator-g1"})
    store.set_idea_verdict("t1-i1", "KILLED", synth_id="synthesizer-g1", evidence=[], reason="r")
    store.put_proposal("t1-p", "t1", "t1-i1", {"title": "x"})
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/factory/state").status_code == 401
        client.post("/api/login", json={"username": "owner", "password": "pw"})
        assert "통제면" in client.get("/static/console.js").text
        assert client.post("/api/factory/control", json={"action": "pause"}).json()["loop"] == "PAUSED"
        assert client.post("/api/factory/control", json={"action": "kill"}).json()["loop"] == "KILLED"
        assert client.post("/api/factory/control", json={"action": "resume"}).status_code == 409
        assert client.post("/api/factory/control", json={"action": "reset"}).json()["loop"] == "RUN"
        assert client.post("/api/factory/topics", json={"text": "x"}).status_code == 503
        assert client.post("/api/factory/proposals/t1-p/decision", json={"decision": "REJECTED", "reason": "별로"}).status_code == 200
        assert client.post("/api/factory/ideas/t1-i1/review", json={"verdict": "overkill"}).status_code == 200
        assert client.get("/api/factory/state").json()["counts"]["REJECTED"] == 1
        actions = [a["action"] for a in client.get("/api/factory/audit").json()]
        assert {"loop_state", "proposal_decision", "kill_review"} <= set(actions)
