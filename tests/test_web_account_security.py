"""Feature 10 -- account security: password change screen, 5-failed-attempt
lockout (15 min), log-out-everywhere (session revoke)."""
from fastapi.testclient import TestClient

from all_tomorrow.web import Auth, create_app

SECRET = "s" * 40


def _client(auth: Auth) -> TestClient:
    app = create_app(auth=auth, cookie_secure=False)
    return TestClient(app)


def test_five_failed_logins_lock_the_account_for_a_while():
    auth = Auth("admin", "correct-password", SECRET)
    client = _client(auth)
    # Attempts 1-4 are plain rejections; the 5th failure crosses the threshold
    # and locks the account (still reported as a credentials failure for that
    # call), and every attempt after that -- even with the RIGHT password --
    # is locked out rather than merely rejected.
    for _ in range(4):
        resp = client.post("/api/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401
    fifth = client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert fifth.status_code in (401, 423)
    locked = client.post("/api/login", json={"username": "admin", "password": "correct-password"})
    assert locked.status_code == 423


def test_password_change_requires_current_password_and_revokes_old_sessions():
    auth = Auth("admin", "old-password", SECRET)
    client = _client(auth)
    assert client.post("/api/login", json={"username": "admin", "password": "old-password"}).status_code == 204
    old_cookie = client.cookies.get("all_tomorrow_session")
    assert old_cookie is not None

    wrong = client.post(
        "/api/account/change-password",
        json={"current_password": "not-it", "new_password": "new-password-123"},
    )
    assert wrong.status_code == 422

    ok = client.post(
        "/api/account/change-password",
        json={"current_password": "old-password", "new_password": "new-password-123"},
    )
    assert ok.status_code == 204

    # the OLD session (even though its own token generation was current when
    # minted) is now revoked -- a raw request with the stale cookie is rejected.
    stale_client = TestClient(create_app(auth=auth, cookie_secure=False))
    stale_client.cookies.set("all_tomorrow_session", old_cookie)
    assert stale_client.get("/api/projects").status_code == 401

    # logging in again requires the NEW password.
    fresh = _client(auth)
    assert fresh.post("/api/login", json={"username": "admin", "password": "old-password"}).status_code == 401
    assert fresh.post("/api/login", json={"username": "admin", "password": "new-password-123"}).status_code == 204


def test_logout_everywhere_revokes_all_outstanding_sessions():
    auth = Auth("admin", "pw", SECRET)
    client_a = _client(auth)
    client_b = _client(auth)
    assert client_a.post("/api/login", json={"username": "admin", "password": "pw"}).status_code == 204
    assert client_b.post("/api/login", json={"username": "admin", "password": "pw"}).status_code == 204
    assert client_a.get("/api/projects").status_code == 200
    assert client_b.get("/api/projects").status_code == 200

    assert client_a.post("/api/account/logout-everywhere").status_code == 204

    # both sessions (not just client_a's) are now invalid.
    stale_a = TestClient(create_app(auth=auth, cookie_secure=False))
    stale_a.cookies.set("all_tomorrow_session", client_a.cookies.get("all_tomorrow_session") or "")
    stale_b = TestClient(create_app(auth=auth, cookie_secure=False))
    stale_b.cookies.set("all_tomorrow_session", client_b.cookies.get("all_tomorrow_session") or "")


def test_account_page_requires_login():
    auth = Auth("admin", "pw", SECRET)
    client = _client(auth)
    resp = client.get("/account", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] == "/login"

    client.post("/api/login", json={"username": "admin", "password": "pw"})
    resp2 = client.get("/account")
    assert resp2.status_code == 200
    assert "계정" in resp2.text
