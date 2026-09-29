"""Device agent domain — registered device identity and lease state.

A Device is a physically separate machine (Tailscale-reachable) that pulls Work
from the central server and executes it with its own local worker CLIs. Device
identity/lease is intentionally separate from the Goal/Work/Run semantic core:
a Device never owns a Work directly (that would violate the Work
execution_ref-forbidden invariant in ``domain.state``) — it owns a *lease* on
one Work, tracked here, while the Work/Run's own status lives in the normal
Goal/Work/Run store.

Only the token DIGEST is ever stored — the raw device token is returned once,
at registration/rotation time, and never persisted or logged in plain text.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id, utc_now

HEARTBEAT_INTERVAL_SECONDS = 30
OFFLINE_AFTER_SECONDS = 90
DEFAULT_LEASE_TTL_SECONDS = 120


class DeviceError(DomainError):
    pass


class DeviceTokenInvalidError(DeviceError):
    pass


class DeviceRevokedError(DeviceError):
    pass


class LeaseConflictError(DeviceError):
    """Raised when a Work is already leased to a different device."""


class DeviceStatus(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"       # heartbeat missed past OFFLINE_AFTER_SECONDS
    REVOKED = "REVOKED"       # token revoked from the web UI ("기기 끊기")


def new_device_id() -> str:
    return new_id("dev")


def new_device_token() -> str:
    """A high-entropy bearer token. Returned to the caller exactly once."""
    return secrets.token_urlsafe(32)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    device_id: str
    name: str
    owner_user_id: str
    token_digest: str
    capabilities: frozenset[str] = frozenset()
    max_concurrent: int = 1
    status: DeviceStatus = DeviceStatus.OFFLINE
    registered_at: datetime = field(default_factory=utc_now)
    last_heartbeat_at: datetime | None = None
    revoked_at: datetime | None = None
    revision: int = 1

    def is_revoked(self) -> bool:
        return self.status is DeviceStatus.REVOKED

    def effective_status(self, now: datetime | None = None) -> DeviceStatus:
        """Live status derived from heartbeat freshness (S: 90s offline rule).

        A revoked device stays REVOKED regardless of heartbeat recency — revoke
        is a terminal, one-way action from the web UI ("기기 끊기").
        """
        if self.status is DeviceStatus.REVOKED:
            return DeviceStatus.REVOKED
        now = now or utc_now()
        if self.last_heartbeat_at is None:
            return DeviceStatus.OFFLINE
        if (now - self.last_heartbeat_at) > timedelta(seconds=OFFLINE_AFTER_SECONDS):
            return DeviceStatus.OFFLINE
        return DeviceStatus.ONLINE

    def verify_token(self, token: str) -> None:
        if self.is_revoked():
            raise DeviceRevokedError(f"device {self.device_id} token has been revoked")
        import hmac

        if not hmac.compare_digest(hash_device_token(token), self.token_digest):
            raise DeviceTokenInvalidError("invalid device token")


class LeaseStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"       # heartbeat/renew missed; Work returned to pending
    RELEASED = "RELEASED"     # device explicitly gave it back (rare)


@dataclass(frozen=True, slots=True)
class DeviceLeaseRecord:
    """One device's claim on one Work.

    Device identity/lease lives here, never on the WorkRecord itself — see
    module docstring. ``ambiguous_side_effect`` marks a Work whose lease expired
    mid-execution without a completion report: such Work is NOT auto-reassigned
    (cross_system.py's AMBIGUOUS rule — a side-effecting task must not run
    twice blindly) and instead surfaces for a human decision.
    """
    lease_id: str
    work_id: str
    device_id: str
    status: LeaseStatus = LeaseStatus.ACTIVE
    leased_at: datetime = field(default_factory=utc_now)
    expires_at: datetime = field(default_factory=lambda: utc_now() + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS))
    completed_at: datetime | None = None
    ambiguous_side_effect: bool = False
    revision: int = 1

    def is_active(self, now: datetime | None = None) -> bool:
        if self.status is not LeaseStatus.ACTIVE:
            return False
        now = now or utc_now()
        return now <= self.expires_at

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or utc_now()
        return self.status is LeaseStatus.ACTIVE and now > self.expires_at
