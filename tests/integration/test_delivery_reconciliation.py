from __future__ import annotations

import asyncio
import pytest

from all_tomorrow.adapters.fake_adapters import FakeDurableAdapter
from all_tomorrow.delivery import (
    BlindReplayForbiddenError,
    DeliveryKind,
    DeliveryRecord,
    DeliveryReconciler,
    DeliveryStatus,
    format_idempotency_key,
)
from all_tomorrow.domain.ids import new_delivery_id
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

    async def test_ambiguous_external_effect_blind_replay_forbidden(self) -> None:
        """S0-00B3-03: Ambiguous external effect must never be blindly replayed."""
        durable_port = FakeDurableAdapter()
        reconciler = DeliveryReconciler(durable_port)

        ambiguous_rec = DeliveryRecord(
            delivery_id=new_delivery_id(),
            kind=DeliveryKind.RUN_START,
            subject_refs={"run_id": "run_ambiguous"},
            destination_adapter="fake_durable",
            idempotency_key=format_idempotency_key("run", "start", "run_ambiguous"),
            payload={"workflow_name": "flow_ambiguous"},
            status=DeliveryStatus.AMBIGUOUS,
        )

        with pytest.raises(BlindReplayForbiddenError, match="Blind replay is forbidden"):
            await reconciler.reconcile(ambiguous_rec, allow_blind_replay=False)

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

    async def test_idempotency_key_formatting_and_versioning(self) -> None:
        """S0-00B3-05: Idempotency key scope, version, and collision resistance."""
        key_v1 = format_idempotency_key("run", "start", "run_999", version=1)
        key_v2 = format_idempotency_key("run", "start", "run_999", version=2)
        key_diff_scope = format_idempotency_key("run", "signal", "run_999", version=1)

        assert key_v1.startswith("idmp_run_start_v1_")
        assert key_v2.startswith("idmp_run_start_v2_")
        assert key_v1 != key_v2
        assert key_v1 != key_diff_scope
