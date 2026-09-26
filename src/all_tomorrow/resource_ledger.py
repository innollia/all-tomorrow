"""Stage 3.3B — Resource Ledger.

Tracks a SHARED resource's capacity, outstanding reservations, and actual usage
(distinct from the Stage-1 per-lineage budget: that bounds one autonomous
lineage; this bounds a shared resource across all consumers). Reserve/release/
reconcile are atomic under a lock; concurrent reservations never exceed the
ceiling; a failed op still consumes any actual cost incurred; expired
reservations are released; unknown quota is treated conservatively.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id, utc_now


class LedgerError(DomainError):
    pass


class CapacityExceededError(LedgerError):
    pass


@dataclass(slots=True)
class _Reservation:
    reservation_id: str
    units: int
    expires_at: datetime


class ResourceLedger:
    """One shared resource's capacity ledger."""

    def __init__(self, resource_id: str, capacity: int | None) -> None:
        # capacity None = UNKNOWN → conservative (nothing may be reserved).
        self.resource_id = resource_id
        self.capacity = capacity
        self._lock = asyncio.Lock()
        self._reservations: dict[str, _Reservation] = {}
        self._actual_usage: int = 0

    def _reserved_units(self) -> int:
        return sum(r.units for r in self._reservations.values())

    async def reserve(self, units: int, *, ttl_seconds: int = 300) -> str:
        async with self._lock:
            if self.capacity is None:
                raise CapacityExceededError(f"{self.resource_id}: capacity UNKNOWN → conservative deny")
            self._expire_locked(utc_now())
            if self._reserved_units() + units > self.capacity:
                raise CapacityExceededError(f"{self.resource_id}: reservation exceeds capacity")
            rid = new_id("resv")
            self._reservations[rid] = _Reservation(rid, units, utc_now() + timedelta(seconds=ttl_seconds))
            return rid

    async def release(self, reservation_id: str) -> None:
        async with self._lock:
            self._reservations.pop(reservation_id, None)

    async def consume_actual(self, units: int | None, *, failed: bool = False) -> None:
        """Record actual usage. A failed op that still incurred cost consumes too.

        Unknown actual usage is not settled as 0 — it raises so the caller keeps it
        UNKNOWN rather than silently under-counting.
        """
        async with self._lock:
            if units is None:
                raise LedgerError("unknown actual usage must not be settled as 0")
            self._actual_usage += units  # `failed` is recorded by the caller's event; cost still counts

    async def reconcile(self) -> dict:
        """Release expired reservations; return a snapshot."""
        async with self._lock:
            self._expire_locked(utc_now())
            return {
                "resource_id": self.resource_id,
                "capacity": self.capacity,
                "reserved": self._reserved_units(),
                "actual_usage": self._actual_usage,
                "outstanding": len(self._reservations),
            }

    def _expire_locked(self, now: datetime) -> None:
        for rid in [r.reservation_id for r in self._reservations.values() if r.expires_at <= now]:
            self._reservations.pop(rid, None)
