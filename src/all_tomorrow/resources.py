"""Stage 2.4A — Resource Registry.

Registers usable resources (tool/worker/model routes) by capability, authority,
health freshness, cost/quota and version — never by a provider-name branch.
Stale health is treated as unavailable; unknown quota/cost is handled
conservatively (treated as exhausted/expensive, never as free/unlimited).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from all_tomorrow.domain.ids import utc_now


class ResourceKind(StrEnum):
    TOOL = "TOOL"
    WORKER = "WORKER"
    MODEL = "MODEL"


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    resource_id: str
    kind: ResourceKind
    capabilities: frozenset[str]
    authority_scope: str = "default"
    version: str = "1"
    health_status: str = "unknown"          # healthy / degraded / down / unknown
    health_checked_at: datetime | None = None
    remaining_quota: int | None = None       # None = UNKNOWN → conservative
    cost_per_unit: float | None = None        # None = UNKNOWN → conservative

    def is_healthy(self, now: datetime, freshness: timedelta) -> bool:
        if self.health_status != "healthy":
            return False
        if self.health_checked_at is None:
            return False
        return (now - self.health_checked_at) <= freshness   # stale → not healthy

    def has_quota(self) -> bool:
        # Unknown quota is treated conservatively as NOT available.
        if self.remaining_quota is None:
            return False
        return self.remaining_quota > 0


class ResourceRegistry:
    def __init__(self, *, health_freshness_seconds: int = 60) -> None:
        self._resources: dict[str, ResourceRecord] = {}
        self.freshness = timedelta(seconds=health_freshness_seconds)

    def register(self, r: ResourceRecord) -> None:
        self._resources[r.resource_id] = r

    def get(self, resource_id: str) -> ResourceRecord | None:
        return self._resources.get(resource_id)

    def available(
        self,
        *,
        required_capabilities: frozenset[str],
        authority_scope: str = "default",
        require_quota: bool = True,
        now: datetime | None = None,
    ) -> list[ResourceRecord]:
        now = now or utc_now()
        out: list[ResourceRecord] = []
        for r in self._resources.values():
            if not required_capabilities <= r.capabilities:
                continue
            if r.authority_scope != authority_scope:
                continue
            if not r.is_healthy(now, self.freshness):
                continue
            if require_quota and not r.has_quota():
                continue
            out.append(r)
        return out
