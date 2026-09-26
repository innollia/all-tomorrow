"""Stage 2.2A — Authentication & Session verification (S2-22A-01..04)."""

from __future__ import annotations

import pytest

from all_tomorrow.auth import AuthEngine, AuthError, Role, hash_password, verify_password


def _engine() -> AuthEngine:
    e = AuthEngine(idle_ttl_seconds=1800, absolute_ttl_seconds=43200, max_failed=3, lockout_seconds=300)
    e.register("owner", "correct horse battery", Role.OWNER)
    e.register("viewer", "viewer-pass", Role.VIEWER)
    return e


def test_password_kdf_roundtrip_and_wrong() -> None:
    ph = hash_password("s3cret")
    assert verify_password("s3cret", ph)
    assert not verify_password("wrong", ph)
    assert ph.digest != "s3cret" and len(ph.salt) == 32


# S2-22A-01: session fixation defended — login rotates the session id.
def test_22a_01_fixation_rotation() -> None:
    e = _engine()
    s1 = e.login("owner", "correct horse battery")
    s2 = e.login("owner", "correct horse battery", prior_session_id=s1.session_id)
    assert s2.session_id != s1.session_id
    # old session no longer authenticates (dropped on rotation)
    with pytest.raises(AuthError):
        e.authenticate(s1.session_id)


# S2-22A-01: CSRF token required for mutating requests.
def test_22a_01_csrf_required_for_mutation() -> None:
    e = _engine()
    s = e.login("owner", "correct horse battery")
    # read is fine without csrf
    e.authenticate(s.session_id, mutating=False)
    # mutation without/with-wrong csrf fails
    with pytest.raises(AuthError):
        e.authenticate(s.session_id, mutating=True)
    with pytest.raises(AuthError):
        e.authenticate(s.session_id, csrf_token="wrong", mutating=True)
    # correct csrf passes
    assert e.authenticate(s.session_id, csrf_token=s.csrf_token, mutating=True)


# S2-22A-02: logout/revoke immediately invalidates.
def test_22a_02_revoke_immediate() -> None:
    e = _engine()
    s = e.login("owner", "correct horse battery")
    e.revoke(s.session_id)
    with pytest.raises(AuthError):
        e.authenticate(s.session_id)


# S2-22A-03: role enforcement owner/editor/viewer.
def test_22a_03_role_enforcement() -> None:
    e = _engine()
    viewer = e.login("viewer", "viewer-pass")
    with pytest.raises(AuthError):
        e.require_role(viewer, Role.EDITOR)   # viewer cannot edit
    owner = e.login("owner", "correct horse battery")
    e.require_role(owner, Role.OWNER)          # owner ok
    e.require_role(owner, Role.VIEWER)         # owner exceeds viewer


# S2-22A-04: no raw password/session secret leaked in error messages.
def test_22a_04_no_secret_in_errors() -> None:
    e = _engine()
    try:
        e.login("owner", "the-wrong-password-xyz")
    except AuthError as ex:
        assert "the-wrong-password-xyz" not in str(ex)


# brute-force lockout after max_failed.
def test_22a_brute_force_lockout() -> None:
    e = _engine()
    for _ in range(3):
        with pytest.raises(AuthError):
            e.login("owner", "bad")
    # even the correct password is locked out now
    with pytest.raises(AuthError, match="locked"):
        e.login("owner", "correct horse battery")
