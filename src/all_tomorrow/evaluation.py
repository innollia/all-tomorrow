from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from all_tomorrow.contracts import ContractError, new_id


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    SANDBOXED = "sandboxed"
    EVALUATED = "evaluated"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class EvaluationScore:
    dataset_id: str
    passed: int
    failed: int
    mean_score: float

    @property
    def total(self) -> int:
        return self.passed + self.failed


@dataclass(frozen=True, slots=True)
class ImprovementProposal:
    target_type: str
    target_id: str
    baseline_ref: str
    candidate_ref: str
    reason: str
    proposal_id: str = field(default_factory=lambda: new_id("proposal"))
    status: ProposalStatus = ProposalStatus.PROPOSED


@dataclass(frozen=True, slots=True)
class EvaluationDecision:
    proposal_id: str
    accepted: bool
    reason: str
    baseline: EvaluationScore
    candidate: EvaluationScore


class EvaluationService:
    """Produces promotion decisions; it never mutates production targets itself."""

    @staticmethod
    def compare(
        proposal: ImprovementProposal,
        baseline: EvaluationScore,
        candidate: EvaluationScore,
        *,
        minimum_cases: int = 1,
    ) -> EvaluationDecision:
        if baseline.dataset_id != candidate.dataset_id:
            raise ContractError("baseline and candidate must use the same dataset")
        if baseline.total < minimum_cases or candidate.total < minimum_cases:
            raise ContractError("evaluation does not meet minimum case count")
        no_regression = candidate.failed <= baseline.failed
        score_improved = candidate.mean_score > baseline.mean_score
        accepted = no_regression and score_improved
        reason = (
            "candidate improved mean score without increasing failures"
            if accepted
            else "candidate did not clear the no-regression promotion gate"
        )
        return EvaluationDecision(proposal.proposal_id, accepted, reason, baseline, candidate)

