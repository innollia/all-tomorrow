import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from all_tomorrow.tailnet_auth import TailnetIdentity, is_tailnet_address
from all_tomorrow.web import NO_AUTO_COOKIE, SESSION_COOKIE, Auth, create_app

OWNER = "chungho2082@gmail.com"
PHONE = "100.91.14.13"


def identity(owners=None, calls=None):
    table = owners if owners is not None else {PHONE: OWNER, "100.84.9.56": "someone-else@example.com"}

    def whois(host):
        if calls is not None:
            calls.append(host)
        return table.get(host)
    return TailnetIdentity({OWNER}, whois)


def app_client(tmp_path, tailnet, host, *, secure=False, scheme="http"):
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32, state_path=tmp_path / "auth.json"),
                     console_data_dir=str(tmp_path), tailnet=tailnet, cookie_secure=secure)
    return TestClient(app, base_url=f"{scheme}://testserver", client=(host, 51000), follow_redirects=False)


def test_tailnet_ranges() -> None:
    assert is_tailnet_address("100.97.113.3") and is_tailnet_address("fd7a:115c:a1e0::1")
    assert is_tailnet_address("::ffff:100.64.0.1")
    for host in ("127.0.0.1", "172.18.0.5", "15.164.99.125", "100.128.0.1", "testclient", None, ""):
        assert not is_tailnet_address(host)


def test_identity_allows_only_listed_logins_and_caches() -> None:
    calls = []
    tn = identity(calls=calls)
    assert tn.login_for(PHONE) == OWNER and tn.login_for(PHONE) == OWNER
    assert calls == [PHONE]  # cached
    assert tn.login_for("100.84.9.56") is None          # tailnet, but another person's device
    assert tn.login_for("172.18.0.5") is None           # public proxy: never asked
    assert "172.18.0.5" not in calls

    def broken(host):
        raise httpx.ConnectError("no socket")
    assert TailnetIdentity({OWNER}, broken).login_for(PHONE) is None


def test_owner_device_skips_the_password(tmp_path) -> None:
    with app_client(tmp_path, identity(), PHONE) as c:
        r = c.get("/login")
        assert r.status_code == 303 and r.headers["location"] == "/"
        assert SESSION_COOKIE in r.cookies
        c.cookies.set(SESSION_COOKIE, r.cookies[SESSION_COOKIE])
        assert c.get("/").status_code == 200


def test_others_and_public_proxy_get_the_form(tmp_path) -> None:
    for host in ("100.84.9.56", "172.18.0.5"):
        with app_client(tmp_path, identity(), host) as c:
            r = c.get("/login")
            assert r.status_code == 200 and "비밀번호" in r.text
            assert c.get("/login/tailnet").headers["location"] == "/login?tailnet=unavailable"


def test_secure_cookie_over_plain_http_never_auto_logs_in(tmp_path) -> None:
    # The browser would drop the cookie and bounce between / and /login forever.
    with app_client(tmp_path, identity(), PHONE, secure=True, scheme="http") as c:
        assert c.get("/login").status_code == 200
    with app_client(tmp_path, identity(), PHONE, secure=True, scheme="https") as c:
        assert c.get("/login").status_code == 303


def test_logout_stops_auto_login_until_asked(tmp_path) -> None:
    with app_client(tmp_path, identity(), PHONE) as c:
        r = c.post("/api/logout")
        assert r.cookies.get(NO_AUTO_COOKIE) == "1"
        c.cookies.set(NO_AUTO_COOKIE, "1")
        assert c.get("/login").status_code == 200            # stays on the form
        assert c.get("/login/tailnet").status_code == 303    # explicit button still works


def test_disabled_without_allowlist(tmp_path) -> None:
    assert TailnetIdentity.from_environment() is None
    with app_client(tmp_path, None, PHONE) as c:
        page = c.get("/login")
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
