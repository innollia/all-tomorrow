"""03D — Ordinary Promotion and Rollback.

Promotes an ordinary ACCEPTED candidate through a target-specific deployment
transaction, and rolls back to the exact previous immutable ref on regression.
The core knows no target filesystem/provider detail — targets implement
PromotionTarget.

Hard rules:
- stale baseline (current ref changed since ACCEPT) blocks promotion
- a target with no monitoring policy cannot auto-promote
- protected / unknown-classification candidates are never auto-applied
- apply/verify failure rolls back and is NOT recorded as success
- rollback returns to the exact previous ref and is idempotent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from all_tomorrow.domain.errors import DomainError


class PromotionError(DomainError):
    pass


class StaleBaselineError(PromotionError):
    pass


class ProtectedChangeError(PromotionError):
    """Protected or unknown-classification change cannot be auto-promoted."""


class MissingMonitoringPolicyError(PromotionError):
    pass


class ProtectionClass(StrEnum):
    ORDINARY = "ORDINARY"
    PROTECTED = "PROTECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MonitoringPolicy:
    min_observations: int
    hard_rollback_signals: tuple[str, ...]
    tolerance: int = 0


@dataclass(frozen=True, slots=True)
class DeploymentPlan:
    candidate_ref: str
    previous_ref: str
    steps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeploymentRef:
    deployment_id: str
    candidate_ref: str
    previous_ref: str


class PromotionTarget(Protocol):
    def inspect_current(self) -> str: ...                         # immutable current ref/hash
    def validate_candidate(self, candidate_ref: str) -> bool: ...
    def plan(self, candidate_ref: str, current_ref: str) -> DeploymentPlan: ...
    def apply(self, plan: DeploymentPlan) -> DeploymentRef: ...
    def verify(self, deployment: DeploymentRef) -> bool: ...
    def rollback(self, previous_ref: str, deployment: DeploymentRef) -> str: ...


@dataclass(frozen=True, slots=True)
class PromotionResult:
    promoted: bool
    deployment: DeploymentRef | None
    rolled_back: bool = False
    reason: str | None = None


class Promoter:
    def __init__(self, target: PromotionTarget) -> None:
        self.target = target

    def promote(
        self,
        *,
        candidate_ref: str,
        accepted_baseline_ref: str,
        protection_class: ProtectionClass,
        monitoring_policy: MonitoringPolicy | None,
    ) -> PromotionResult:
        # Protected/unknown → never auto-promote (fail-closed).
        if protection_class != ProtectionClass.ORDINARY:
            raise ProtectedChangeError(f"{protection_class} candidate requires approval, no auto-promote")
        # No monitoring policy → no auto-promote (no hidden default window).
        if monitoring_policy is None:
            raise MissingMonitoringPolicyError("monitoring policy required for auto-promotion")

        # Re-confirm baseline is not stale (current ref must equal what we ACCEPTED against).
        current = self.target.inspect_current()
        if current != accepted_baseline_ref:
            raise StaleBaselineError(f"baseline drifted: current={current} accepted={accepted_baseline_ref}")

        if not self.target.validate_candidate(candidate_ref):
            raise PromotionError("candidate validation failed")

        plan = self.target.plan(candidate_ref, current)
        deployment = self.target.apply(plan)

        if not self.target.verify(deployment):
            # apply/verify failure → rollback, NOT recorded as success.
            self.target.rollback(current, deployment)
            return PromotionResult(promoted=False, deployment=deployment, rolled_back=True,
                                   reason="verify failed; rolled back")
        return PromotionResult(promoted=True, deployment=deployment)

    def rollback(self, previous_ref: str, deployment: DeploymentRef) -> str:
        """Rollback to the exact previous ref; idempotent (repeat is a no-op)."""
        result_ref = self.target.rollback(previous_ref, deployment)
        # idempotency is the target's responsibility; a second call returns the same ref.
        return result_ref
