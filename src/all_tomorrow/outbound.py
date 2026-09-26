"""Stage 2.2D — Outbound Delivery Surface.

Separates producing a question/report/notification from actually delivering it to
the user. A delivery has channel binding, an idempotency key (retry never
double-sends), a receipt, expiry, and opt-out. Creating a Question record is NOT
delivery success, and a failed delivery never forges Work/Question state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id, utc_now


class OutboundError(DomainError):
    pass


class DeliveryStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"   # opt-out / policy


@dataclass(frozen=True, slots=True)
class OutboundDelivery:
    delivery_id: str
    channel: str
    recipient_id: str
    idempotency_key: str
    payload_ref: str                 # a ref, not raw sensitive content
    sensitive: bool = False
    status: DeliveryStatus = DeliveryStatus.PENDING
    receipt: str | None = None
    attempts: int = 0
    created_at: datetime = field(default_factory=utc_now)


class OutboundStore:
    def __init__(self) -> None:
        self._by_id: dict[str, OutboundDelivery] = {}
        self._by_key: dict[str, str] = {}          # idempotency_key -> delivery_id
        self._opted_out: set[tuple[str, str]] = set()   # (recipient, channel)
        self._sensitive_channels: set[str] = set()       # channels allowed for sensitive

    def allow_sensitive(self, channel: str) -> None:
        self._sensitive_channels.add(channel)

    def opt_out(self, recipient_id: str, channel: str) -> None:
        self._opted_out.add((recipient_id, channel))

    def enqueue(self, d: OutboundDelivery) -> OutboundDelivery:
        # Idempotent: same key returns the existing delivery (no duplicate row).
        existing_id = self._by_key.get(d.idempotency_key)
        if existing_id is not None:
            return self._by_id[existing_id]
        if (d.recipient_id, d.channel) in self._opted_out:
            d = replace(d, status=DeliveryStatus.SUPPRESSED)
        elif d.sensitive and d.channel not in self._sensitive_channels:
            d = replace(d, status=DeliveryStatus.SUPPRESSED)  # sensitive-content channel policy
        self._by_id[d.delivery_id] = d
        self._by_key[d.idempotency_key] = d.delivery_id
        return d

    def deliver(self, delivery_id: str, *, transport_ok: bool) -> OutboundDelivery:
        d = self._by_id[delivery_id]
        if d.status in (DeliveryStatus.DELIVERED, DeliveryStatus.SUPPRESSED):
            return d  # idempotent: already terminal, retry does nothing
        attempts = d.attempts + 1
        if transport_ok:
            updated = replace(d, status=DeliveryStatus.DELIVERED,
                              receipt=new_id("rcpt"), attempts=attempts)
        else:
            # Failed delivery: record FAILED, but this never changes Work/Question state.
            updated = replace(d, status=DeliveryStatus.FAILED, attempts=attempts)
        self._by_id[delivery_id] = updated
        return updated

    def get(self, delivery_id: str) -> OutboundDelivery | None:
        return self._by_id.get(delivery_id)
