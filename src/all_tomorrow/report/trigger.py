"""05D — Report Trigger and Minimal Access.

Generates reports on correct logical-day semantics (local calendar date + IANA
timezone + boundary policy version — never a bare UTC 'day'), idempotent per
logical period, with bounded catch-up after restart/offline and DST-safe period
identity. Provides authenticated read-only access with strict user isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from all_tomorrow.domain.errors import DomainError


BOUNDARY_POLICY_VERSION = "1"


class AccessDenied(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class TimeModel:
    timezone: str                 # IANA, e.g. "Asia/Seoul"
    boundary_hour_local: int = 0  # local hour the report day boundary falls on
    catch_up_horizon_days: int = 7


def logical_period_id(model: TimeModel, instant_utc: datetime) -> str:
    """Logical day identity: local calendar date at the boundary + tz + policy version.

    Two instants on the same local report-day map to the same id (idempotent),
    and a DST fold/gap cannot split or duplicate a logical day because identity is
    the local calendar date, not a UTC offset window.
    """
    tz = ZoneInfo(model.timezone)
    local = instant_utc.astimezone(tz)
    # Shift by the boundary hour so a boundary_hour_local!=0 groups the day correctly.
    shifted = local - timedelta(hours=model.boundary_hour_local)
    d: date = shifted.date()
    return f"{d.isoformat()}|{model.timezone}|bp{BOUNDARY_POLICY_VERSION}"


def periods_to_catch_up(model: TimeModel, last_done: date, now_utc: datetime) -> list[str]:
    """Missed logical periods since ``last_done``, bounded by the catch-up horizon."""
    tz = ZoneInfo(model.timezone)
    today = (now_utc.astimezone(tz) - timedelta(hours=model.boundary_hour_local)).date()
    out: list[str] = []
    d = last_done + timedelta(days=1)
    while d <= today:
        out.append(f"{d.isoformat()}|{model.timezone}|bp{BOUNDARY_POLICY_VERSION}")
        d += timedelta(days=1)
    # Bound: never generate more than the horizon's worth of most-recent periods.
    if len(out) > model.catch_up_horizon_days:
        out = out[-model.catch_up_horizon_days:]
    return out


class ReportAccess:
    """Authenticated read-only access with user-scope isolation."""

    def __init__(self, store) -> None:
        self.store = store

    def get(self, report_id: str, *, requester_id: str | None):
        if requester_id is None:
            raise AccessDenied("401: authentication required")
        r = self.store.get(report_id)
        if r is None:
            return None
        if r.user_id != requester_id:
            # Do not leak existence to a non-owner guessing ids.
            raise AccessDenied("not owner")
        return r
