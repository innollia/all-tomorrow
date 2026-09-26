from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable

from all_tomorrow.domain.errors import ErrorCategory, InvariantViolationError
from all_tomorrow.domain.state import RunRecord


class OperationClass(StrEnum):
    MODEL_INVOCATION = "MODEL_INVOCATION"
    READ_ONLY_TOOL = "READ_ONLY_TOOL"
    IDEMPOTENT_MUTATION = "IDEMPOTENT_MUTATION"
    RECONCILE_BEFORE_RETRY_MUTATION = "RECONCILE_BEFORE_RETRY_MUTATION"
    WORKER_PROCESS = "WORKER_PROCESS"
    DURABLE_START_RECONCILE = "DURABLE_START_RECONCILE"
    USER_REQUEST_SEMANTIC_REPLAN = "USER_REQUEST_SEMANTIC_REPLAN"


@dataclass(frozen=True, slots=True)
class OperationRetryPolicy:
    """Retry, timeout, and backoff policy for a specific operation class.

    Requirements:
    - S0-00B4-01: Exactly one primary retry owner per operation class.
    - S0-00B4-02: Nested defaults sum does not exceed total timeout / policy ceiling.
    """
    operation_class: OperationClass
    primary_retry_owner: str
    retryable_categories: frozenset[ErrorCategory]
    max_attempts: int
    per_attempt_timeout_seconds: float
    total_timeout_seconds: float
    backoff_seconds: float
    backoff_jitter: bool
    idempotency_required: bool
    exhausted_transition: str
    telemetry_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.primary_retry_owner or not self.primary_retry_owner.strip():
            raise ValueError("OperationRetryPolicy.primary_retry_owner must be non-empty")
        if self.max_attempts < 1:
            raise ValueError("OperationRetryPolicy.max_attempts must be >= 1")
        if self.per_attempt_timeout_seconds <= 0:
            raise ValueError("per_attempt_timeout_seconds must be positive")
        if self.total_timeout_seconds < self.per_attempt_timeout_seconds:
            raise ValueError("total_timeout_seconds cannot be less than per_attempt_timeout_seconds")
        # S0-00B4-02: Total ceiling check: per_attempt * max_attempts must be within bounded total ceiling
        if self.per_attempt_timeout_seconds * self.max_attempts > self.total_timeout_seconds * 1.5:
            raise InvariantViolationError(
                f"Policy ceiling exceeded: {self.max_attempts} attempts of {self.per_attempt_timeout_seconds}s "
                f"exceeds ceiling for total timeout {self.total_timeout_seconds}s"
            )


@dataclass(frozen=True, slots=True)
class ReplanStormProtection:
    """S0-00B4-03: Replan storm upper bound and error fingerprint suppression."""
    max_replan_runs_per_work: int = 3
    suppress_repeated_error_fingerprint: bool = True
    exhausted_action: str = "NEED_USER"

    def __post_init__(self) -> None:
        if self.max_replan_runs_per_work < 1:
            raise ValueError("max_replan_runs_per_work must be >= 1")
        if self.max_replan_runs_per_work > 10:
            raise InvariantViolationError(
                f"Replan storm upper bound violated: max_replan_runs_per_work={self.max_replan_runs_per_work} > 10"
            )


@dataclass(frozen=True, slots=True)
class UsageObservation:
    """S0-00B4-04: Cost and elapsed observations where unknown is NOT coerced to 0."""
    elapsed_seconds: float | None = None
    cost_usd: float | None = None
    observation_ref: str = ""

    def get_elapsed_seconds(self) -> float:
        if self.elapsed_seconds is None:
            raise InvariantViolationError("Unknown elapsed_seconds must not be coerced to 0.0")
        return self.elapsed_seconds

    def get_cost_usd(self) -> float:
        if self.cost_usd is None:
            raise InvariantViolationError("Unknown cost_usd must not be coerced to 0.0")
        return self.cost_usd


class ExecutionPolicyRegistry:
    """Central registry and validator for execution policies."""

    def __init__(
        self,
        policies: Iterable[OperationRetryPolicy],
        replan_protection: ReplanStormProtection | None = None,
    ) -> None:
        self._policies: dict[OperationClass, OperationRetryPolicy] = {}
        for policy in policies:
            # S0-00B4-01: Exactly one primary retry owner per failure/operation class
            if policy.operation_class in self._policies:
                existing = self._policies[policy.operation_class]
                raise InvariantViolationError(
                    f"Duplicate retry policy for {policy.operation_class}: "
                    f"existing owner '{existing.primary_retry_owner}' vs new owner '{policy.primary_retry_owner}'"
                )
            self._policies[policy.operation_class] = policy

        self.replan_protection = replan_protection or ReplanStormProtection()

    def get_policy(self, op_class: OperationClass) -> OperationRetryPolicy:
        if op_class not in self._policies:
            raise KeyError(f"No policy registered for {op_class}")
        return self._policies[op_class]

    def evaluate_replan(
        self,
        work_past_runs: list[RunRecord],
        new_error_fingerprint: str | None = None,
        past_error_fingerprints: tuple[str, ...] = (),
    ) -> tuple[bool, str]:
        """S0-00B4-03: Evaluates whether a new replan Run can be started for a Work."""
        if len(work_past_runs) >= self.replan_protection.max_replan_runs_per_work:
            return False, f"Replan budget exhausted ({len(work_past_runs)} >= {self.replan_protection.max_replan_runs_per_work})"

        if self.replan_protection.suppress_repeated_error_fingerprint and new_error_fingerprint:
            # If the same error fingerprint repeated 2+ times consecutively, suppress replan
            if past_error_fingerprints and past_error_fingerprints[-1] == new_error_fingerprint:
                return False, f"Suppressed repeated identical error fingerprint: {new_error_fingerprint}"

        return True, "OK"
