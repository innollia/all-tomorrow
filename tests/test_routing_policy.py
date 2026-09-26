"""Stage 2.4A + 2.4B — resource registry + selection policy verification."""

from __future__ import annotations

from datetime import timedelta

import pytest

from all_tomorrow.domain.ids import utc_now
from all_tomorrow.resources import ResourceKind, ResourceRecord, ResourceRegistry
from all_tomorrow.routing_policy import NoResourceError, select


def _r(rid, caps, *, healthy=True, checked_ago=0, quota=100, cost=1.0, scope="default"):
    return ResourceRecord(
        resource_id=rid, kind=ResourceKind.MODEL, capabilities=frozenset(caps),
        authority_scope=scope, health_status="healthy" if healthy else "down",
        health_checked_at=utc_now() - timedelta(seconds=checked_ago),
        remaining_quota=quota, cost_per_unit=cost,
    )


# S2-24A-01: stale health → not available.
def test_24a_01_stale_health_unavailable() -> None:
    reg = ResourceRegistry(health_freshness_seconds=60)
    reg.register(_r("fresh", ["chat"], checked_ago=5))
    reg.register(_r("stale", ["chat"], checked_ago=600))   # health too old
    avail = reg.available(required_capabilities=frozenset({"chat"}))
    ids = {r.resource_id for r in avail}
    assert "fresh" in ids and "stale" not in ids


# S2-24A-03: unknown quota is conservative (unavailable).
def test_24a_03_unknown_quota_conservative() -> None:
    reg = ResourceRegistry()
    reg.register(_r("unknownq", ["chat"], quota=None))
    avail = reg.available(required_capabilities=frozenset({"chat"}))
    assert avail == []


# S2-24A-02: selection is by capability, not provider name (no name branch).
def test_24a_02_capability_not_provider_name() -> None:
    reg = ResourceRegistry()
    reg.register(_r("anything", ["code", "chat"]))
    avail = reg.available(required_capabilities=frozenset({"code"}))
    assert [r.resource_id for r in avail] == ["anything"]


# S2-24B-01: authority/capability hard filter.
def test_24b_01_hard_filter() -> None:
    reg = ResourceRegistry()
    reg.register(_r("wrong_scope", ["chat"], scope="other"))
    reg.register(_r("ok", ["chat"], scope="default"))
    avail = reg.available(required_capabilities=frozenset({"chat"}), authority_scope="default")
    assert [r.resource_id for r in avail] == ["ok"]


# S2-24B-02: selection independent of insertion order.
def test_24b_02_order_independent() -> None:
    a = _r("a", ["chat"], cost=2.0)
    b = _r("b", ["chat"], cost=1.0)
    assert select([a, b]).resource.resource_id == "b"
    assert select([b, a]).resource.resource_id == "b"   # same winner regardless of order


# S2-24B-04: explicit user choice preserved over inferred preference.
def test_24b_04_explicit_choice_preserved() -> None:
    a = _r("a", ["chat"], cost=1.0)   # cheapest
    b = _r("b", ["chat"], cost=5.0)
    res = select([a, b], explicit_choice_id="b", inferred_preference_id="a")
    assert res.resource.resource_id == "b"      # explicit wins even though a is cheaper
    assert "explicit" in res.reason


def test_24b_inferred_only_without_explicit() -> None:
    a = _r("a", ["chat"], cost=1.0)
    b = _r("b", ["chat"], cost=5.0)
    res = select([a, b], inferred_preference_id="b")
    assert res.resource.resource_id == "b"


def test_24b_no_candidates_raises() -> None:
    with pytest.raises(NoResourceError):
        select([])
