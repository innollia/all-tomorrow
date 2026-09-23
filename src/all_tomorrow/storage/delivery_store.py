from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from all_tomorrow.delivery import DeliveryRecord, DeliveryStatus
from all_tomorrow.domain.errors import InvariantViolationError
from all_tomorrow.domain.ids import DeliveryId


class DeliveryCASConflictError(InvariantViolationError):
    """Raised when a concurrent reconciler conflicts on DeliveryRecord revision."""


class DeliveryStore:
    """In-memory atomic storage for DeliveryRecord with CAS support."""

    def __init__(self) -> None:
        self._records_by_id: dict[DeliveryId, DeliveryRecord] = {}
        self._records_by_idempotency_key: dict[str, DeliveryId] = {}
        self._lock = asyncio.Lock()

    async def create_delivery(self, record: DeliveryRecord) -> DeliveryRecord:
        async with self._lock:
            if record.idempotency_key in self._records_by_idempotency_key:
                existing_id = self._records_by_idempotency_key[record.idempotency_key]
                return self._records_by_id[existing_id]
            self._records_by_id[record.delivery_id] = record
            self._records_by_idempotency_key[record.idempotency_key] = record.delivery_id
            return record

    async def get_delivery(self, delivery_id: DeliveryId) -> DeliveryRecord | None:
        async with self._lock:
            return self._records_by_id.get(delivery_id)

    async def get_by_idempotency_key(self, key: str) -> DeliveryRecord | None:
        async with self._lock:
            delivery_id = self._records_by_idempotency_key.get(key)
            if delivery_id is None:
                return None
            return self._records_by_id.get(delivery_id)

    async def update_cas(self, expected_revision: int, updated: DeliveryRecord) -> bool:
        """Compare-and-swap update based on revision."""
        async with self._lock:
            current = self._records_by_id.get(updated.delivery_id)
            if current is None:
                return False
            if current.revision != expected_revision:
                return False
            self._records_by_id[updated.delivery_id] = updated
            return True

    async def atomic_app_transaction(
        self,
        intent: DeliveryRecord,
        domain_action: Callable[[], Coroutine[Any, Any, Any]],
    ) -> tuple[Any, DeliveryRecord]:
        """S0-00B3-01: Atomic application state mutation + delivery intent commit."""
        async with self._lock:
            # Execute domain action
            domain_result = await domain_action()
            # Commit intent
            if intent.idempotency_key in self._records_by_idempotency_key:
                existing_id = self._records_by_idempotency_key[intent.idempotency_key]
                committed_intent = self._records_by_id[existing_id]
            else:
                self._records_by_id[intent.delivery_id] = intent
                self._records_by_idempotency_key[intent.idempotency_key] = intent.delivery_id
                committed_intent = intent
            return domain_result, committed_intent
