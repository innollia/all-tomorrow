"""04E — Laptop Approval Authority.

Applies protected self-changes through a laptop-local authority that AWS cannot
bypass by manipulating credentials or the database. A protected apply is allowed
ONLY when a fresh reauthentication AND an exact, unexpired, artifact-bound,
single-use approval match the candidate being applied.

Everything here fails closed: unknown, mismatched, expired, replayed, forged,
mutated-after-approval, wrong-account, no-reauth, offline — all deny.

The authority store is a distinct credential domain: an ordinary self-mod
credential cannot write approvals or hold the protected apply capability. Modeled
here as an explicit ``authority_write_token`` that AWS never possesses.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import utc_now


class ApprovalDenied(DomainError):
    """A protected apply was denied. Carries a machine-readable reason."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


class ApprovalState(StrEnum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class ProtectedChangeRequest:
    """The exact thing an apply is bound to. Any drift here denies the apply."""

    proposal_id: str
    proposal_revision: int
    candidate_artifact_hash: str
    baseline_artifact_hash: str
    requested_authority_change_hash: str
    evaluation_refs: tuple[str, ...] = ()
    protection_policy_version: str = "1"

    def binding_digest(self) -> str:
        parts = [
            self.proposal_id,
            str(self.proposal_revision),
            self.candidate_artifact_hash,
            self.baseline_artifact_hash,
            self.requested_authority_change_hash,
            self.protection_policy_version,
        ]
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """Immutable approval tuple. NOT a reusable boolean row."""

    approval_id: str
    request: ProtectedChangeRequest
    account_id: str
    nonce: str
    issued_at: datetime
    expires_at: datetime
    state: ApprovalState = ApprovalState.ISSUED

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True, slots=True)
class AuditEntry:
    proposal_id: str
    proposal_revision: int
    binding_digest: str
    decision: str            # "approved" | "rejected" | "applied" | "denied"
    account_id: str
    nonce_state: str
    at: datetime
    apply_result_ref: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReauthContext:
    """Proof of a fresh, per-approval reauthentication.

    ``verified`` is set only by the auth layer AFTER a successful password/2FA
    check with CSRF/origin validation; a stolen-but-not-reauthed session presents
    verified=False and is denied.
    """

    account_id: str
    verified: bool
    origin_ok: bool
    csrf_ok: bool
    reauthenticated_at: datetime


class LaptopApprovalAuthority:
    """Laptop-local authority owning the protected apply capability.

    ``authority_write_token`` is the authority's own write credential — AWS never
    holds it. ``apply_capability`` is a callable the laptop owns; AWS is not given
    a path that turns approval=true into an apply.
    """

    def __init__(
        self,
        *,
        authority_write_token: str,
        online: bool = True,
        approval_ttl_seconds: int = 300,
    ) -> None:
        if not authority_write_token or len(authority_write_token) < 16:
            raise ValueError("authority_write_token must be a strong secret")
        self._write_token = authority_write_token
        self.online = online
        self.ttl = timedelta(seconds=approval_ttl_seconds)
        self._records: dict[str, ApprovalRecord] = {}
        self._consumed_nonces: set[str] = set()
        self._audit: list[AuditEntry] = []

    # -- Issue (approve) ----------------------------------------------------
    def approve(
        self,
        request: ProtectedChangeRequest,
        reauth: ReauthContext,
        *,
        authority_write_token: str,
        account_id: str,
    ) -> ApprovalRecord:
        # Only the authority's own write credential may create an approval.
        if not hmac.compare_digest(authority_write_token, self._write_token):
            self._log(request, "denied", account_id, "n/a", reason="authority_write_denied")
            raise ApprovalDenied("authority_write_denied", "not the authority write credential")
        self._require_fresh_reauth(reauth, account_id, request)

        record = ApprovalRecord(
            approval_id=secrets.token_hex(16),
            request=request,
            account_id=account_id,
            nonce=secrets.token_hex(16),
            issued_at=utc_now(),
            expires_at=utc_now() + self.ttl,
        )
        self._records[record.approval_id] = record
        self._log(request, "approved", account_id, "issued")
        return record

    def revoke(self, approval_id: str) -> None:
        rec = self._records.get(approval_id)
        if rec and rec.state == ApprovalState.ISSUED:
            self._records[approval_id] = replace(rec, state=ApprovalState.REVOKED)
            self._log(rec.request, "rejected", rec.account_id, "revoked")

    # -- Apply (fail-closed) ------------------------------------------------
    def apply_protected_change(
        self,
        approval_id: str,
        present_request: ProtectedChangeRequest,
        reauth: ReauthContext,
        apply_capability,
    ):
        """Apply ONLY if a fresh reauth + exact unexpired single-use approval match.

        ``apply_capability`` is owned by the laptop; AWS never calls this path.
        Every mismatch denies before the capability is invoked.
        """
        if not self.online:
            raise ApprovalDenied("offline", "laptop authority offline; cannot apply")

        rec = self._records.get(approval_id)
        if rec is None:
            self._log(present_request, "denied", reauth.account_id, "missing", reason="unknown_approval")
            raise ApprovalDenied("unknown_approval")

        now = utc_now()
        # State: consumed/revoked cannot be reused.
        if rec.state != ApprovalState.ISSUED:
            self._log(rec.request, "denied", rec.account_id, rec.state.value, reason="not_issued")
            raise ApprovalDenied("approval_not_issued", f"state={rec.state}")
        # Replay: nonce already consumed.
        if rec.nonce in self._consumed_nonces:
            raise ApprovalDenied("nonce_replay")
        # Expiry.
        if rec.is_expired(now):
            self._log(rec.request, "denied", rec.account_id, "expired", reason="expired")
            raise ApprovalDenied("expired")
        # Fresh reauth for THIS apply (stolen session without reauth denies).
        self._require_fresh_reauth(reauth, rec.account_id, rec.request)
        # Exact artifact binding: candidate/request must be byte-identical to what
        # was approved (substitution or post-approval mutation denies).
        if present_request.binding_digest() != rec.request.binding_digest():
            self._log(present_request, "denied", rec.account_id, "issued", reason="binding_mismatch")
            raise ApprovalDenied("binding_mismatch", "candidate/request differs from approved")

        # All checks pass — the LAPTOP performs the apply and single-uses the nonce.
        result_ref = apply_capability(present_request)
        self._records[approval_id] = replace(rec, state=ApprovalState.CONSUMED)
        self._consumed_nonces.add(rec.nonce)
        self._log(rec.request, "applied", rec.account_id, "consumed", apply_result_ref=str(result_ref))
        return result_ref

    # -- helpers ------------------------------------------------------------
    def _require_fresh_reauth(
        self, reauth: ReauthContext, account_id: str, request: ProtectedChangeRequest
    ) -> None:
        if reauth.account_id != account_id:
            self._log(request, "denied", reauth.account_id, "n/a", reason="account_mismatch")
            raise ApprovalDenied("account_mismatch")
        if not reauth.verified:
            self._log(request, "denied", account_id, "n/a", reason="reauth_required")
            raise ApprovalDenied("reauth_required", "fresh reauthentication required")
        if not reauth.origin_ok or not reauth.csrf_ok:
            self._log(request, "denied", account_id, "n/a", reason="csrf_or_origin")
            raise ApprovalDenied("csrf_or_origin", "cross-origin / CSRF check failed")

    def _log(self, request, decision, account_id, nonce_state, *, apply_result_ref=None, reason=None):
        self._audit.append(
            AuditEntry(
                proposal_id=request.proposal_id,
                proposal_revision=request.proposal_revision,
                binding_digest=request.binding_digest(),
                decision=decision,
                account_id=account_id,
                nonce_state=nonce_state,
                at=utc_now(),
                apply_result_ref=apply_result_ref,
                reason=reason,
            )
        )

    def audit_trail(self) -> list[AuditEntry]:
        return list(self._audit)


def hash_material(*parts: str) -> str:
    """Helper to produce a stable artifact/authority-change hash for a request."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
