"""Feature 8 -- Discord CENTRAL_TASK requests land in the same Goal/Work store as
the web UI, visible with transport=discord; dedup key is the Discord message id."""
import asyncio

from fastapi.testclient import TestClient

from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore
from all_tomorrow.web import Auth, create_app
from all_tomorrow.web_control import WebControl

SECRET = "s" * 40


def _client(store) -> tuple[TestClient, WebControl]:
    control = WebControl(store)
    app = create_app(
        auth=Auth("admin", "pw", SECRET, edge_token="edge-secret"),
        cookie_secure=False, control=control,
    )
    client = TestClient(app)
    assert client.post("/api/login", json={"username": "admin", "password": "pw"}).status_code == 204
    return client, control


def test_central_task_from_discord_creates_goal_visible_with_transport():
    store = InMemoryGoalWorkRunStore()
    client, control = _client(store)
    response = client.post(
        "/internal/edge/discord/decide",
        headers={"authorization": "Bearer edge-secret"},
        json={
            "intent": "long_task", "needs_long_running_task": True,
            "discord_user_id": "admin", "discord_message_id": "msg-1",
            "text": "디스코드에서 요청한 작업",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "CENTRAL_TASK"
    assert body["is_new"] is True
    goal_id = body["goal_id"]

    overview = client.get("/api/overview").json()
    goal = [g for g in overview["goals"] if g["goal_id"] == goal_id][0]
    assert goal["transport"] == "discord"
    assert goal["title"] == "디스코드에서 요청한 작업"


def test_duplicate_discord_message_id_dedups_to_one_goal():
    store = InMemoryGoalWorkRunStore()
    client, control = _client(store)
    body = {
        "intent": "long_task", "needs_long_running_task": True,
        "discord_user_id": "admin", "discord_message_id": "msg-dup",
        "text": "중복 방지 테스트",
    }
    r1 = client.post("/internal/edge/discord/decide", headers={"authorization": "Bearer edge-secret"}, json=body)
    r2 = client.post("/internal/edge/discord/decide", headers={"authorization": "Bearer edge-secret"}, json=body)
    assert r1.json()["is_new"] is True
    assert r2.json()["is_new"] is False
    assert r1.json()["goal_id"] == r2.json()["goal_id"]

    overview = client.get("/api/overview").json()
    discord_goals = [g for g in overview["goals"] if g["transport"] == "discord"]
    assert len(discord_goals) == 1


def test_non_central_task_discord_decision_does_not_create_a_goal():
    store = InMemoryGoalWorkRunStore()
    client, control = _client(store)
    response = client.post(
        "/internal/edge/discord/decide",
        headers={"authorization": "Bearer edge-secret"},
        json={
            "intent": "casual_chat",
            "discord_user_id": "admin", "discord_message_id": "msg-2",
            "text": "그냥 인사",
        },
    )
    body = response.json()
    assert body["action"] == "LOCAL_REPLY"
    assert "goal_id" not in body
    overview = client.get("/api/overview").json()
    assert overview["goals"] == []
