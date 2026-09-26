"""Stage 3.1A — Owner adapters & source precedence verification (S3-31A-01..04)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from all_tomorrow.domain.ids import utc_now
from all_tomorrow.owners import (
    AuthorityError,
    OwnerError,
    OwnerFact,
    SourceKind,
    SourceRef,
    Truthiness,
    read_fact,
    write_fact,
)


def _ref(kind, age=timedelta(0), fresh=timedelta(hours=1)):
    return SourceRef(source_id=f"s-{kind}", kind=kind, fetched_at=utc_now() - age, freshness=fresh)


def _fact(kind, value="v", age=timedelta(0)):
    return OwnerFact(key="next_class", value=value, source=_ref(kind, age))


# S3-31A-02: owner canonical outranks cache outranks derived summary.
def test_31a_02_source_precedence() -> None:
    cands = [_fact(SourceKind.DERIVED_SUMMARY, "summary"),
             _fact(SourceKind.CACHE, "cache"),
             _fact(SourceKind.OWNER_CANONICAL, "truth")]
    best, t = read_fact(cands)
    assert best.value == "truth" and t == Truthiness.CURRENT


# S3-31A-03: a stale cache is not passed off as current truth.
def test_31a_03_stale_cache_not_current() -> None:
    stale = _fact(SourceKind.CACHE, "old", age=timedelta(hours=5))
    best, t = read_fact([stale])
    assert t == Truthiness.STALE_UNKNOWN


def test_31a_no_candidates_need_user() -> None:
    best, t = read_fact([])
    assert best is None and t == Truthiness.NEED_USER


# S3-31A-04: writing owner truth requires authority.
def test_31a_04_authority_enforced() -> None:
    with pytest.raises(AuthorityError):
        write_fact(_fact(SourceKind.OWNER_CANONICAL), has_owner_authority=False)
    ok = write_fact(_fact(SourceKind.OWNER_CANONICAL), has_owner_authority=True)
    assert ok.value == "v"


# S3-31A-01: a derived summary cannot overwrite owner truth.
def test_31a_01_derived_cannot_overwrite() -> None:
    with pytest.raises(OwnerError):
        write_fact(_fact(SourceKind.DERIVED_SUMMARY), has_owner_authority=True)
