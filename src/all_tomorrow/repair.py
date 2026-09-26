"""Stage 2.3D — Repair / Operator Workflow.

Surfaces REPAIR_REQUIRED items for an operator to inspect / retry / reconcile /
resolve / abandon. Every operator action is authorized and audited. An item
whose side-effect is not blind-retryable requires an explicit resolution
(reconcile/abandon), never an automatic retry. Repair never deletes the item's
original provenance — it appends.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id, utc_now


class RepairError(DomainError):
    pass


class RepairStatus(StrEnum):
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    RECONCILED = "RECONCILED"
    RESOLVED = "RESOLVED"
    ABANDONED = "ABANDONED"


@dataclass(frozen=True, slots=True)
class RepairItem:
    repair_id: str
    subject_ref: str                 # run/delivery/work ref needing repair
    reason: str
    safe_to_retry: bool              # False → blind retry forbidden, needs resolution
    provenance_refs: tuple[str, ...]
    status: RepairStatus = RepairStatus.REPAIR_REQUIRED
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class AuditEntry:
    repair_id: str
    action: str
    operator: str
    at: datetime = field(default_factory=utc_now)


class RepairService:
    def __init__(self) -> None:
        self._items: dict[str, RepairItem] = {}
        self._audit: list[AuditEntry] = []
        self._operators: set[str] = set()

    def authorize(self, operator: str) -> None:
        self._operators.add(operator)

    def record_repair_required(self, item: RepairItem) -> RepairItem:
        # Never overwrite an existing item's provenance.
        if item.repair_id in self._items:
            raise RepairError(f"repair item exists: {item.repair_id}")
        self._items[item.repair_id] = item
        return item

    def list_required(self) -> list[RepairItem]:
        return [i for i in self._items.values() if i.status == RepairStatus.REPAIR_REQUIRED]

    def _act(self, repair_id: str, operator: str, action: str) -> RepairItem:
        if operator not in self._operators:
            raise RepairError(f"operator {operator} not authorized")
        item = self._items[repair_id]
        self._audit.append(AuditEntry(repair_id, action, operator))
        return item

    def retry(self, repair_id: str, operator: str) -> RepairItem:
        item = self._act(repair_id, operator, "retry")
        if not item.safe_to_retry:
            raise RepairError("side-effect not blind-retryable; use reconcile/resolve")
        updated = replace(item, status=RepairStatus.RESOLVED)
        self._items[repair_id] = updated
        return updated

    def reconcile(self, repair_id: str, operator: str, *, outcome_ref: str) -> RepairItem:
        item = self._act(repair_id, operator, "reconcile")
        # provenance preserved; a reconcile outcome ref is appended.
        updated = replace(item, status=RepairStatus.RECONCILED,
                          provenance_refs=(*item.provenance_refs, outcome_ref))
        self._items[repair_id] = updated
        return updated

    def resolve(self, repair_id: str, operator: str) -> RepairItem:
        item = self._act(repair_id, operator, "resolve")
        updated = replace(item, status=RepairStatus.RESOLVED)
        self._items[repair_id] = updated
        return updated

    def abandon(self, repair_id: str, operator: str) -> RepairItem:
        item = self._act(repair_id, operator, "abandon")
        updated = replace(item, status=RepairStatus.ABANDONED)
        self._items[repair_id] = updated
        return updated

    def audit_trail(self) -> list[AuditEntry]:
        return list(self._audit)
