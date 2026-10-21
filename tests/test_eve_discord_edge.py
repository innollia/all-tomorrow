import asyncio

from fastapi.testclient import TestClient

from all_tomorrow.overseer import reports
from all_tomorrow.overseer.loop import central_snapshot, event
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore
from all_tomorrow.web import Auth, create_app
from all_tomorrow.web_control import WebControl


def test_eve_backlog_ack_reply_and_owner_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(tmp_path))
    monkeypatch.setenv("DISCORD_OWNER_USER_ID", "123")
    store = InMemoryGoalWorkRunStore()
    question = event("metacog.question", payload={"report": "[질문] 권한 확대? " + "😀" * 1000})
    asyncio.run(store.append_event(question))
    app = create_app(auth=Auth("owner", "password", "s" * 32, edge_token="edge-secret"),
                     control=WebControl(store))
    headers = {"Authorization": "Bearer edge-secret"}
    with TestClient(app) as client:
        assert client.get("/internal/edge/discord/reports").status_code == 401
        batch = client.get("/internal/edge/discord/reports", headers=headers).json()
        report = batch["reports"][0]
        assert report["event_id"] == str(question.event_id)
        assert report["next_part"] == 0
        assert len(report["parts"]) == 2
        ack = {"event_id": report["event_id"], "part": 0, "message_id": "900"}
        assert client.post("/internal/edge/discord/reports/ack", headers=headers, json={**ack, "part": 1}).status_code == 409
        assert client.post("/internal/edge/discord/reports/ack", headers=headers, json=ack).status_code == 200
        assert client.post("/internal/edge/discord/reports/ack", headers=headers, json=ack).status_code == 200
        # 봇 재시작 후 같은 파일을 읽어 성공한 부분 다음부터 재개한다.
        assert client.get("/internal/edge/discord/reports", headers=headers).json()["reports"][0]["next_part"] == 1
        assert client.post("/internal/edge/discord/reports/ack", headers=headers,
                           json={**ack, "part": 1, "message_id": "901"}).status_code == 200
        assert client.get("/internal/edge/discord/reports", headers=headers).json()["reports"] == []
        reply = {"discord_user_id": "123", "discord_message_id": "902", "reply_to_message_id": "900", "text": "승인해"}
        assert client.post("/internal/edge/discord/reply", headers=headers,
                           json={**reply, "discord_user_id": "other"}).status_code == 403
        for _ in range(2):
            response = client.post("/internal/edge/discord/reply", headers=headers, json=reply)
            assert response.json()["approval_granted"] is False
        events = asyncio.run(store.list_events())
        answers = [e for e in events if e.type == "discord.question_reply"]
        assert len(answers) == 1 and answers[0].payload["question_event_id"] == str(question.event_id)
        assert answers[0].payload["text"] == "승인해"
        snapshot = asyncio.run(central_snapshot(store))
        assert any(e["type"] == "discord.question_reply" for e in snapshot["events"])
        assert not asyncio.run(store.list_goals())


def test_central_query_and_project_action_create_owner_request(tmp_path, monkeypatch):
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(tmp_path))
    monkeypatch.setenv("DISCORD_OWNER_USER_ID", "123")
    store = InMemoryGoalWorkRunStore()
    app = create_app(auth=Auth("owner", "password", "s" * 32, edge_token="secret"), control=WebControl(store))
    headers = {"Authorization": "Bearer secret"}
    with TestClient(app) as client:
        for i, flag in enumerate(["needs_project_state", "needs_canonical_mutation", "needs_long_running_task"]):
            body = {"intent": "request", flag: True, "discord_user_id": "123",
                    "discord_message_id": str(i), "text": "프로젝트를 확인하고 처리해 줘"}
            first = client.post("/internal/edge/discord/decide", headers=headers, json=body).json()
            second = client.post("/internal/edge/discord/decide", headers=headers, json=body).json()
            assert first["goal_id"] == second["goal_id"]
            assert second["is_new"] is False
        assert len(asyncio.run(store.list_goals())) == 3
        assert all(g.user_id == "owner" for g in asyncio.run(store.list_goals()))
        assert client.post("/internal/edge/discord/decide", headers=headers,
                           json={**body, "discord_user_id": "other"}).status_code == 403


def test_eve_default_never_uses_webhook(tmp_path, monkeypatch):
    monkeypatch.setattr("all_tomorrow.overseer.environment.load_key_pool", lambda: None)
    monkeypatch.delenv("ALL_TOMORROW_DISCORD_TRANSPORT", raising=False)
    monkeypatch.setenv("ALL_TOMORROW_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/unused")
    reports.enqueue(tmp_path, "evt", "보고")
    assert reports.flush(tmp_path, post=lambda *a, **k: (_ for _ in ()).throw(AssertionError())) == 0
    assert reports.pending(tmp_path)[0]["event_id"] == "evt"
