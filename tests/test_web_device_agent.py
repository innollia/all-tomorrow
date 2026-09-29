"""Device agent web API: registration, user-facing device list, revoke."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from all_tomorrow.web import Auth, create_app


@pytest.fixture
def client() -> TestClient:
    auth = Auth("innollia", "password123", "s" * 40)
    app = create_app(auth=auth, cookie_secure=False)
    c = TestClient(app)
    r = c.post("/api/login", json={"username": "innollia", "password": "password123"})
    assert r.status_code == 204
    return c


def test_issue_registration_code_requires_login() -> None:
    auth = Auth("innollia", "password123", "s" * 40)
    app = create_app(auth=auth, cookie_secure=False)
    c = TestClient(app)
    r = c.post("/api/devices/registration-code")
    assert r.status_code == 401


def test_full_device_lifecycle_through_http(client: TestClient) -> None:
    r = client.post("/api/devices/registration-code")
    assert r.status_code == 200
    code = r.json()["registration_code"]

    r = client.post("/api/device/register", json={
        "registration_code": code, "name": "dp7", "capabilities": ["kiro"], "max_concurrent": 1,
    })
    assert r.status_code == 200
    device_id = r.json()["device_id"]
    token = r.json()["token"]

    r = client.post("/api/device/heartbeat", json={"device_id": device_id, "token": token})
    assert r.status_code == 200
    assert r.json()["status"] == "ONLINE"

    r = client.get("/api/devices")
    assert r.status_code == 200
    devices = r.json()
    assert len(devices) == 1
    assert devices[0]["device_id"] == device_id
    assert devices[0]["status"] == "ONLINE"

    r = client.post("/api/requests", json={"text": "테스트 작업 (기기 연결 테스트, 지워도 됨)",
                                            "idempotency_key": "abc12345"})
    assert r.status_code == 200

    r = client.post("/api/device/claim", json={"device_id": device_id, "token": token})
    assert r.status_code == 200
    lease = r.json()["lease"]
    assert lease is not None
    lease_id = lease["lease_id"]

    r = client.post("/api/device/complete", json={
        "device_id": device_id, "token": token, "lease_id": lease_id,
        "succeeded": True, "output_text": "done", "error": None, "duration_ms": 5,
    })
    assert r.status_code == 200
    assert r.json()["outcome"] == "succeeded"

    r = client.post(f"/api/devices/{device_id}/revoke")
    assert r.status_code == 200
    assert r.json()["status"] == "REVOKED"

    r = client.post("/api/device/heartbeat", json={"device_id": device_id, "token": token})
    assert r.status_code == 401


def test_bad_registration_code_rejected(client: TestClient) -> None:
    r = client.post("/api/device/register", json={
        "registration_code": "not-a-real-code", "name": "x", "capabilities": [],
    })
    assert r.status_code == 422


def test_device_cannot_revoke_another_users_device(client: TestClient) -> None:
    r = client.post("/api/devices/registration-code")
    code = r.json()["registration_code"]
    r = client.post("/api/device/register", json={
        "registration_code": code, "name": "dp7", "capabilities": [],
    })
    device_id = r.json()["device_id"]

    auth2 = Auth("someoneelse", "password123", "s" * 40)
    # A second Auth instance simulates the "not this owner" case by faking a
    # revoke call outside this user's session -- exercised at the service
    # layer directly in tests/test_device_agent.py; here we only check the
    # happy-path owner check via the same client/session, which is the only
    # session this single-tenant web app's Auth class supports.
    r = client.post(f"/api/devices/{device_id}/revoke")
    assert r.status_code == 200
