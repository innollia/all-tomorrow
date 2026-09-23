from __future__ import annotations

import asyncio
import pytest

from all_tomorrow.domain.errors import (
    ActiveRunLimitExceededError,
    CanonicalError,
    ErrorCategory,
    InvalidStateTransitionError,
    MissingCompletionEvidenceError,
    TerminalReviveError,
    WorkExecutionRefForbiddenError,
)
from all_tomorrow.error_normalization import normalize_exception


class DummyHttpException(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class TestErrorNormalization:
    """S0-00B2-05: Backend/vendor exception to CanonicalError mapping."""

    def test_not_found_and_unavailable_separation(self) -> None:
        """CRITICAL: NOT_FOUND and UNAVAILABLE must never be merged."""
        # NOT_FOUND from 404
        err_404 = normalize_exception(DummyHttpException(404, "Workflow not found"))
        assert err_404.category == ErrorCategory.NOT_FOUND
        assert err_404.category != ErrorCategory.UNAVAILABLE
        assert err_404.retryability is False

        # NOT_FOUND from KeyError
        err_key = normalize_exception(KeyError("execution_123 not found"))
        assert err_key.category == ErrorCategory.NOT_FOUND
        assert err_key.category != ErrorCategory.UNAVAILABLE

        # UNAVAILABLE from ConnectionRefusedError
        err_conn = normalize_exception(ConnectionRefusedError("Could not connect to DBOS"))
        assert err_conn.category == ErrorCategory.UNAVAILABLE
        assert err_conn.category != ErrorCategory.NOT_FOUND
        assert err_conn.retryability is True

        # UNAVAILABLE from 503
        err_503 = normalize_exception(DummyHttpException(503, "Service unavailable"))
        assert err_503.category == ErrorCategory.UNAVAILABLE
        assert err_503.category != ErrorCategory.NOT_FOUND

    def test_timeout_and_ambiguous_effect_distinction(self) -> None:
        """CRITICAL: TIMEOUT must preserve ambiguity flag for possible in-flight side effects."""
        err_timeout = normalize_exception(TimeoutError("Operation timed out after 30s"))
        assert err_timeout.category == ErrorCategory.TIMEOUT
        assert err_timeout.ambiguity is True
        assert err_timeout.retryability is True

    def test_rate_limiting_normalization(self) -> None:
        err_429 = normalize_exception(DummyHttpException(429, "Rate limit reached"))
        assert err_429.category == ErrorCategory.RATE_LIMITED
        assert err_429.retryability is True
        assert err_429.ambiguity is False

    def test_auth_and_permission_normalization(self) -> None:
        err_401 = normalize_exception(DummyHttpException(401, "Invalid token"))
        assert err_401.category == ErrorCategory.AUTHENTICATION_FAILED
        assert err_401.authority_security_relevance is True
        assert err_401.retryability is False

        err_403 = normalize_exception(DummyHttpException(403, "Forbidden tool"))
        assert err_403.category == ErrorCategory.PERMISSION_DENIED
        assert err_403.authority_security_relevance is True
        assert err_403.retryability is False

    def test_invariant_and_domain_error_normalization(self) -> None:
        err_revive = normalize_exception(TerminalReviveError("Cannot revive terminal Work"))
        assert err_revive.category == ErrorCategory.INVARIANT_VIOLATION
        assert err_revive.retryability is False

        err_active = normalize_exception(ActiveRunLimitExceededError("Two active runs forbidden"))
        assert err_active.category == ErrorCategory.INVARIANT_VIOLATION
        assert err_active.retryability is False

        err_exec = normalize_exception(WorkExecutionRefForbiddenError("ExecutionRef forbidden on Work"))
        assert err_exec.category == ErrorCategory.INVARIANT_VIOLATION

        err_transition = normalize_exception(InvalidStateTransitionError("Illegal transition"))
        assert err_transition.category == ErrorCategory.INVALID_STATE

        err_evidence = normalize_exception(MissingCompletionEvidenceError("Missing evidence"))
        assert err_evidence.category == ErrorCategory.INVALID_STATE
