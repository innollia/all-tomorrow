"""Feature 7 -- file attachments on the request form: max 10MB, max 5 files,
disk-backed (LocalArtifactStore) + DB ArtifactRef (via Goal creation Event),
attachment content treated as unauthorized data (never inline text / never
granting authority -- ingress_policy.attachment_grants_authority stays False)."""
import asyncio
import io

from fastapi.testclient import TestClient

from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore
from all_tomorrow.web import Auth, create_app
from all_tomorrow.web_control import WebControl

SECRET = "s" * 40


def _client(tmp_path) -> TestClient:
    control = WebControl(InMemoryGoalWorkRunStore())
    app = create_app(
        auth=Auth("admin", "pw", SECRET), cookie_secure=False, control=control,
        upload_dir=str(tmp_path / "uploads"),
    )
    client = TestClient(app)
    assert client.post("/api/login", json={"username": "admin", "password": "pw"}).status_code == 204
    return client


def test_submit_with_one_attachment_stores_it_and_links_the_goal(tmp_path):
    client = _client(tmp_path)
    files = [("files", ("note.txt", io.BytesIO(b"hello attachment"), "text/plain"))]
    response = client.post(
        "/api/requests/with-attachments",
        params={"text": "파일 첨부 요청", "idempotency_key": "att-key-1"},
        files=files,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_new"] is True
    stored = list((tmp_path / "uploads").glob("*.dat"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == b"hello attachment"


def test_more_than_five_attachments_is_rejected(tmp_path):
    client = _client(tmp_path)
    files = [("files", (f"f{i}.txt", io.BytesIO(b"x"), "text/plain")) for i in range(6)]
    response = client.post(
        "/api/requests/with-attachments",
        params={"text": "너무 많은 첨부", "idempotency_key": "att-key-2"},
        files=files,
    )
    assert response.status_code == 422


def test_attachment_over_10mb_is_rejected(tmp_path):
    client = _client(tmp_path)
    big = b"a" * (10 * 1024 * 1024 + 1)
    files = [("files", ("big.bin", io.BytesIO(big), "application/octet-stream"))]
    response = client.post(
        "/api/requests/with-attachments",
        params={"text": "너무 큰 첨부", "idempotency_key": "att-key-3"},
        files=files,
    )
    assert response.status_code == 422
    assert list((tmp_path / "uploads").glob("*.dat")) == []


def test_five_attachments_at_exactly_the_limit_is_allowed(tmp_path):
    client = _client(tmp_path)
    files = [("files", (f"f{i}.txt", io.BytesIO(b"ok"), "text/plain")) for i in range(5)]
    response = client.post(
        "/api/requests/with-attachments",
        params={"text": "딱 5개 첨부", "idempotency_key": "att-key-4"},
        files=files,
    )
    assert response.status_code == 200
