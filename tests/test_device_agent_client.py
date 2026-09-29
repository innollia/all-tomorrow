"""Device agent client against a real (in-process) FastAPI app via ASGI
transport — no network socket, but exercises the actual HTTP contract."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from all_tomorrow.device_agent_client import DeviceAgentClient, DeviceAgentClientError
from all_tomorrow.web import Auth, create_app


@pytest.fixture
def app():
    auth = Auth("innollia", "password123", "s" * 40)
    return create_app(auth=auth, cookie_secure=False)


@pytest.fixture
def logged_in_http(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def _issue_code(http: httpx.AsyncClient) -> str:
    r = await http.post("/api/login", json={"username": "innollia", "password": "password123"})
    assert r.status_code == 204
    r = await http.post("/api/devices/registration-code")
    assert r.status_code == 200
    return r.json()["registration_code"]


async def test_client_registers_and_persists_state(app, tmp_path: Path, logged_in_http) -> None:
    code = await _issue_code(logged_in_http)
    transport = httpx.ASGITransport(app=app)
    client = DeviceAgentClient(
        base_url="http://testserver", state_path=tmp_path / "state.json",
        worker_config_path=tmp_path / "unused.json", device_name="dp7",
    )
    client._http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        await client.register(code, capabilities=frozenset({"kiro"}))
        assert client.device_id is not None
        assert (tmp_path / "state.json").is_file()
        saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert saved["device_id"] == client.device_id
        assert saved["token"] == client.token

        status = await client.heartbeat()
        assert status == "ONLINE"
    finally:
        await client.close()


async def test_client_ensure_registered_reuses_saved_state(app, tmp_path: Path, logged_in_http) -> None:
    code = await _issue_code(logged_in_http)
    transport = httpx.ASGITransport(app=app)
    state_path = tmp_path / "state.json"
    client = DeviceAgentClient(base_url="http://testserver", state_path=state_path,
                                worker_config_path=tmp_path / "unused.json", device_name="dp7")
    client._http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    await client.register(code, capabilities=frozenset())
    saved_device_id = client.device_id
    await client.close()

    client2 = DeviceAgentClient(base_url="http://testserver", state_path=state_path,
                                worker_config_path=tmp_path / "unused.json", device_name="dp7")
    client2._http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    try:
        await client2.ensure_registered(None, frozenset())
        assert client2.device_id == saved_device_id
    finally:
        await client2.close()


async def test_client_without_state_or_code_raises(tmp_path: Path) -> None:
    client = DeviceAgentClient(base_url="http://testserver", state_path=tmp_path / "state.json",
                                worker_config_path=tmp_path / "unused.json")
    with pytest.raises(DeviceAgentClientError):
        await client.ensure_registered(None, frozenset())
    await client.close()


async def test_claim_returns_none_when_nothing_pending(app, tmp_path: Path, logged_in_http) -> None:
    code = await _issue_code(logged_in_http)
    transport = httpx.ASGITransport(app=app)
    client = DeviceAgentClient(base_url="http://testserver", state_path=tmp_path / "state.json",
                                worker_config_path=tmp_path / "unused.json", device_name="dp7")
    client._http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        await client.register(code, capabilities=frozenset())
        await client.heartbeat()
        lease = await client.claim()
        assert lease is None
    finally:
        await client.close()
