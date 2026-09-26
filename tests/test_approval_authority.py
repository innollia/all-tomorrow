"""04E — Laptop Approval Authority threat model (12 negative scenarios + happy path)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from all_tomorrow.approval import (
    ApprovalDenied,
    ApprovalState,
    LaptopApprovalAuthority,
    ProtectedChangeRequest,
    ReauthContext,
    hash_material,
)
from all_tomorrow.domain.ids import utc_now

WRITE_TOKEN = "authority-write-secret-token-0123456789"
ACCOUNT = "owner@laptop"


def _req(candidate="cand-v1") -> ProtectedChangeRequest:
    return ProtectedChangeRequest(
        proposal_id="prop-1",
        proposal_revision=1,
        candidate_artifact_hash=hash_material(candidate),
        baseline_artifact_hash=hash_material("baseline"),
        requested_authority_change_hash=hash_material("expand:deploy"),
        evaluation_refs=("eval:1",),
    )


def _reauth(verified=True, origin_ok=True, csrf_ok=True, account=ACCOUNT) -> ReauthContext:
    return ReauthContext(
        account_id=account, verified=verified, origin_ok=origin_ok,
        csrf_ok=csrf_ok, reauthenticated_at=utc_now(),
    )


def _authority(online=True, ttl=300) -> LaptopApprovalAuthority:
    return LaptopApprovalAuthority(
        authority_write_token=WRITE_TOKEN, online=online, approval_ttl_seconds=ttl
    )


def _apply(_req) -> str:
    return "applied:ok"


# Happy path — fresh reauth + exact unexpired approval applies.
def test_happy_path_applies() -> None:
    a = _authority()
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    result = a.apply_protected_change(rec.approval_id, _req(), _reauth(), _apply)
    assert result == "applied:ok"
    assert a._records[rec.approval_id].state == ApprovalState.CONSUMED


# 1. AWS credential (no authority write token) cannot approve.
def test_aws_cannot_approve_without_authority_token() -> None:
    a = _authority()
    with pytest.raises(ApprovalDenied) as e:
        a.approve(_req(), _reauth(), authority_write_token="aws-ordinary-cred", account_id=ACCOUNT)
    assert e.value.reason == "authority_write_denied"


# 2. Forged approval row (unknown approval_id) denies.
def test_forged_approval_row_denies() -> None:
    a = _authority()
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change("forged-id", _req(), _reauth(), _apply)
    assert e.value.reason == "unknown_approval"


# 3. Nonce replay: a consumed approval cannot be reused.
def test_nonce_replay_denies() -> None:
    a = _authority()
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    a.apply_protected_change(rec.approval_id, _req(), _reauth(), _apply)
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change(rec.approval_id, _req(), _reauth(), _apply)
    assert e.value.reason in ("approval_not_issued", "nonce_replay")


# 4. Expired approval denies.
def test_expired_approval_denies() -> None:
    a = _authority(ttl=0)
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change(rec.approval_id, _req(), _reauth(), _apply)
    assert e.value.reason == "expired"


# 5. Candidate artifact substitution (different hash) denies.
def test_artifact_substitution_denies() -> None:
    a = _authority()
    rec = a.approve(_req("cand-v1"), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change(rec.approval_id, _req("cand-v2-swapped"), _reauth(), _apply)
    assert e.value.reason == "binding_mismatch"


# 6. Post-approval proposal mutation (revision bump) denies.
def test_post_approval_mutation_denies() -> None:
    a = _authority()
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    mutated = ProtectedChangeRequest(
        proposal_id="prop-1", proposal_revision=2,  # bumped after approval
        candidate_artifact_hash=hash_material("cand-v1"),
        baseline_artifact_hash=hash_material("baseline"),
        requested_authority_change_hash=hash_material("expand:deploy"),
    )
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change(rec.approval_id, mutated, _reauth(), _apply)
    assert e.value.reason == "binding_mismatch"


# 7. Stolen session without fresh reauth denies.
def test_stolen_session_no_reauth_denies() -> None:
    a = _authority()
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change(rec.approval_id, _req(), _reauth(verified=False), _apply)
    assert e.value.reason == "reauth_required"


# 8. CSRF / cross-origin denies.
def test_csrf_cross_origin_denies() -> None:
    a = _authority()
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change(rec.approval_id, _req(), _reauth(origin_ok=False), _apply)
    assert e.value.reason == "csrf_or_origin"


# 9. Wrong account denies.
def test_wrong_account_denies() -> None:
    a = _authority()
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change(rec.approval_id, _req(), _reauth(account="attacker@x"), _apply)
    assert e.value.reason == "account_mismatch"


# 10. Laptop offline denies (durable wait, no apply).
def test_offline_denies() -> None:
    a = _authority(online=False)
    # approve while records exist, but apply path is offline.
    a2 = _authority(online=True)
    rec = a2.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    a._records[rec.approval_id] = a2._records[rec.approval_id]
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change(rec.approval_id, _req(), _reauth(), _apply)
    assert e.value.reason == "offline"


# 11. Revoked approval cannot apply.
def test_revoked_approval_denies() -> None:
    a = _authority()
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    a.revoke(rec.approval_id)
    with pytest.raises(ApprovalDenied) as e:
        a.apply_protected_change(rec.approval_id, _req(), _reauth(), _apply)
    assert e.value.reason == "approval_not_issued"


# 12. Consumed approval reuse denies (double-apply).
def test_consumed_reuse_denies() -> None:
    a = _authority()
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    a.apply_protected_change(rec.approval_id, _req(), _reauth(), _apply)
    with pytest.raises(ApprovalDenied):
        a.apply_protected_change(rec.approval_id, _req(), _reauth(), _apply)


# Audit records decisions without storing secrets.
def test_audit_records_no_secrets() -> None:
    a = _authority()
    rec = a.approve(_req(), _reauth(), authority_write_token=WRITE_TOKEN, account_id=ACCOUNT)
    a.apply_protected_change(rec.approval_id, _req(), _reauth(), _apply)
    trail = a.audit_trail()
    assert any(e.decision == "applied" for e in trail)
    import dataclasses
    blob = repr([dataclasses.asdict(e) for e in trail])
    assert WRITE_TOKEN not in blob
    assert rec.nonce not in blob  # nonce value not stored in audit, only its state
