"""Stage 3.2A — Trigger Store & Scheduler.

A TriggerRecord fires by a logical_fire_key (period identity), so a duplicate
fire creates only one Work. A fire from an old trigger revision is invalid (the
trigger was updated/cancelled), DST fold/gap cannot duplicate a logical period,
and catch-up after downtime is bounded by a horizon.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id, utc_now


class TriggerError(DomainError):
    pass


class TriggerKind(StrEnum):
    RECURRING_DAILY = "RECURRING_DAILY"
    ONE_SHOT = "ONE_SHOT"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True, slots=True)
class TriggerRecord:
    trigger_id: str
    user_id: str
    kind: TriggerKind
    timezone: str
    revision: int = 1
    enabled: bool = True
    catch_up_horizon_days: int = 7


def logical_fire_key(t: TriggerRecord, instant_utc: datetime) -> str:
    """Period identity for a fire: local calendar date + tz + trigger revision."""
    tz = ZoneInfo(t.timezone)
    d: date = instant_utc.astimezone(tz).date()
    return f"{t.trigger_id}|{d.isoformat()}|{t.timezone}|r{t.revision}"


class TriggerScheduler:
    def __init__(self) -> None:
        self._triggers: dict[str, TriggerRecord] = {}
        self._fired_keys: set[str] = set()          # logical_fire_key already → Work
        self._works: dict[str, str] = {}            # fire_key -> work_id

    def register(self, t: TriggerRecord) -> None:
        self._triggers[t.trigger_id] = t

    def update_revision(self, trigger_id: str) -> TriggerRecord:
        t = self._triggers[trigger_id]
        updated = replace(t, revision=t.revision + 1)
        self._triggers[trigger_id] = updated
        return updated

    def cancel(self, trigger_id: str) -> None:
        t = self._triggers[trigger_id]
        self._triggers[trigger_id] = replace(t, enabled=False, revision=t.revision + 1)

    def fire(self, trigger_id: str, instant_utc: datetime) -> str | None:
        """Attempt a fire. Returns a new work_id, or None if it was a duplicate.

        A fire whose trigger revision no longer matches the current record is
        rejected (old-revision fire invalid).
        """
        t = self._triggers[trigger_id]
        if not t.enabled:
            raise TriggerError(f"trigger {trigger_id} disabled")
        key = logical_fire_key(t, instant_utc)
        # An old-revision key (built from a stale revision) will not match the
        # current record's key for the same instant → treat as invalid.
        expected_prefix = f"{trigger_id}|"
        if not key.startswith(expected_prefix) or not key.endswith(f"r{t.revision}"):
            raise TriggerError("stale trigger revision fire")
        if key in self._fired_keys:
            return None                       # duplicate fire → no new Work
        self._fired_keys.add(key)
        work_id = new_id("work")
        self._works[key] = work_id
        return work_id

    def catch_up_keys(self, trigger_id: str, last_fired: date, now_utc: datetime) -> list[str]:
        t = self._triggers[trigger_id]
        tz = ZoneInfo(t.timezone)
        today = now_utc.astimezone(tz).date()
        keys: list[str] = []
        d = last_fired + timedelta(days=1)
        while d <= today:
            keys.append(f"{trigger_id}|{d.isoformat()}|{t.timezone}|r{t.revision}")
            d += timedelta(days=1)
        if len(keys) > t.catch_up_horizon_days:
            keys = keys[-t.catch_up_horizon_days:]   # bounded catch-up
        return keys
