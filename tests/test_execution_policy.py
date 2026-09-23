from __future__ import annotations

import pytest

from all_tomorrow.domain.errors import ErrorCategory, InvariantViolationError
from all_tomorrow.domain.ids import new_run_id, new_work_id
from all_tomorrow.domain.state import RunRecord, RunStatus
from all_tomorrow.execution_policy import (
    ExecutionPolicyRegistry,
    OperationClass,
    OperationRetryPolicy,
    ReplanStormProtection,
    UsageObservation,
)


class TestExecutionPolicy:
    """Requirements S0-00B4-01 through S0-00B4-04."""

    def test_single_retry_owner_per_class(self) -> None:
        """S0-00B4-01: Exactly one primary retry owner per failure/operation class."""
        policy_model = OperationRetryPolicy(
            operation_class=OperationClass.MODEL_INVOCATION,
            primary_retry_owner="durable_backend_step",
            retryable_categories=frozenset({ErrorCategory.RATE_LIMITED, ErrorCategory.UNAVAILABLE}),
            max_attempts=3,
            per_attempt_timeout_seconds=30.0,
            total_timeout_seconds=90.0,
            backoff_seconds=2.0,
            backoff_jitter=True,
            idempotency_required=True,
            exhausted_transition="FAILED",
        )

        registry = ExecutionPolicyRegistry([policy_model])
        assert registry.get_policy(OperationClass.MODEL_INVOCATION).primary_retry_owner == "durable_backend_step"

        # Attempting to register another policy with a different or duplicate owner for the same class raises error
        duplicate_policy = OperationRetryPolicy(
            operation_class=OperationClass.MODEL_INVOCATION,
            primary_retry_owner="litellm_proxy",
            retryable_categories=frozenset({ErrorCategory.RATE_LIMITED}),
            max_attempts=2,
            per_attempt_timeout_seconds=15.0,
            total_timeout_seconds=45.0,
            backoff_seconds=1.0,
            backoff_jitter=False,
            idempotency_required=True,
            exhausted_transition="FAILED",
        )
        with pytest.raises(InvariantViolationError, match="Duplicate retry policy"):
            ExecutionPolicyRegistry([policy_model, duplicate_policy])

    def test_nested_defaults_cannot_exceed_policy_ceiling(self) -> None:
        """S0-00B4-02: Nested defaults sum cannot exceed policy ceiling."""
        # attempts * per_attempt = 10 * 30 = 300s, but total_timeout is only 60s -> violates ceiling
        with pytest.raises(InvariantViolationError, match="Policy ceiling exceeded"):
            OperationRetryPolicy(
                operation_class=OperationClass.READ_ONLY_TOOL,
                primary_retry_owner="tool_adapter",
                retryable_categories=frozenset({ErrorCategory.TIMEOUT}),
                max_attempts=10,
                per_attempt_timeout_seconds=30.0,
                total_timeout_seconds=60.0,
                backoff_seconds=1.0,
                backoff_jitter=False,
                idempotency_required=False,
                exhausted_transition="FAILED",
            )

    def test_replan_storm_upper_bound(self) -> None:
        """S0-00B4-03: User Work replan storm upper bound and repeated error suppression."""
        # Upper bound cannot exceed 10
        with pytest.raises(InvariantViolationError, match="Replan storm upper bound violated"):
            ReplanStormProtection(max_replan_runs_per_work=15)

        protection = ReplanStormProtection(max_replan_runs_per_work=3)
        registry = ExecutionPolicyRegistry([], replan_protection=protection)

        work_id = new_work_id()
        runs = [
            RunRecord(run_id=new_run_id(), work_id=work_id, status=RunStatus.FAILED),
            RunRecord(run_id=new_run_id(), work_id=work_id, status=RunStatus.FAILED),
        ]

        # 2 past runs, max 3: allowed
        can_replan, reason = registry.evaluate_replan(runs)
        assert can_replan is True

        # Repeated identical error fingerprint is suppressed
        can_replan_rep, reason_rep = registry.evaluate_replan(
            runs,
            new_error_fingerprint="fp_sql_syntax_error",
            past_error_fingerprints=("fp_sql_syntax_error",),
        )
        assert can_replan_rep is False
        assert "Suppressed repeated identical error fingerprint" in reason_rep

        # 3 past runs: budget exhausted
        runs.append(RunRecord(run_id=new_run_id(), work_id=work_id, status=RunStatus.FAILED))
        can_replan_ex, reason_ex = registry.evaluate_replan(runs)
        assert can_replan_ex is False
        assert "Replan budget exhausted" in reason_ex

    def test_unknown_cost_and_elapsed_not_coerced_to_zero(self) -> None:
        """S0-00B4-04: Unknown cost/elapsed must NOT be treated as 0."""
        obs = UsageObservation(elapsed_seconds=None, cost_usd=None)

        with pytest.raises(InvariantViolationError, match="Unknown elapsed_seconds must not be coerced to 0.0"):
            obs.get_elapsed_seconds()

        with pytest.raises(InvariantViolationError, match="Unknown cost_usd must not be coerced to 0.0"):
            obs.get_cost_usd()

        obs_valid = UsageObservation(elapsed_seconds=1.23, cost_usd=0.005)
        assert obs_valid.get_elapsed_seconds() == 1.23
        assert obs_valid.get_cost_usd() == 0.005
