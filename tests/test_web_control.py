import asyncio

from fastapi.testclient import TestClient

from all_tomorrow.domain.ids import new_question_id
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore, QuestionRecordSemantic
from all_tomorrow.web import Auth, create_app
from all_tomorrow.web_control import NotFound, WebControl

SECRET = "s" * 40


def _client(control: WebControl) -> TestClient:
    app = create_app(auth=Auth("admin", "pw", SECRET), cookie_secure=False, control=control)
    client = TestClient(app)
    assert client.post("/api/login", json={"username": "admin", "password": "pw"}).status_code == 204
    return client


def test_web_request_creates_goal_in_store_and_dedups():
    store = InMemoryGoalWorkRunStore()
    client = _client(WebControl(store))
    body = {"text": "보고서 정리해줘", "idempotency_key": "key-00000001"}
    first = client.post("/api/requests", json=body).json()
    second = client.post("/api/requests", json=body).json()
    assert first["is_new"] and not second["is_new"]
    assert first["goal_id"] == second["goal_id"]
    goals = asyncio.run(store.list_goals(user_id="admin"))
    assert len(goals) == 1 and goals[0].title == "보고서 정리해줘"
    overview = client.get("/api/overview").json()
    assert overview["goals"][0]["works"][0]["status"] == "PENDING"


def test_cancel_goal_from_web():
    store = InMemoryGoalWorkRunStore()
    client = _client(WebControl(store))
    goal_id = client.post("/api/requests", json={"text": "x", "idempotency_key": "key-00000002"}).json()["goal_id"]
    assert client.post(f"/api/goals/{goal_id}/cancel").status_code == 200
    goal = client.get("/api/overview").json()["goals"][0]
    assert goal["status"] == "CANCEL_REQUESTED"
    assert goal["works"][0]["status"] == "CANCELLED"


def test_answer_pending_question_from_web():
    store = InMemoryGoalWorkRunStore()
    client = _client(WebControl(store))
    client.post("/api/requests", json={"text": "x", "idempotency_key": "key-00000003"})
    work_id = client.get("/api/overview").json()["goals"][0]["works"][0]["work_id"]
    qid = new_question_id()
    asyncio.run(store.create_question(QuestionRecordSemantic(question_id=qid, prompt="어느 쪽?", work_id=work_id)))
    questions = client.get("/api/overview").json()["questions"]
    assert questions[0]["prompt"] == "어느 쪽?"
    assert client.post(f"/api/questions/{qid}/answer", json={"answer": "A"}).json()["status"] == "ANSWERED"
    assert client.get("/api/overview").json()["questions"] == []


def test_other_users_objects_are_invisible():
    store = InMemoryGoalWorkRunStore()
    ctl = WebControl(store)
    goal_id = asyncio.run(ctl.submit("alice", "비밀 일", "key-00000004"))["goal_id"]
    assert asyncio.run(ctl.overview("bob"))["goals"] == []
    try:
        asyncio.run(ctl.cancel("bob", goal_id))
    except NotFound:
        pass
    else:
        raise AssertionError("bob must not cancel alice's goal")


def test_api_requires_login_and_page_is_dark():
    app = create_app(auth=Auth("admin", "pw", SECRET), cookie_secure=False)
    client = TestClient(app)
    assert client.get("/api/overview").status_code == 401
    assert client.post("/api/requests", json={"text": "x", "idempotency_key": "key-00000005"}).status_code == 401
    assert "background:#000" in client.get("/login").text



import os

import pytest


@pytest.mark.skipif(not os.environ.get("AT_SEMANTIC_TEST_URL"), reason="needs AT_SEMANTIC_TEST_URL (live Postgres)")
def test_web_uses_postgres_and_survives_restart(monkeypatch):
    from all_tomorrow.web import app_from_environment

    monkeypatch.setenv("ALL_TOMORROW_ADMIN_USER", "admin")
    monkeypatch.setenv("ALL_TOMORROW_ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("ALL_TOMORROW_SESSION_SECRET", SECRET)
    monkeypatch.setenv("ALL_TOMORROW_COOKIE_SECURE", "false")
    monkeypatch.setenv("ALL_TOMORROW_DATABASE_URL", os.environ["AT_SEMANTIC_TEST_URL"])
    title = f"live-{new_question_id()}"
    with TestClient(app_from_environment()) as client:
        client.post("/api/login", json={"username": "admin", "password": "pw"})
        goal_id = client.post("/api/requests", json={"text": title, "idempotency_key": title}).json()["goal_id"]
    # A fresh process (new app, new pool) still sees it: the data lives in Postgres.
    with TestClient(app_from_environment()) as client:
        client.post("/api/login", json={"username": "admin", "password": "pw"})
        goals = {g["goal_id"]: g for g in client.get("/api/overview").json()["goals"]}
        assert goals[goal_id]["title"] == title
        assert client.post(f"/api/goals/{goal_id}/cancel").status_code == 200
