from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from all_tomorrow.domain.ids import EventId, new_event_id, utc_now


@dataclass(frozen=True, slots=True)
class EventRecord:
    """Canonical domain event record."""
    event_id: EventId
    event_type: str
    actor_ref: str
    correlation_id: str
    schema_version: int = 1
    occurred_at: datetime = field(default_factory=utc_now)
    recorded_at: datetime = field(default_factory=utc_now)
    causation_event_id: EventId | None = None
    idempotency_key: str | None = None
    subject_refs: dict[str, str] = field(default_factory=dict)
    payload_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.event_type or not self.event_type.strip():
            raise ValueError("EventRecord.event_type must be non-empty")
        if self.schema_version < 1:
            raise ValueError("EventRecord.schema_version must be >= 1")
        if not self.actor_ref or not self.actor_ref.strip():
            raise ValueError("EventRecord.actor_ref must be non-empty")
        if not self.correlation_id or not self.correlation_id.strip():
            raise ValueError("EventRecord.correlation_id must be non-empty")

    def sort_key(self) -> tuple[datetime, str]:
        """Tie-break ordering using occurred_at and event_id."""
        return (self.occurred_at, str(self.event_id))
