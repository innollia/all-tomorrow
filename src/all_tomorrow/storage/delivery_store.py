from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Callable, Coroutine, Protocol

from all_tomorrow.delivery import (
    DeliveryKind,
    DeliveryRecord,
    DeliveryStatus,
    utc_now,
)
from all_tomorrow.domain.errors import InvariantViolationError
from all_tomorrow.domain.ids import DeliveryId


class DeliveryCASConflictError(InvariantViolationError):
    """Raised when a concurrent reconciler conflicts on DeliveryRecord revision."""


class IdempotencyKeyExpiredError(InvariantViolationError):
    """Raised when an idempotency key is presented after its valid_until expiration."""


class DeliveryCommitError(InvariantViolationError):
    """Raised when an atomic outbox intent commit fails."""


class DeliveryStoreProtocol(Protocol):
    async def create_delivery(self, record: DeliveryRecord) -> DeliveryRecord:
        ...

    async def get_delivery(self, delivery_id: DeliveryId) -> DeliveryRecord | None:
        ...

    async def get_by_idempotency_key(self, key: str) -> DeliveryRecord | None:
        ...

    async def update_cas(self, expected_revision: int, updated: DeliveryRecord) -> bool:
        ...


class DeliveryStore:
    """Transactional storage for DeliveryRecord adhering to atomic outbox semantics."""

    def __init__(self) -> None:
        self._records_by_id: dict[DeliveryId, DeliveryRecord] = {}
        self._records_by_idempotency_key: dict[str, DeliveryId] = {}
        self._lock = asyncio.Lock()

    async def create_delivery(self, record: DeliveryRecord) -> DeliveryRecord:
        async with self._lock:
            now = utc_now()
            if record.idempotency_key in self._records_by_idempotency_key:
                existing_id = self._records_by_idempotency_key[record.idempotency_key]
                existing = self._records_by_id[existing_id]
                # S0-00B3-05: Idempotency retention check
                if existing.is_expired(now):
                    raise IdempotencyKeyExpiredError(
                        f"Idempotency key '{record.idempotency_key}' expired at {existing.valid_until}"
                    )
                return existing

            if record.is_expired(now):
                raise IdempotencyKeyExpiredError(
                    f"Cannot create delivery with already expired idempotency key (valid_until={record.valid_until})"
                )

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
            rec = self._records_by_id.get(delivery_id)
            if rec is not None and rec.is_expired():
                return None
            return rec

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
        """S0-00B3-01: Atomic application state mutation + delivery intent commit.

        Guarantees:
        - Domain mutation and outbox intent are validated and committed atomically under lock.
        - If pre-validation or intent commit fails, domain_action is never executed.
        - If domain_action fails, delivery intent is never committed.
        - Neither partial commit nor pseudo-compensation rollback is used.
        """
        async with self._lock:
            now = utc_now()
            # 1. Pre-validate intent (e.g. check TTL expiration or constraints)
            if intent.is_expired(now):
                raise IdempotencyKeyExpiredError(
                    f"Cannot commit outbox intent with expired key (valid_until={intent.valid_until})"
                )

            if intent.idempotency_key in self._records_by_idempotency_key:
                existing_id = self._records_by_idempotency_key[intent.idempotency_key]
                existing = self._records_by_id[existing_id]
                if existing.is_expired(now):
                    raise IdempotencyKeyExpiredError(
                        f"Idempotency key '{intent.idempotency_key}' expired at {existing.valid_until}"
                    )
                # Check for semantic payload/destination conflict on duplicate key
                if existing.destination_adapter != intent.destination_adapter or existing.subject_refs != intent.subject_refs:
                    raise DeliveryCASConflictError(
                        f"Idempotency key '{intent.idempotency_key}' already exists with different destination or subjects"
                    )
                committed_intent = existing
                domain_result = None
            else:
                committed_intent = intent
                # 2. Execute a new domain mutation under the same lock. A valid
                # duplicate intent returns the canonical record without applying
                # the semantic mutation a second time.
                domain_result = await domain_action()

            # 3. Finalize intent storage
            if committed_intent is intent:
                self._records_by_id[intent.delivery_id] = intent
                self._records_by_idempotency_key[intent.idempotency_key] = intent.delivery_id

            return domain_result, committed_intent
