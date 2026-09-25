from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import pytest

from all_tomorrow.adapters.fake_adapters import FakeDurableAdapter
from all_tomorrow.delivery import (
    DeliveryKind,
    DeliveryRecord,
    DeliveryReconciler,
    DeliveryStatus,
    RetentionClass,
    calculate_valid_until,
    format_idempotency_key,
    utc_now,
)
from all_tomorrow.domain.errors import ErrorCategory
from all_tomorrow.domain.ids import ExecutionRef, new_delivery_id
from all_tomorrow.storage.delivery_store import DeliveryStore


@pytest.mark.asyncio
class TestDeliveryReconciliation:
    """Requirements S0-00B3-01 through S0-00B3-05."""

    async def test_atomic_app_transaction_and_delivery_intent(self) -> None:
        """S0-00B3-01: App transaction + delivery intent committed together."""
        store = DeliveryStore()
        durable_port = FakeDurableAdapter()
        reconciler = DeliveryReconciler(durable_port)

        intent = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_recon_1"},
            destination_adapter="fake_durable",
            idempotency_key=format_idempotency_key("run", "start", "run_recon_1"),
            payload={"workflow_name": "flow_1"},
        )

        app_db_state = {}

        async def domain_commit() -> None:
            app_db_state["run_recon_1"] = "COMMITTED_IN_APP_DB"

        _, committed_intent = await store.atomic_app_transaction(intent, domain_commit)
        assert app_db_state["run_recon_1"] == "COMMITTED_IN_APP_DB"
        assert committed_intent.status == DeliveryStatus.PENDING

        # Now reconciler executes delivery
        result_record = await reconciler.reconcile(committed_intent)
        assert result_record.status == DeliveryStatus.DELIVERED
        assert result_record.delivered_at is not None

    async def test_concurrent_reconcilers_converge_via_cas(self) -> None:
        """S0-00B3-02: Concurrent reconcilers converge to the exact same result."""
        store = DeliveryStore()
        durable_port = FakeDurableAdapter()
        reconciler = DeliveryReconciler(durable_port)

        rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_concurrent"},
            destination_adapter="fake_durable",
            idempotency_key=format_idempotency_key("run", "start", "run_concurrent"),
            payload={"workflow_name": "flow_concurrent"},
        )
        await store.create_delivery(rec)

        async def run_worker() -> DeliveryRecord:
            current = await store.get_delivery(rec.delivery_id)
            assert current is not None
            reconciled = await reconciler.reconcile(current)
            # CAS update
            await store.update_cas(expected_revision=current.revision, updated=reconciled)
            final = await store.get_delivery(rec.delivery_id)
            return final or reconciled

        # Run two concurrent reconciler workers
        res1, res2 = await asyncio.gather(run_worker(), run_worker())

        # Both converge to DELIVERED with the same idempotency key and same target
        assert res1.status == DeliveryStatus.DELIVERED
        assert res2.status == DeliveryStatus.DELIVERED
        assert res1.idempotency_key == res2.idempotency_key

    async def test_ambiguous_recovery_queries_existing_effect_without_blind_replay(self) -> None:
        """S0-00B3-03: Ambiguous recovery checks external state and does not blindly replay."""
        durable_port = FakeDurableAdapter()
        reconciler = DeliveryReconciler(durable_port)

        run_id = "run_ambiguous_recovery"
        # Pre-seed external backend as if the start reached it before network crashed
        from all_tomorrow.domain.ids import RunId
        exec_ref = await durable_port.start(
            run_id=RunId(run_id),
            workflow_name="flow_ambiguous",
            payload={},
        )

        ambiguous_rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": run_id},
            destination_adapter="fake_durable",
            idempotency_key=format_idempotency_key("run", "start", run_id),
            payload={"workflow_name": "flow_ambiguous"},
            status=DeliveryStatus.AMBIGUOUS,
            attempts=1,
            max_attempts=3,
        )

        # Reconciling the AMBIGUOUS record must query external backend, discover execution is RUNNING,
        # and resolve to DELIVERED (no blind replay error, no duplicate execution)
        resolved = await reconciler.reconcile(ambiguous_rec)
        assert resolved.status == DeliveryStatus.DELIVERED
        assert resolved.delivered_at is not None

    async def test_ambiguous_recovery_when_external_not_found(self) -> None:
        """S0-00B3-03: When ambiguous probe confirms NOT_FOUND, then and only then start."""
        durable_port = FakeDurableAdapter()
        reconciler = DeliveryReconciler(durable_port)

        run_id = "run_not_yet_started"
        ambiguous_rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": run_id},
            destination_adapter="fake_durable",
            idempotency_key=format_idempotency_key("run", "start", run_id),
            payload={"workflow_name": "flow_new"},
            status=DeliveryStatus.AMBIGUOUS,
            attempts=1,
            max_attempts=3,
        )

        resolved = await reconciler.reconcile(ambiguous_rec)
        assert resolved.status == DeliveryStatus.DELIVERED
        # Verify it now exists in external backend
        ref = ExecutionRef(backend="fake_durable", execution_id=f"exec_{run_id}")
        status = await durable_port.get_status(ref)
        assert status.error is None

    async def test_exhausted_delivery_moves_to_repair_required(self) -> None:
        """S0-00B3-04: Exhausted delivery moves to REPAIR_REQUIRED and is not deleted."""
        durable_port = FakeDurableAdapter()
        durable_port.simulate_unavailable = True
        reconciler = DeliveryReconciler(durable_port)

        rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_exhaust"},
            destination_adapter="fake_durable",
            idempotency_key=format_idempotency_key("run", "start", "run_exhaust"),
            payload={"workflow_name": "flow_exhaust"},
            attempts=2,
            max_attempts=3,
        )

        # 3rd attempt will fail and exhaust max_attempts=3
        exhausted = await reconciler.reconcile(rec)
        assert exhausted.status == DeliveryStatus.REPAIR_REQUIRED
        assert exhausted.is_terminal()
        assert exhausted.attempts == 3

    async def test_unimplemented_delivery_kind_fails_closed_never_marked_delivered(self) -> None:
        """Issue 1: Unimplemented/unhandled delivery kind must NOT be marked DELIVERED."""
        durable_port = FakeDurableAdapter()
        reconciler = DeliveryReconciler(durable_port)

        unhandled_rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.TRIGGER_FIRE,
            subject_refs={"trigger_id": "trig_1"},
            destination_adapter="scheduler",
            idempotency_key="idmp_unhandled_trig",
            payload={"trigger_name": "daily_eval"},
        )

        result = await reconciler.reconcile(unhandled_rec)
        assert result.status == DeliveryStatus.FAILED
        assert result.status != DeliveryStatus.DELIVERED
        assert result.last_error is not None
        assert result.last_error.category == ErrorCategory.UNSUPPORTED
        assert result.delivered_at is None

    async def test_idempotency_retention_ttl_expiration_fails_closed(self) -> None:
        """Issue 4: Idempotency retention TTL expiration prevents dispatching expired delivery."""
        durable_port = FakeDurableAdapter()
        reconciler = DeliveryReconciler(durable_port)

        now = utc_now()
        past = now - timedelta(minutes=5)
        expired_rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_ttl"},
            destination_adapter="fake_durable",
            idempotency_key="idmp_ttl_expired",
            payload={},
            valid_until=past,
        )

        res = await reconciler.reconcile(expired_rec)
        assert res.status == DeliveryStatus.FAILED
        assert res.status != DeliveryStatus.DELIVERED
        assert res.last_error is not None
        assert res.last_error.code == "idempotency_key_expired"
