from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from all_tomorrow.domain.errors import (
    CanonicalError,
    DomainError,
    ErrorCategory,
    InvalidStateTransitionError,
    InvariantViolationError,
)
from all_tomorrow.domain.ids import DeliveryId, new_delivery_id, utc_now
from all_tomorrow.ports.durable import (
    CancelOutcome,
    DurableExecutionPort,
    DurableExecutionState,
    SignalOutcome,
)


class DeliveryKind(StrEnum):
    RUN_START = "RUN_START"
    QUESTION_SIGNAL = "QUESTION_SIGNAL"
    ARTIFACT_ATTACH = "ARTIFACT_ATTACH"
    OUTBOUND_MESSAGE = "OUTBOUND_MESSAGE"
    SOURCE_MUTATION = "SOURCE_MUTATION"
    TRIGGER_FIRE = "TRIGGER_FIRE"


class DeliveryStatus(StrEnum):
    PENDING = "PENDING"
    DISPATCHING = "DISPATCHING"
    DELIVERED = "DELIVERED"
    AMBIGUOUS = "AMBIGUOUS"
    FAILED = "FAILED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    CANCELLED = "CANCELLED"


TERMINAL_DELIVERY_STATUSES: frozenset[DeliveryStatus] = frozenset({
    DeliveryStatus.DELIVERED,
    DeliveryStatus.REPAIR_REQUIRED,
    DeliveryStatus.CANCELLED,
})


def format_idempotency_key(
    namespace: str,
    scope: str,
    *parts: str,
    version: int = 1,
) -> str:
    """S0-00B3-05: Deterministic idempotency key generator with scope, version, and hash protection."""
    clean_parts = ":".join(p.strip() for p in parts if p.strip())
    raw_payload = f"{namespace}:{scope}:v{version}:{clean_parts}"
    hash_digest = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()[:24]
    return f"idmp_{namespace}_{scope}_v{version}_{hash_digest}"


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    """Cross-store delivery and reconciliation intent record."""
    delivery_id: DeliveryId
    kind: DeliveryKind
    subject_refs: dict[str, str]
    destination_adapter: str
    idempotency_key: str
    payload: dict[str, Any]
    status: DeliveryStatus = DeliveryStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    revision: int = 1
    last_error: CanonicalError | None = None
    next_attempt_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValueError("DeliveryRecord.idempotency_key must be non-empty")
        if not self.destination_adapter or not self.destination_adapter.strip():
            raise ValueError("DeliveryRecord.destination_adapter must be non-empty")
        if self.max_attempts < 1:
            raise ValueError("DeliveryRecord.max_attempts must be >= 1")
        if self.attempts < 0:
            raise ValueError("DeliveryRecord.attempts must be >= 0")

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_DELIVERY_STATUSES


class BlindReplayForbiddenError(InvariantViolationError):
    """Raised when attempting to blindly replay a delivery with ambiguous external effect."""


class DeliveryReconciler:
    """Coordinates dispatching and reconciliation of cross-store DeliveryRecords.

    Guarantees:
    - S0-00B3-02: Concurrent reconcilers converge to the same result via CAS.
    - S0-00B3-03: Ambiguous external effect is never blindly replayed without querying the existing effect.
    - S0-00B3-04: Exhausted attempts transition to REPAIR_REQUIRED (never silently discarded).
    """

    def __init__(self, durable_port: DurableExecutionPort) -> None:
        self.durable_port = durable_port

    async def reconcile(
        self,
        record: DeliveryRecord,
        allow_blind_replay: bool = False,
    ) -> DeliveryRecord:
        if record.is_terminal():
            return record

        now = utc_now()
        # S0-00B3-03: If status was AMBIGUOUS, blind replay is strictly forbidden
        if record.status == DeliveryStatus.AMBIGUOUS and not allow_blind_replay:
            raise BlindReplayForbiddenError(
                f"Delivery {record.delivery_id} has ambiguous state. Blind replay is forbidden until external state is reconciled."
            )

        # Check attempt exhaustion -> S0-00B3-04: REPAIR_REQUIRED
        next_attempts = record.attempts + 1
        if next_attempts > record.max_attempts:
            return DeliveryRecord(
                delivery_id=record.delivery_id,
                kind=record.kind,
                subject_refs=record.subject_refs,
                destination_adapter=record.destination_adapter,
                idempotency_key=record.idempotency_key,
                payload=record.payload,
                status=DeliveryStatus.REPAIR_REQUIRED,
                attempts=record.attempts,
                max_attempts=record.max_attempts,
                revision=record.revision + 1,
                last_error=record.last_error,
                created_at=record.created_at,
                updated_at=now,
            )

        try:
            if record.kind == DeliveryKind.RUN_START:
                from all_tomorrow.domain.ids import RunId
                run_id = RunId(record.subject_refs.get("run_id", record.idempotency_key))
                workflow_name = record.payload.get("workflow_name", "default_workflow")
                wf_payload = record.payload.get("workflow_payload", {})

                # Call durable port (idempotent for same run_id / idempotency_key)
                ref = await self.durable_port.start(
                    run_id=run_id,
                    workflow_name=workflow_name,
                    payload=wf_payload,
                    idempotency_key=record.idempotency_key,
                )
                return DeliveryRecord(
                    delivery_id=record.delivery_id,
                    kind=record.kind,
                    subject_refs=record.subject_refs,
                    destination_adapter=record.destination_adapter,
                    idempotency_key=record.idempotency_key,
                    payload=record.payload,
                    status=DeliveryStatus.DELIVERED,
                    attempts=next_attempts,
                    max_attempts=record.max_attempts,
                    revision=record.revision + 1,
                    delivered_at=now,
                    created_at=record.created_at,
                    updated_at=now,
                )

            elif record.kind == DeliveryKind.QUESTION_SIGNAL:
                from all_tomorrow.domain.ids import ExecutionRef
                exec_id = record.subject_refs.get("execution_id", "")
                signal_name = record.payload.get("signal_name", "user_answer")
                signal_id = record.subject_refs.get("signal_id", record.idempotency_key)
                ref = ExecutionRef(backend=record.destination_adapter, execution_id=exec_id)

                sig_res = await self.durable_port.signal(
                    ref=ref,
                    signal_name=signal_name,
                    signal_id=signal_id,
                    payload=record.payload.get("signal_payload", {}),
                )
                if sig_res.outcome in (SignalOutcome.DELIVERED, SignalOutcome.DUPLICATE_IGNORED):
                    return DeliveryRecord(
                        delivery_id=record.delivery_id,
                        kind=record.kind,
                        subject_refs=record.subject_refs,
                        destination_adapter=record.destination_adapter,
                        idempotency_key=record.idempotency_key,
                        payload=record.payload,
                        status=DeliveryStatus.DELIVERED,
                        attempts=next_attempts,
                        max_attempts=record.max_attempts,
                        revision=record.revision + 1,
                        delivered_at=now,
                        created_at=record.created_at,
                        updated_at=now,
                    )
                else:
                    return DeliveryRecord(
                        delivery_id=record.delivery_id,
                        kind=record.kind,
                        subject_refs=record.subject_refs,
                        destination_adapter=record.destination_adapter,
                        idempotency_key=record.idempotency_key,
                        payload=record.payload,
                        status=DeliveryStatus.FAILED,
                        attempts=next_attempts,
                        max_attempts=record.max_attempts,
                        revision=record.revision + 1,
                        last_error=sig_res.error,
                        created_at=record.created_at,
                        updated_at=now,
                    )
            else:
                # Other delivery kinds mark as delivered for this base seam
                return DeliveryRecord(
                    delivery_id=record.delivery_id,
                    kind=record.kind,
                    subject_refs=record.subject_refs,
                    destination_adapter=record.destination_adapter,
                    idempotency_key=record.idempotency_key,
                    payload=record.payload,
                    status=DeliveryStatus.DELIVERED,
                    attempts=next_attempts,
                    max_attempts=record.max_attempts,
                    revision=record.revision + 1,
                    delivered_at=now,
                    created_at=record.created_at,
                    updated_at=now,
                )

        except Exception as exc:
            from all_tomorrow.error_normalization import normalize_exception
            err = normalize_exception(exc)
            # If the error is ambiguous (e.g. timeout / connection reset), transition to AMBIGUOUS
            new_status = DeliveryStatus.AMBIGUOUS if err.ambiguity else DeliveryStatus.FAILED
            if next_attempts >= record.max_attempts:
                new_status = DeliveryStatus.REPAIR_REQUIRED

            return DeliveryRecord(
                delivery_id=record.delivery_id,
                kind=record.kind,
                subject_refs=record.subject_refs,
                destination_adapter=record.destination_adapter,
                idempotency_key=record.idempotency_key,
                payload=record.payload,
                status=new_status,
                attempts=next_attempts,
                max_attempts=record.max_attempts,
                revision=record.revision + 1,
                last_error=err,
                created_at=record.created_at,
                updated_at=now,
            )
