from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from all_tomorrow.domain.errors import (
    CanonicalError,
    DomainError,
    ErrorCategory,
    InvalidStateTransitionError,
    InvariantViolationError,
)
from all_tomorrow.domain.ids import DeliveryId, ExecutionRef, RunId, new_delivery_id, utc_now
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


class IdempotencyScope(StrEnum):
    USER = "USER"
    PROJECT = "PROJECT"
    RUN = "RUN"
    GLOBAL = "GLOBAL"


class RetentionClass(StrEnum):
    SHORT_LIVED = "SHORT_LIVED"   # e.g., 1 hour
    STANDARD = "STANDARD"         # e.g., 24 hours
    EXTENDED = "EXTENDED"         # e.g., 7 days
    PERMANENT = "PERMANENT"       # e.g., no TTL


RETENTION_TTL_MAP: dict[RetentionClass, timedelta | None] = {
    RetentionClass.SHORT_LIVED: timedelta(hours=1),
    RetentionClass.STANDARD: timedelta(hours=24),
    RetentionClass.EXTENDED: timedelta(days=7),
    RetentionClass.PERMANENT: None,
}


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
    retention_class: RetentionClass = RetentionClass.STANDARD,
) -> str:
    """S0-00B3-05: Deterministic idempotency key generator with scope, version, and hash protection."""
    clean_parts = ":".join(p.strip() for p in parts if p.strip())
    raw_payload = f"{namespace}:{scope}:v{version}:{clean_parts}"
    hash_digest = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()[:24]
    return f"idmp_{namespace}_{scope}_v{version}_{hash_digest}"


def calculate_valid_until(
    retention_class: RetentionClass = RetentionClass.STANDARD,
    start_time: datetime | None = None,
) -> datetime | None:
    delta = RETENTION_TTL_MAP.get(retention_class)
    if delta is None:
        return None
    return (start_time or utc_now()) + delta


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
    idempotency_scope: str = "global"
    retention_class: str = "standard"
    valid_until: datetime | None = None
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
        if self.valid_until is None:
            r_class = self.retention_class.upper() if isinstance(self.retention_class, str) else self.retention_class
            try:
                ret_enum = RetentionClass(r_class)
            except ValueError:
                ret_enum = RetentionClass.STANDARD
            ttl = calculate_valid_until(ret_enum, self.created_at)
            if ttl is not None:
                object.__setattr__(self, "valid_until", ttl)

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_DELIVERY_STATUSES

    def is_expired(self, as_of: datetime | None = None) -> bool:
        if self.valid_until is None:
            return False
        return (as_of or utc_now()) > self.valid_until


class BlindReplayForbiddenError(InvariantViolationError):
    """Raised when attempting to blindly replay a delivery with ambiguous external effect."""


class UnsupportedDeliveryKindError(InvariantViolationError):
    """Raised when a delivery kind has no registered executor or adapter."""


class DeliveryHandler(Protocol):
    """Protocol for specialized delivery handlers."""
    async def handle_delivery(self, record: DeliveryRecord) -> tuple[bool, Any, CanonicalError | None]:
        ...


class DeliveryReconciler:
    """Coordinates dispatching and reconciliation of cross-store DeliveryRecords.

    Guarantees:
    - S0-00B3-01: Application state mutation + delivery intent are committed together.
    - S0-00B3-02: Concurrent reconcilers converge to the same result via CAS.
    - S0-00B3-03: Ambiguous external effect is queried before any retry; blind replay is forbidden.
    - S0-00B3-04: Exhausted attempts transition to REPAIR_REQUIRED (never silently discarded).
    - S0-00B3-05: Idempotency keys respect scope, version, and retention lifecycle.
    - Unimplemented delivery kinds are NEVER marked DELIVERED; they fail closed.
    """

    def __init__(
        self,
        durable_port: DurableExecutionPort,
        handlers: dict[DeliveryKind, DeliveryHandler] | None = None,
    ) -> None:
        self.durable_port = durable_port
        self._handlers: dict[DeliveryKind, DeliveryHandler] = handlers or {}

    def register_handler(self, kind: DeliveryKind, handler: DeliveryHandler) -> None:
        self._handlers[kind] = handler

    async def reconcile(self, record: DeliveryRecord) -> DeliveryRecord:
        if record.is_terminal():
            return record

        now = utc_now()

        # Check TTL expiration
        if record.is_expired(now):
            return DeliveryRecord(
                delivery_id=record.delivery_id,
                kind=record.kind,
                subject_refs=record.subject_refs,
                destination_adapter=record.destination_adapter,
                idempotency_key=record.idempotency_key,
                payload=record.payload,
                status=DeliveryStatus.FAILED,
                attempts=record.attempts,
                max_attempts=record.max_attempts,
                revision=record.revision + 1,
                idempotency_scope=record.idempotency_scope,
                retention_class=record.retention_class,
                valid_until=record.valid_until,
                last_error=CanonicalError(
                    category=ErrorCategory.TIMEOUT,
                    code="idempotency_key_expired",
                    retryability=False,
                    ambiguity=False,
                    safe_message=f"Delivery TTL expired at {record.valid_until}",
                ),
                created_at=record.created_at,
                updated_at=now,
            )

        # S0-00B3-03: Ambiguous recovery through external inquiry (NEVER blind replay)
        if record.status == DeliveryStatus.AMBIGUOUS:
            return await self._reconcile_ambiguous(record)

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
                idempotency_scope=record.idempotency_scope,
                retention_class=record.retention_class,
                valid_until=record.valid_until,
                last_error=record.last_error,
                created_at=record.created_at,
                updated_at=now,
            )

        try:
            if record.kind == DeliveryKind.RUN_START:
                return await self._dispatch_run_start(record, next_attempts, now)
            elif record.kind == DeliveryKind.QUESTION_SIGNAL:
                return await self._dispatch_question_signal(record, next_attempts, now)
            elif record.kind in self._handlers:
                handler = self._handlers[record.kind]
                success, _, err = await handler.handle_delivery(record)
                status = DeliveryStatus.DELIVERED if success else DeliveryStatus.FAILED
                delivered_at = now if success else None
                return DeliveryRecord(
                    delivery_id=record.delivery_id,
                    kind=record.kind,
                    subject_refs=record.subject_refs,
                    destination_adapter=record.destination_adapter,
                    idempotency_key=record.idempotency_key,
                    payload=record.payload,
                    status=status,
                    attempts=next_attempts,
                    max_attempts=record.max_attempts,
                    revision=record.revision + 1,
                    idempotency_scope=record.idempotency_scope,
                    retention_class=record.retention_class,
                    valid_until=record.valid_until,
                    last_error=err,
                    delivered_at=delivered_at,
                    created_at=record.created_at,
                    updated_at=now,
                )
            else:
                # S0-00B3: Unimplemented delivery kinds MUST NOT pretend to be DELIVERED!
                # They fail closed with ErrorCategory.UNSUPPORTED.
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
                    idempotency_scope=record.idempotency_scope,
                    retention_class=record.retention_class,
                    valid_until=record.valid_until,
                    last_error=CanonicalError(
                        category=ErrorCategory.UNSUPPORTED,
                        code="unsupported_delivery_kind",
                        retryability=False,
                        ambiguity=False,
                        safe_message=f"DeliveryKind '{record.kind.value}' has no registered handler and cannot be delivered",
                    ),
                    created_at=record.created_at,
                    updated_at=now,
                )

        except Exception as exc:
            from all_tomorrow.error_normalization import normalize_exception
            err = normalize_exception(exc)
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
                idempotency_scope=record.idempotency_scope,
                retention_class=record.retention_class,
                valid_until=record.valid_until,
                last_error=err,
                created_at=record.created_at,
                updated_at=now,
            )

    async def _dispatch_run_start(
        self,
        record: DeliveryRecord,
        next_attempts: int,
        now: datetime,
    ) -> DeliveryRecord:
        run_id = RunId(record.subject_refs.get("run_id", record.idempotency_key))
        workflow_name = record.payload.get("workflow_name", "default_workflow")
        wf_payload = record.payload.get("workflow_payload", {})

        await self.durable_port.start(
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
            idempotency_scope=record.idempotency_scope,
            retention_class=record.retention_class,
            valid_until=record.valid_until,
            delivered_at=now,
            created_at=record.created_at,
            updated_at=now,
        )

    async def _dispatch_question_signal(
        self,
        record: DeliveryRecord,
        next_attempts: int,
        now: datetime,
    ) -> DeliveryRecord:
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
                idempotency_scope=record.idempotency_scope,
                retention_class=record.retention_class,
                valid_until=record.valid_until,
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
                idempotency_scope=record.idempotency_scope,
                retention_class=record.retention_class,
                valid_until=record.valid_until,
                last_error=sig_res.error,
                created_at=record.created_at,
                updated_at=now,
            )

    async def _reconcile_ambiguous(self, record: DeliveryRecord) -> DeliveryRecord:
        """S0-00B3-03: Probes external system state to reconcile ambiguous delivery.

        CRITICAL: Never blindly replay. Query the existing external effect first.
        """
        now = utc_now()
        next_attempts = record.attempts + 1

        if record.kind == DeliveryKind.RUN_START:
            run_id = record.subject_refs.get("run_id", "")
            try:
                # S0-00B3-03: Discover external execution ref through port discovery (never guess IDs)
                ref = await self.durable_port.find_by_run_id(RunId(run_id))
                if ref is None:
                    # External backend confirmed execution does not exist.
                    # Safe to start now with deterministic key.
                    return await self._dispatch_run_start(record, next_attempts, now)

                status_res = await self.durable_port.get_status(ref)
                if status_res.error is not None:
                    if status_res.error.category == ErrorCategory.NOT_FOUND:
                        return await self._dispatch_run_start(record, next_attempts, now)
                    elif status_res.error.category == ErrorCategory.UNAVAILABLE:
                        # Still unreachable. Do not blind replay.
                        new_status = DeliveryStatus.REPAIR_REQUIRED if next_attempts >= record.max_attempts else DeliveryStatus.AMBIGUOUS
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
                            idempotency_scope=record.idempotency_scope,
                            retention_class=record.retention_class,
                            valid_until=record.valid_until,
                            last_error=status_res.error,
                            created_at=record.created_at,
                            updated_at=now,
                        )

                # External execution exists!
                if status_res.state in (
                    DurableExecutionState.RUNNING,
                    DurableExecutionState.WAITING,
                    DurableExecutionState.COMPLETED,
                ):
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
                        idempotency_scope=record.idempotency_scope,
                        retention_class=record.retention_class,
                        valid_until=record.valid_until,
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
                        idempotency_scope=record.idempotency_scope,
                        retention_class=record.retention_class,
                        valid_until=record.valid_until,
                        last_error=status_res.error,
                        created_at=record.created_at,
                        updated_at=now,
                    )
            except Exception as exc:
                from all_tomorrow.error_normalization import normalize_exception
                err = normalize_exception(exc)
                new_status = DeliveryStatus.REPAIR_REQUIRED if next_attempts >= record.max_attempts else DeliveryStatus.AMBIGUOUS
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
                    idempotency_scope=record.idempotency_scope,
                    retention_class=record.retention_class,
                    valid_until=record.valid_until,
                    last_error=err,
                    created_at=record.created_at,
                    updated_at=now,
                )

        # For kinds without deterministic probe, fail closed to REPAIR_REQUIRED
        return DeliveryRecord(
            delivery_id=record.delivery_id,
            kind=record.kind,
            subject_refs=record.subject_refs,
            destination_adapter=record.destination_adapter,
            idempotency_key=record.idempotency_key,
            payload=record.payload,
            status=DeliveryStatus.REPAIR_REQUIRED,
            attempts=next_attempts,
            max_attempts=record.max_attempts,
            revision=record.revision + 1,
            idempotency_scope=record.idempotency_scope,
            retention_class=record.retention_class,
            valid_until=record.valid_until,
            last_error=CanonicalError(
                category=ErrorCategory.AMBIGUOUS_EFFECT,
                code="ambiguous_reconciliation_unsupported",
                retryability=False,
                ambiguity=True,
                safe_message=f"Cannot safely probe ambiguous effect for {record.kind.value}. Operator repair required.",
            ),
            created_at=record.created_at,
            updated_at=now,
        )
