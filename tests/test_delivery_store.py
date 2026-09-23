from __future__ import annotations

import pytest

from all_tomorrow.delivery import (
    DeliveryKind,
    DeliveryRecord,
    DeliveryStatus,
    format_idempotency_key,
)
from all_tomorrow.domain.ids import new_delivery_id
from all_tomorrow.storage.delivery_store import DeliveryStore


@pytest.mark.asyncio
class TestDeliveryStore:
    async def test_create_and_get_by_id_and_idempotency(self) -> None:
        store = DeliveryStore()
        idmp = format_idempotency_key("run", "start", "run_123")
        rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_123"},
            destination_adapter="dbos",
            idempotency_key=idmp,
            payload={"workflow_name": "researcher"},
        )
        created = await store.create_delivery(rec)
        assert created.delivery_id == rec.delivery_id

        # Duplicate create with same idempotency key returns existing
        dup = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_123"},
            destination_adapter="dbos",
            idempotency_key=idmp,
            payload={"workflow_name": "different"},
        )
        retrieved_dup = await store.create_delivery(dup)
        assert retrieved_dup.delivery_id == rec.delivery_id

        # Lookup by id
        found = await store.get_delivery(rec.delivery_id)
        assert found is not None
        assert found.idempotency_key == idmp

        # Lookup by key
        found_key = await store.get_by_idempotency_key(idmp)
        assert found_key is not None
        assert found_key.delivery_id == rec.delivery_id

    async def test_cas_update_success_and_conflict(self) -> None:
        store = DeliveryStore()
        rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_456"},
            destination_adapter="dbos",
            idempotency_key="idmp_test_cas",
            payload={},
            revision=1,
        )
        await store.create_delivery(rec)

        # Successful CAS update with revision=1 -> revision=2
        updated = DeliveryRecord(
            delivery_id=rec.delivery_id,
            kind=rec.kind,
            subject_refs=rec.subject_refs,
            destination_adapter=rec.destination_adapter,
            idempotency_key=rec.idempotency_key,
            payload=rec.payload,
            status=DeliveryStatus.DISPATCHING,
            revision=2,
        )
        ok = await store.update_cas(expected_revision=1, updated=updated)
        assert ok is True

        # Conflicting CAS update using stale expected_revision=1
        stale_update = DeliveryRecord(
            delivery_id=rec.delivery_id,
            kind=rec.kind,
            subject_refs=rec.subject_refs,
            destination_adapter=rec.destination_adapter,
            idempotency_key=rec.idempotency_key,
            payload=rec.payload,
            status=DeliveryStatus.DELIVERED,
            revision=3,
        )
        ok_conflict = await store.update_cas(expected_revision=1, updated=stale_update)
        assert ok_conflict is False

    async def test_atomic_app_transaction(self) -> None:
        store = DeliveryStore()
        intent = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_789"},
            destination_adapter="dbos",
            idempotency_key="idmp_atomic_tx",
            payload={},
        )
        side_effect_state = []

        async def domain_mutation() -> str:
            side_effect_state.append("committed_domain_run")
            return "ok"

        res, committed_intent = await store.atomic_app_transaction(intent, domain_mutation)
        assert res == "ok"
        assert side_effect_state == ["committed_domain_run"]
        assert committed_intent.delivery_id == intent.delivery_id

        # Verify in store
        in_store = await store.get_delivery(intent.delivery_id)
        assert in_store is not None
