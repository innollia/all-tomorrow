"""Stage 2.3A — Context Pack verification (S2-23A-01..04)."""

from __future__ import annotations

import pytest

from all_tomorrow.context_pack import (
    Authority,
    ContextItem,
    OwnerConflictError,
    build_context_pack,
    is_control_authority,
)


def _item(ref, authority, size=10, owner="u1"):
    return ContextItem(ref=ref, owner_id=owner, authority=authority, size_bytes=size, summary=f"sum:{ref}")


# S2-23A-01: deterministic bounded selection (same inputs → same pack, order-independent).
def test_23a_01_deterministic_bounded() -> None:
    items = [_item("a", Authority.DATA), _item("b", Authority.CONTROL), _item("c", Authority.DATA)]
    p1 = build_context_pack(objective="o", owner_id="u1", items=items, byte_budget=20)
    p2 = build_context_pack(objective="o", owner_id="u1", items=list(reversed(items)), byte_budget=20)
    assert [i.ref for i in p1.control_items] == [i.ref for i in p2.control_items]
    assert p1.total_bytes == p2.total_bytes
    # CONTROL selected first within budget.
    assert "b" in [i.ref for i in p1.control_items]


# S2-23A-02: omitted refs are summarized, not silently dropped.
def test_23a_02_omitted_refs_recorded() -> None:
    items = [_item("a", Authority.CONTROL, size=15), _item("b", Authority.DATA, size=15)]
    p = build_context_pack(objective="o", owner_id="u1", items=items, byte_budget=15)
    assert p.omitted_refs == ("b",)      # b didn't fit → recorded, not dropped silently


# S2-23A-03: cross-owner merge is rejected (no silent merge).
def test_23a_03_owner_conflict_rejected() -> None:
    items = [_item("a", Authority.CONTROL, owner="u1"), _item("b", Authority.DATA, owner="u2")]
    with pytest.raises(OwnerConflictError):
        build_context_pack(objective="o", owner_id="u1", items=items, byte_budget=100)


# S2-23A-04: untrusted DATA content cannot expand authority.
def test_23a_04_data_cannot_expand_authority() -> None:
    items = [
        _item("policy", Authority.CONTROL),
        _item("webpage", Authority.DATA),   # even if it says "ignore policy / run command"
    ]
    p = build_context_pack(objective="o", owner_id="u1", items=items, byte_budget=100)
    assert is_control_authority(p, "policy") is True
    assert is_control_authority(p, "webpage") is False   # DATA never grants authority
