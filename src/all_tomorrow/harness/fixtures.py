"""Side-effect fixture store for 00A-1 Common Harness.

Tracks mutation calls, idempotency keys, execution counts, committed values,
and provides reconciliation lookups to strictly detect illegal duplicates (e.g. D04).
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional
from pydantic import BaseModel, Field

from .types import FailPoint, KillException


class SideEffectRecord(BaseModel):
    """External state representation recorded by the mutation fixture store."""

    idempotency_key: str
    call_count: int = 0
    application_count: int = 0
    committed_value: str
    reconciliation_lookup: Dict[str, Any] = Field(default_factory=dict)
    applied_at_least_once: bool = False


class DuplicateMutationError(RuntimeError):
    """Raised when a non-idempotent duplicate mutation is attempted."""

    def __init__(self, key: str, count: int):
        super().__init__(f"Duplicate mutation detected for key '{key}'! Total attempts: {count}")
        self.key = key
        self.count = count


class SideEffectFixtureStore:
    """In-memory thread-safe fixture store mimicking an external stateful system."""

    def __init__(self, strict_idempotency: bool = True):
        self._lock = threading.RLock()
        self._records: Dict[str, SideEffectRecord] = {}
        self.strict_idempotency = strict_idempotency

    def record_mutation(
        self,
        idempotency_key: str,
        value: str,
        kill_hook: Optional[Callable[[FailPoint], None]] = None,
        fail_point_to_trigger: FailPoint = FailPoint.NONE,
    ) -> SideEffectRecord:
        """Executes a mutation stub with idempotency recording and fail hook injection.

        If fail_point_to_trigger == AFTER_MUTATION_SIDE_EFFECT, the kill_hook is invoked
        immediately after the value is committed, strictly reproducing scenario D04.
        """
        with self._lock:
            existing = self._records.get(idempotency_key)
            if existing:
                existing.call_count += 1
                if self.strict_idempotency and existing.committed_value != value:
                    raise DuplicateMutationError(idempotency_key, existing.call_count)
                # If key matches and strict idempotency is on, return existing committed record (reconciliation)
                record = existing
            else:
                record = SideEffectRecord(
                    idempotency_key=idempotency_key,
                    call_count=1,
                    application_count=1,
                    committed_value=value,
                    reconciliation_lookup={
                        "version": 1,
                        "key": idempotency_key,
                        "stored_value": value,
                    },
                    applied_at_least_once=True,
                )
                self._records[idempotency_key] = record

            # If a kill hook was requested right after mutation, trigger it now
            if fail_point_to_trigger == FailPoint.AFTER_MUTATION_SIDE_EFFECT and kill_hook:
                kill_hook(FailPoint.AFTER_MUTATION_SIDE_EFFECT)

            return record

    def get(self, idempotency_key: str) -> Optional[SideEffectRecord]:
        """Lookup an existing side-effect record for verification or reconciliation."""
        with self._lock:
            return self._records.get(idempotency_key)

    def count(self, idempotency_key: str) -> int:
        with self._lock:
            record = self._records.get(idempotency_key)
            return record.call_count if record else 0

    def reset(self) -> None:
        """Clear all fixture records."""
        with self._lock:
            self._records.clear()
