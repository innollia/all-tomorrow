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
