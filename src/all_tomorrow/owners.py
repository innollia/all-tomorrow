"""Stage 3.1A — Owner Adapters & Source Precedence.

Owner-owned facts (calendar, tasks, school records) are read and written through
canonical SourceRefs with recorded provenance. A derived summary never overwrites
owner truth; the highest-precedence source wins on conflict; a cache past its
freshness horizon is reported UNKNOWN / NEED_USER rather than posing as current
truth; and a write requires the authority the owner role grants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import utc_now


class OwnerError(DomainError):
    pass


class AuthorityError(OwnerError):
    pass


class Truthiness(StrEnum):
    CURRENT = "CURRENT"
    STALE_UNKNOWN = "STALE_UNKNOWN"     # cache expired → not current truth
    NEED_USER = "NEED_USER"             # conflict a machine must not resolve


class SourceKind(IntEnum):
    # Higher value = higher precedence.
    DERIVED_SUMMARY = 1                 # never overwrites owner truth
    CACHE = 2
    OWNER_CANONICAL = 3                 # the source of truth


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: str
    kind: SourceKind
    fetched_at: datetime
    freshness: timedelta = timedelta(hours=1)

    def is_fresh(self, now: datetime | None = None) -> bool:
        now = now or utc_now()
        return (now - self.fetched_at) <= self.freshness


@dataclass(frozen=True, slots=True)
class OwnerFact:
    key: str
    value: str
    source: SourceRef


def read_fact(candidates: list[OwnerFact], *, now: datetime | None = None) -> tuple[OwnerFact | None, Truthiness]:
    """Pick the canonical fact by source precedence and report its truthiness."""
    if not candidates:
        return None, Truthiness.NEED_USER
    ranked = sorted(candidates, key=lambda f: f.source.kind, reverse=True)
    best = ranked[0]
    # S3-31A-02: precedence — owner canonical beats cache beats derived summary.
    # S3-31A-03: a stale non-canonical cache is not current truth.
    if best.source.kind == SourceKind.OWNER_CANONICAL:
        return best, Truthiness.CURRENT
    if best.source.is_fresh(now):
        return best, Truthiness.CURRENT
    return best, Truthiness.STALE_UNKNOWN


def write_fact(fact: OwnerFact, *, has_owner_authority: bool) -> OwnerFact:
    """Write to owner truth. Requires authority; a derived summary cannot be the write source."""
    # S3-31A-04: role/authority enforcement.
    if not has_owner_authority:
        raise AuthorityError(f"write to owner fact {fact.key} requires owner authority")
    # S3-31A-01: a derived summary must not overwrite owner truth.
    if fact.source.kind == SourceKind.DERIVED_SUMMARY:
        raise OwnerError("a derived summary cannot overwrite owner truth")
    return fact
