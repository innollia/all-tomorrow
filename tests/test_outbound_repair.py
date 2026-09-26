"""Stage 2.2D + 2.3D — outbound delivery + repair operator verification."""

from __future__ import annotations

import pytest

from all_tomorrow.outbound import DeliveryStatus, OutboundDelivery, OutboundStore
from all_tomorrow.repair import RepairError, RepairItem, RepairService, RepairStatus


def _d(key="k1", channel="email", recipient="u1", sensitive=False):
    from all_tomorrow.domain.ids import new_id
    return OutboundDelivery(delivery_id=new_id("dlv"), channel=channel, recipient_id=recipient,
                            idempotency_key=key, payload_ref="artifact:1", sensitive=sensitive)


# S2-22D-01: retry never double-sends (idempotent enqueue + terminal deliver).
def test_22d_01_no_duplicate_on_retry() -> None:
    s = OutboundStore()
    d1 = s.enqueue(_d("dup"))
    d2 = s.enqueue(_d("dup"))
    assert d1.delivery_id == d2.delivery_id
    delivered = s.deliver(d1.delivery_id, transport_ok=True)
    again = s.deliver(d1.delivery_id, transport_ok=True)   # retry
    assert delivered.receipt == again.receipt              # same receipt, no re-send


# S2-22D-02/04: failed delivery is FAILED and forges no other state.
def test_22d_04_failed_delivery_isolated() -> None:
    s = OutboundStore()
    d = s.enqueue(_d("k"))
    failed = s.deliver(d.delivery_id, transport_ok=False)
    assert failed.status == DeliveryStatus.FAILED
    assert failed.receipt is None


# S2-22D-03: sensitive content only on allow-listed channels.
def test_22d_03_sensitive_channel_policy() -> None:
    s = OutboundStore()
    d = s.enqueue(_d("k", channel="public-webhook", sensitive=True))
    assert d.status == DeliveryStatus.SUPPRESSED
    s2 = OutboundStore(); s2.allow_sensitive("secure")
    d2 = s2.enqueue(_d("k2", channel="secure", sensitive=True))
    assert d2.status == DeliveryStatus.PENDING


def test_22d_opt_out_suppresses() -> None:
    s = OutboundStore()
    s.opt_out("u1", "email")
    d = s.enqueue(_d("k", channel="email", recipient="u1"))
    assert d.status == DeliveryStatus.SUPPRESSED


# --- Repair ---

def _repair(rid="r1", safe=True):
    return RepairItem(repair_id=rid, subject_ref="run:1", reason="reconciliation exhausted",
                      safe_to_retry=safe, provenance_refs=("evt:1",))


# S2-23D-01/04: item recorded + provenance preserved through reconcile.
def test_23d_reconcile_preserves_provenance() -> None:
    svc = RepairService(); svc.authorize("op")
    svc.record_repair_required(_repair())
    item = svc.reconcile("r1", "op", outcome_ref="evt:2")
    assert item.status == RepairStatus.RECONCILED
    assert "evt:1" in item.provenance_refs and "evt:2" in item.provenance_refs  # original kept


# S2-23D-02: non-safe side-effect cannot blind-retry.
def test_23d_02_unsafe_retry_blocked() -> None:
    svc = RepairService(); svc.authorize("op")
    svc.record_repair_required(_repair(safe=False))
    with pytest.raises(RepairError):
        svc.retry("r1", "op")
    # must resolve/reconcile explicitly instead
    assert svc.resolve("r1", "op").status == RepairStatus.RESOLVED


# S2-23D-03: operator action requires authorization + is audited.
def test_23d_03_auth_and_audit() -> None:
    svc = RepairService()
    svc.record_repair_required(_repair())
    with pytest.raises(RepairError):
        svc.resolve("r1", "stranger")     # unauthorized
    svc.authorize("op")
    svc.resolve("r1", "op")
    assert any(e.action == "resolve" and e.operator == "op" for e in svc.audit_trail())
