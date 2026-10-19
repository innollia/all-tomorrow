import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from all_tomorrow.tailnet_auth import TailnetIdentity
from all_tomorrow.web import NO_AUTO_COOKIE, SESSION_COOKIE, Auth, create_app

OWNER = "chungho2082@gmail.com"
SERVE_PORT = 8081
OWNER_HEADERS = {"Tailscale-User-Login": OWNER, "X-Forwarded-Proto": "https"}


def app_client(tmp_path, port, *, secure=True, tailnet=True):
    tn = TailnetIdentity({OWNER}, SERVE_PORT) if tailnet else None
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32, state_path=tmp_path / "auth.json"),
                     console_data_dir=str(tmp_path), tailnet=tn, cookie_secure=secure)
    # scope["server"] comes from the base URL: the port the request arrived on.
    return TestClient(app, base_url=f"http://testserver:{port}", follow_redirects=False)


def test_owner_via_tailscale_serve_skips_the_password(tmp_path) -> None:
    with app_client(tmp_path, SERVE_PORT) as c:
        r = c.get("/login", headers=OWNER_HEADERS)
        assert r.status_code == 303 and r.headers["location"] == "/"
        assert SESSION_COOKIE in r.cookies


def test_header_is_ignored_on_the_main_port(tmp_path) -> None:
    # public Caddy, tailnet :8080 and device agents all arrive here; a forged header does nothing
    with app_client(tmp_path, 8080) as c:
        r = c.get("/login", headers=OWNER_HEADERS)
        assert r.status_code == 200 and "비밀번호" in r.text
        assert c.get("/login/tailnet", headers=OWNER_HEADERS).headers["location"] == "/login?tailnet=unavailable"


def test_other_tailnet_users_and_missing_header_get_the_form(tmp_path) -> None:
    with app_client(tmp_path, SERVE_PORT) as c:
        for headers in ({"Tailscale-User-Login": "someone-else@example.com", "X-Forwarded-Proto": "https"},
                        {"X-Forwarded-Proto": "https"}):
            assert c.get("/login", headers=headers).status_code == 200


def test_secure_cookie_needs_https_from_serve(tmp_path) -> None:
    with app_client(tmp_path, SERVE_PORT) as c:
        # without X-Forwarded-Proto: https the Secure cookie would be dropped -> no auto login
        assert c.get("/login", headers={"Tailscale-User-Login": OWNER}).status_code == 200
    with app_client(tmp_path, SERVE_PORT, secure=False) as c:
        assert c.get("/login", headers={"Tailscale-User-Login": OWNER}).status_code == 303


def test_logout_stops_auto_login_until_asked(tmp_path) -> None:
    with app_client(tmp_path, SERVE_PORT) as c:
        r = c.post("/api/logout")
        assert r.cookies.get(NO_AUTO_COOKIE) == "1"
        c.cookies.set(NO_AUTO_COOKIE, "1")
        assert c.get("/login", headers=OWNER_HEADERS).status_code == 200          # stays on the form
        assert c.get("/login/tailnet", headers=OWNER_HEADERS).status_code == 303  # explicit button


def test_disabled_without_configuration(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ALL_TOMORROW_TAILNET_LOGINS", raising=False)
    assert TailnetIdentity.from_environment() is None
    monkeypatch.setenv("ALL_TOMORROW_TAILNET_LOGINS", OWNER)
    monkeypatch.delenv("ALL_TOMORROW_TAILSCALE_SERVE_PORT", raising=False)
    assert TailnetIdentity.from_environment() is None  # never trust the header without a dedicated port
    with app_client(tmp_path, SERVE_PORT, tailnet=False) as c:
        page = c.get("/login", headers=OWNER_HEADERS)
        assert page.status_code == 200 and "/login/tailnet" not in page.text


def test_changed_password_and_revocation_survive_restart(tmp_path) -> None:
    state = tmp_path / "auth.json"
    first = Auth("owner", "long-env-password", "s" * 32, state_path=state)
    old_token = first.issue()
    first.change_password("long-env-password", "short123")
    restarted = Auth("owner", "long-env-password", "s" * 32, state_path=state)
    assert restarted.verify_password("owner", "short123")
    assert not restarted.verify_password("owner", "long-env-password")
    with pytest.raises(HTTPException):
        restarted.verify(old_token)  # revoked before the restart stays revoked
    # a renamed admin user does not inherit the stored hash
    assert Auth("admin", "long-env-password", "s" * 32, state_path=state).verify_password("admin", "long-env-password")
