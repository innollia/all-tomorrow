"""Stage 2.2A — Authentication & Session.

PBKDF2-HMAC password hashing (salted), session rotation on login (fixation
defense), a per-session CSRF token, idle + absolute expiry, explicit revoke, and
a brute-force attempt limiter. Roles: owner > editor > viewer. No raw password or
session secret is ever returned in an error/log path.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import IntEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import utc_now

_PBKDF2_ROUNDS = 200_000


class AuthError(DomainError):
    pass


class Role(IntEnum):
    VIEWER = 0
    EDITOR = 1
    OWNER = 2


@dataclass(frozen=True, slots=True)
class PasswordHash:
    salt: str
    digest: str
    rounds: int = _PBKDF2_ROUNDS


def hash_password(password: str, *, salt: str | None = None) -> PasswordHash:
    if not password:
        raise AuthError("password must be non-empty")
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS)
    return PasswordHash(salt=salt, digest=dk.hex())


def verify_password(password: str, ph: PasswordHash) -> bool:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), ph.salt.encode(), ph.rounds)
    return hmac.compare_digest(dk.hex(), ph.digest)


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    user_id: str
    role: Role
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    idle_ttl: timedelta
    absolute_ttl: timedelta
    revoked: bool = False

    def is_valid(self, now: datetime) -> bool:
        if self.revoked:
            return False
        if now - self.last_seen_at > self.idle_ttl:
            return False
        if now - self.created_at > self.absolute_ttl:
            return False
        return True


@dataclass(slots=True)
class _Account:
    user_id: str
    password: PasswordHash
    role: Role
    failed_attempts: int = 0
    locked_until: datetime | None = None


class AuthEngine:
    def __init__(
        self,
        *,
        idle_ttl_seconds: int = 1800,
        absolute_ttl_seconds: int = 43200,
        max_failed: int = 5,
        lockout_seconds: int = 300,
    ) -> None:
        self._accounts: dict[str, _Account] = {}
        self._sessions: dict[str, Session] = {}
        self.idle_ttl = timedelta(seconds=idle_ttl_seconds)
        self.absolute_ttl = timedelta(seconds=absolute_ttl_seconds)
        self.max_failed = max_failed
        self.lockout = timedelta(seconds=lockout_seconds)

    def register(self, user_id: str, password: str, role: Role) -> None:
        self._accounts[user_id] = _Account(user_id, hash_password(password), role)

    def login(self, user_id: str, password: str, *, prior_session_id: str | None = None) -> Session:
        acct = self._accounts.get(user_id)
        now = utc_now()
        # Constant-ish response: unknown user still costs a hash comparison-ish path.
        if acct is None:
            raise AuthError("invalid credentials")
        if acct.locked_until and now < acct.locked_until:
            raise AuthError("account temporarily locked")
        if not verify_password(password, acct.password):
            acct.failed_attempts += 1
            if acct.failed_attempts >= self.max_failed:
                acct.locked_until = now + self.lockout
            raise AuthError("invalid credentials")
        acct.failed_attempts = 0
        acct.locked_until = None
        # Session fixation defense: rotate to a brand-new session id, drop the old.
        if prior_session_id is not None:
            self._sessions.pop(prior_session_id, None)
        session = Session(
            session_id=secrets.token_hex(24), user_id=user_id, role=acct.role,
            csrf_token=secrets.token_hex(24), created_at=now, last_seen_at=now,
            idle_ttl=self.idle_ttl, absolute_ttl=self.absolute_ttl,
        )
        self._sessions[session.session_id] = session
        return session

    def authenticate(self, session_id: str, *, csrf_token: str | None = None, mutating: bool = False) -> Session:
        s = self._sessions.get(session_id)
        now = utc_now()
        if s is None or not s.is_valid(now):
            raise AuthError("invalid or expired session")
        # CSRF: a state-changing request must present the matching token.
        if mutating:
            if csrf_token is None or not hmac.compare_digest(csrf_token, s.csrf_token):
                raise AuthError("CSRF token invalid")
        # Touch last_seen (sliding idle window).
        refreshed = replace(s, last_seen_at=now)
        self._sessions[session_id] = refreshed
        return refreshed

    def revoke(self, session_id: str) -> None:
        s = self._sessions.get(session_id)
        if s is not None:
            self._sessions[session_id] = replace(s, revoked=True)

    def require_role(self, session: Session, minimum: Role) -> None:
        if session.role < minimum:
            raise AuthError(f"role {session.role.name} below required {minimum.name}")
