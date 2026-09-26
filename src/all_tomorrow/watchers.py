"""Stage 3.2B — Webhook / Polling / Condition Watchers.

Webhooks verify an HMAC signature and reject replays (nonce + timestamp window)
and oversized/wrong-type bodies. Watchers keep a durable cursor, distinguish
edge (fire on transition) from level (fire while true) semantics, and treat a
poll failure as UNKNOWN — never as "condition false".
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import utc_now


class WebhookError(DomainError):
    pass


class WatchMode(StrEnum):
    EDGE = "EDGE"     # fire only on false→true transition
    LEVEL = "LEVEL"   # fire each observation while true


@dataclass(slots=True)
class WebhookReceiver:
    secret: str
    max_body_bytes: int = 65536
    replay_window: timedelta = timedelta(minutes=5)
    _seen_nonces: set[str] = field(default_factory=set)

    def verify_and_accept(self, *, body: bytes, signature: str, nonce: str,
                          timestamp: datetime, content_type: str = "application/json",
                          now: datetime | None = None) -> bool:
        now = now or utc_now()
        if len(body) > self.max_body_bytes:
            raise WebhookError("body too large")
        if content_type != "application/json":
            raise WebhookError("unsupported content type")
        expected = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise WebhookError("bad signature")           # S3-32B-02 unauthenticated reject
        if abs((now - timestamp).total_seconds()) > self.replay_window.total_seconds():
            raise WebhookError("timestamp outside replay window")
        if nonce in self._seen_nonces:
            return False                                   # S3-32B-01 replay → duplicate ignored
        self._seen_nonces.add(nonce)
        return True


@dataclass(slots=True)
class ConditionWatcher:
    mode: WatchMode
    cursor: str | None = None            # durable observation cursor (S3-32B-03)
    _last_true: bool = False

    def observe(self, *, condition: bool | None, cursor: str) -> bool:
        """Return True if this observation should FIRE.

        ``condition=None`` means the poll failed → UNKNOWN, never treated as false
        (S3-32B). The cursor advances only on a definite observation.
        """
        if condition is None:
            return False   # poll failure: do not fire, do not flip state, keep prior cursor
        self.cursor = cursor
        if self.mode == WatchMode.EDGE:
            fire = condition and not self._last_true    # only on transition (no storm)
            self._last_true = condition
            return fire
        # LEVEL: fire each time it is true.
        self._last_true = condition
        return condition
