"""03A — Improvement & Evaluation persistence.

Promotes ImprovementProposal / EvaluationCriteria / EvaluationRun into a durable
lifecycle with immutable refs and versioned, frozen criteria. Once a proposal is
ACCEPTED, a change to the candidate hash invalidates prior evaluations/approvals
(the proposal goes STALE) — a candidate can never rewrite its own evaluation
record.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError, InvalidStateTransitionError
from all_tomorrow.domain.ids import new_id, utc_now


class ProposalStatus(StrEnum):
    PROPOSED = "PROPOSED"
    SANDBOXED = "SANDBOXED"
    EVALUATED = "EVALUATED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    STALE = "STALE"


_TRANSITIONS: dict[ProposalStatus, frozenset[ProposalStatus]] = {
    ProposalStatus.PROPOSED: frozenset({ProposalStatus.SANDBOXED, ProposalStatus.REJECTED, ProposalStatus.STALE}),
    ProposalStatus.SANDBOXED: frozenset({ProposalStatus.EVALUATED, ProposalStatus.REJECTED, ProposalStatus.STALE}),
    ProposalStatus.EVALUATED: frozenset({ProposalStatus.ACCEPTED, ProposalStatus.REJECTED, ProposalStatus.APPROVAL_REQUIRED, ProposalStatus.STALE}),
    ProposalStatus.APPROVAL_REQUIRED: frozenset({ProposalStatus.ACCEPTED, ProposalStatus.REJECTED, ProposalStatus.STALE}),
    ProposalStatus.ACCEPTED: frozenset({ProposalStatus.PROMOTED, ProposalStatus.STALE, ProposalStatus.REJECTED}),
    ProposalStatus.PROMOTED: frozenset({ProposalStatus.ROLLED_BACK}),
    ProposalStatus.REJECTED: frozenset(),
    ProposalStatus.ROLLED_BACK: frozenset(),
    ProposalStatus.STALE: frozenset(),
}


class ProposalError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class ImprovementProposal:
    proposal_id: str
    target_type: str
    target_id: str
    baseline_hash: str
    reason: str
    protection_class: str
    status: ProposalStatus = ProposalStatus.PROPOSED
    candidate_hash: str | None = None      # set once sandboxed
    criteria_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    source_goal_id: str | None = None
    revision: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class EvaluationCriteria:
    """Frozen BEFORE candidate execution; content-hashed and immutable."""
    criteria_id: str
    proposal_id: str
    required_metrics: tuple[str, ...]
    hard_invariants: tuple[str, ...]
    content_hash: str
    frozen_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    evaluation_id: str
    proposal_id: str
    criteria_ref: str
    baseline_hash: str
    candidate_hash: str
    decision: str            # ACCEPT / REJECT / INCONCLUSIVE
    reason: str
    evaluator_version: str
    created_at: datetime = field(default_factory=utc_now)


class ImprovementStore:
    """In-memory reference store with legal-transition + immutability guards."""

    def __init__(self) -> None:
        self._proposals: dict[str, ImprovementProposal] = {}
        self._criteria: dict[str, EvaluationCriteria] = {}
        self._evaluations: dict[str, list[EvaluationRun]] = {}

    def create_proposal(self, p: ImprovementProposal) -> ImprovementProposal:
        if p.proposal_id in self._proposals:
            raise ProposalError(f"proposal exists: {p.proposal_id}")
        self._proposals[p.proposal_id] = p
        return p

    def get(self, proposal_id: str) -> ImprovementProposal | None:
        return self._proposals.get(proposal_id)

    def transition(self, proposal_id: str, target: ProposalStatus, expected_revision: int) -> ImprovementProposal:
        cur = self._proposals[proposal_id]
        if cur.revision != expected_revision:
            raise ProposalError(f"proposal {proposal_id} revision conflict")
        if target not in _TRANSITIONS.get(cur.status, frozenset()):
            raise InvalidStateTransitionError(f"illegal proposal transition {cur.status}->{target}")
        updated = replace(cur, status=target, revision=cur.revision + 1, updated_at=utc_now())
        self._proposals[proposal_id] = updated
        return updated

    def sandbox_candidate(self, proposal_id: str, candidate_hash: str, expected_revision: int) -> ImprovementProposal:
        cur = self._proposals[proposal_id]
        if cur.revision != expected_revision:
            raise ProposalError("revision conflict")
        updated = replace(
            self.transition(proposal_id, ProposalStatus.SANDBOXED, expected_revision),
            candidate_hash=candidate_hash,
        )
        self._proposals[proposal_id] = updated
        return updated

    def freeze_criteria(self, criteria: EvaluationCriteria, expected_revision: int) -> EvaluationCriteria:
        """Criteria must be frozen while the proposal is SANDBOXED, before EVALUATED."""
        p = self._proposals[criteria.proposal_id]
        if p.status not in (ProposalStatus.SANDBOXED,):
            raise ProposalError(f"criteria must be frozen before evaluation (status={p.status})")
        self._criteria[criteria.criteria_id] = criteria
        self._proposals[criteria.proposal_id] = replace(
            p, criteria_ref=criteria.criteria_id, revision=p.revision + 1
        )
        return criteria

    def record_evaluation(self, ev: EvaluationRun) -> EvaluationRun:
        p = self._proposals[ev.proposal_id]
        # A candidate hash that no longer matches the proposal invalidates the run.
        if p.candidate_hash is not None and ev.candidate_hash != p.candidate_hash:
            raise ProposalError("evaluation candidate hash does not match proposal candidate")
        self._evaluations.setdefault(ev.proposal_id, []).append(ev)
        return ev

    def invalidate_if_candidate_changed(self, proposal_id: str, new_candidate_hash: str) -> ImprovementProposal:
        """If an ACCEPTED proposal's candidate hash changes, prior evals are void → STALE."""
        p = self._proposals[proposal_id]
        if p.candidate_hash is not None and new_candidate_hash != p.candidate_hash:
            if p.status in (ProposalStatus.ACCEPTED, ProposalStatus.EVALUATED, ProposalStatus.APPROVAL_REQUIRED):
                stale = replace(p, status=ProposalStatus.STALE, revision=p.revision + 1, updated_at=utc_now())
                self._proposals[proposal_id] = stale
                return stale
        return p

    def evaluations(self, proposal_id: str) -> list[EvaluationRun]:
        return list(self._evaluations.get(proposal_id, []))
