from fastapi.testclient import TestClient

from all_tomorrow.contracts import Project
from all_tomorrow.web import Auth, WebState, create_app


def make_client() -> TestClient:
    state = WebState(
        projects={"project:eve": Project("project:eve", "Eve", "eve-scene-runtime")},
        runs=[{"run_id": "run_1", "status": "NEED_USER"}],
        questions=[{"question_id": "q_1", "question": "Which repo?"}],
    )
    app = create_app(
        auth=Auth("owner", "correct horse", "s" * 32, edge_token="edge-secret"),
        web_state=state,
    )
    return TestClient(app, base_url="https://testserver")


def test_health_is_public_but_control_plane_data_requires_login() -> None:
    with make_client() as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/projects").status_code == 401


def test_login_exposes_projects_runs_and_questions() -> None:
    with make_client() as client:
        response = client.post("/api/login", json={"username": "owner", "password": "correct horse"})
        assert response.status_code == 204
        assert client.get("/api/projects").json()[0]["project_id"] == "project:eve"
        assert client.get("/api/runs").json()[0]["run_id"] == "run_1"
        assert client.get("/api/questions").json()[0]["question_id"] == "q_1"


def test_bad_password_is_rejected() -> None:
    with make_client() as client:
        response = client.post("/api/login", json={"username": "owner", "password": "wrong"})
        assert response.status_code == 401


def test_authenticated_edge_decision_keeps_casual_chat_local() -> None:
    with make_client() as client:
        client.post("/api/login", json={"username": "owner", "password": "correct horse"})
        response = client.post("/api/edge/discord/decide", json={"intent": "casual_chat"})
        assert response.status_code == 200
        assert response.json()["action"] == "LOCAL_REPLY"


def test_internal_edge_decision_uses_separate_service_credential() -> None:
    with make_client() as client:
        assert client.post("/internal/edge/discord/decide", json={"intent": "casual_chat"}).status_code == 401
        response = client.post(
            "/internal/edge/discord/decide",
            headers={"authorization": "Bearer edge-secret"},
            json={"intent": "casual_chat"},
        )
        assert response.status_code == 200
        assert response.json()["action"] == "LOCAL_REPLY"


def test_usage_ingest_requires_its_own_token_and_is_shown_after_login(tmp_path) -> None:
    state = WebState(usage_path=tmp_path / "usage.json")
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32, edge_token="edge-secret", usage_token="usage-secret"), web_state=state)
    snapshot = {
        "collected_at": "2026-10-19T00:00:00+00:00",
        "providers": [{"id": "claude", "name": "Claude", "plan": "Max 20x", "status": "connected",
                       "observed_at": "2026-10-19T00:00:00+00:00",
                       "windows": [{"label": "5-hour", "percent": 3, "resets_at": "2026-10-19T03:00:00+00:00"}]}],
    }
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/internal/usage", json=snapshot, headers={"authorization": "Bearer edge-secret"}).status_code == 401
        assert client.post("/internal/usage", json=snapshot, headers={"authorization": "Bearer usage-secret"}).status_code == 204
        assert client.get("/api/usage").status_code == 401
        client.post("/api/login", json={"username": "owner", "password": "correct horse"})
        assert client.get("/api/usage").json()["providers"][0]["windows"][0]["percent"] == 3
        assert 'id="usage"' in client.get("/").text
    assert WebState(usage_path=tmp_path / "usage.json").usage["providers"][0]["plan"] == "Max 20x"


def test_claude_limits_map_to_dashboard_windows() -> None:
    from all_tomorrow.usage import claude_windows

    windows = claude_windows({"limits": [
        {"kind": "session", "percent": 3, "resets_at": "a"},
        {"kind": "weekly_all", "percent": 97, "resets_at": "b"},
        {"kind": "weekly_scoped", "percent": 1, "resets_at": "c", "scope": {"model": {"display_name": "Fable"}}},
    ]})
    assert [w["label"] for w in windows] == ["5-hour", "Weekly", "Weekly · Fable"]
