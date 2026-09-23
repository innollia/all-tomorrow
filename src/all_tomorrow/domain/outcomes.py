from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from all_tomorrow.domain.errors import MissingCompletionEvidenceError
from all_tomorrow.domain.ids import OutcomeId, new_outcome_id, utc_now


class TargetType(StrEnum):
    GOAL = "GOAL"
    WORK = "WORK"
    RUN = "RUN"
    EXPERIMENT = "EXPERIMENT"
    DEPLOYMENT = "DEPLOYMENT"


class OutcomeStatus(StrEnum):
    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class CompletionEvidence:
    """Verifiable proof that an outcome was satisfied according to policy."""
    criterion_ref: str
    evaluator_ref: str
    evaluator_version: str
    observed_values: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    recorded_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.criterion_ref or not self.criterion_ref.strip():
            raise ValueError("CompletionEvidence.criterion_ref must be non-empty")
        if not self.evaluator_ref or not self.evaluator_ref.strip():
            raise ValueError("CompletionEvidence.evaluator_ref must be non-empty")
        if not self.evaluator_version or not self.evaluator_version.strip():
            raise ValueError("CompletionEvidence.evaluator_version must be non-empty")


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    """Outcome evaluation record for a target entity."""
    outcome_id: OutcomeId
    target_type: TargetType
    target_id: str
    status: OutcomeStatus
    evidence: CompletionEvidence | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.target_id or not self.target_id.strip():
            raise ValueError("OutcomeRecord.target_id must be non-empty")
        if self.status == OutcomeStatus.SATISFIED and self.evidence is None:
            raise MissingCompletionEvidenceError(
                f"OutcomeRecord for {self.target_type}:{self.target_id} marked SATISFIED requires non-null CompletionEvidence"
            )


def verify_completion_evidence(
    target_type: TargetType,
    target_id: str,
    evidence: CompletionEvidence | OutcomeRecord | None,
) -> OutcomeRecord:
    """Validates that completion evidence is provided and satisfied before allowing SUCCEEDED transition."""
    if evidence is None:
        raise MissingCompletionEvidenceError(
            f"Cannot transition {target_type.value} '{target_id}' to SUCCEEDED without completion evidence"
        )
    if isinstance(evidence, CompletionEvidence):
        return OutcomeRecord(
            outcome_id=new_outcome_id(),
            target_type=target_type,
            target_id=target_id,
            status=OutcomeStatus.SATISFIED,
            evidence=evidence,
        )
    if isinstance(evidence, OutcomeRecord):
        if evidence.target_type != target_type or evidence.target_id != target_id:
            raise MissingCompletionEvidenceError(
                f"OutcomeRecord target mismatch: expected {target_type.value}:{target_id}, got {evidence.target_type.value}:{evidence.target_id}"
            )
        if evidence.status != OutcomeStatus.SATISFIED or evidence.evidence is None:
            raise MissingCompletionEvidenceError(
                f"OutcomeRecord for {target_type.value}:{target_id} is not SATISFIED (status={evidence.status.value})"
            )
        return evidence
    raise MissingCompletionEvidenceError(f"Invalid evidence type: {type(evidence)!r}")
