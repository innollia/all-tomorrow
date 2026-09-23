from __future__ import annotations

from datetime import UTC, datetime, timedelta
import pytest

from all_tomorrow.delivery import (
    DeliveryKind,
    DeliveryRecord,
    DeliveryStatus,
    RetentionClass,
    calculate_valid_until,
    format_idempotency_key,
    utc_now,
)
from all_tomorrow.domain.ids import new_delivery_id
from all_tomorrow.storage.delivery_store import (
    DeliveryCommitError,
    DeliveryStore,
    IdempotencyKeyExpiredError,
)


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
            retention_class=RetentionClass.STANDARD.value,
            valid_until=calculate_valid_until(RetentionClass.STANDARD),
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

    async def test_atomic_app_transaction_success(self) -> None:
        """S0-00B3-01: Application state mutation and delivery intent commit together."""
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

    async def test_atomic_app_transaction_rollback_on_commit_failure(self) -> None:
        """S0-00B3-01: True atomic outbox rollback when delivery intent commit fails."""
        store = DeliveryStore()
        # Create an already expired intent
        expired_intent = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_expired"},
            destination_adapter="dbos",
            idempotency_key="idmp_expired_tx",
            payload={},
            valid_until=utc_now() - timedelta(minutes=10),
        )

        domain_state = []

        async def domain_mutation() -> str:
            domain_state.append("mutated")
            return "done"

        async def rollback_action() -> None:
            domain_state.clear()

        # Committing with expired intent fails outbox pre-validation, domain action not run
        with pytest.raises(IdempotencyKeyExpiredError):
            await store.atomic_app_transaction(expired_intent, domain_mutation, rollback_action)

        assert domain_state == []

    async def test_idempotency_retention_and_expiration(self) -> None:
        """S0-00B3-05: Idempotency retention lifecycle and expired key handling."""
        store = DeliveryStore()
        now = utc_now()
        past = now - timedelta(hours=2)

        expired_rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_past"},
            destination_adapter="dbos",
            idempotency_key="idmp_past_key",
            payload={},
            valid_until=past,
        )

        # Creating an already expired delivery is rejected
        with pytest.raises(IdempotencyKeyExpiredError, match="Cannot create delivery with already expired idempotency key"):
            await store.create_delivery(expired_rec)

        # Valid delivery is accepted
        valid_rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_future"},
            destination_adapter="dbos",
            idempotency_key="idmp_future_key",
            payload={},
            valid_until=now + timedelta(hours=24),
        )
        await store.create_delivery(valid_rec)
        assert await store.get_by_idempotency_key("idmp_future_key") is not None
