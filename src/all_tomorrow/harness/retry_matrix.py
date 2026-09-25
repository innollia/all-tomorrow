"""Retry Policy Matrix for 00A-1 Common Harness.

Documents and configures retry defaults across distinct architectural layers:
1. provider SDK
2. LiteLLM model gateway
3. PydanticAI
4. durable backend (DBOS / Restate)
5. All Tomorrow semantic Work retry

Ensures that multiple layers do not execute uncoordinated, nested retries on identical failures.
"""

from __future__ import annotations

from typing import Dict, List
from pydantic import BaseModel, Field


class LayerRetryPolicy(BaseModel):
    """Configuration and responsibility for a single retry layer."""

    layer_name: str
    default_retries: int | None
    max_retries: int | None
    backoff_strategy: str
    handled_failure_classes: List[str]
    is_retry_owner: bool = False
    notes: str = ""


class RetryMatrix(BaseModel):
    """Cross-layer retry coordination matrix to prevent cascaded duplicate retries."""

    layers: Dict[str, LayerRetryPolicy] = Field(default_factory=dict)

    @classmethod
    def standard_harness_matrix(cls) -> "RetryMatrix":
        """Desired ownership policy, not evidence that every client applies it.

        Unknown or backend-dependent defaults are None. Crash recovery is not
        equivalent to an exception retry count. Integration probes must verify
        the effective configuration before this policy is used in production.
        """
        return cls(
            layers={
                "provider_sdk": LayerRetryPolicy(
                    layer_name="provider_sdk",
                    default_retries=2,  # OpenAI SDK _constants.DEFAULT_MAX_RETRIES
                    max_retries=0,
                    backoff_strategy="none",
                    handled_failure_classes=[],
                    is_retry_owner=False,
                    notes="Delegated upstream to LiteLLM Gateway.",
                ),
                "litellm_gateway": LayerRetryPolicy(
                    layer_name="litellm_gateway",
                    default_retries=None,
                    max_retries=0,
                    backoff_strategy="exponential",
                    handled_failure_classes=[],
                    is_retry_owner=False,
                    notes="Disable router/provider retry; durable step owns transient transport errors.",
                ),
                "pydantic_ai": LayerRetryPolicy(
                    layer_name="pydantic_ai",
                    default_retries=1,
                    max_retries=1,
                    backoff_strategy="immediate",
                    handled_failure_classes=["validation_error", "structured_output_parse_error"],
                    is_retry_owner=True,
                    notes="Sole owner of prompt self-correction and output schema retries.",
                ),
                "durable_backend": LayerRetryPolicy(
                    layer_name="durable_backend",
                    default_retries=None,
                    max_retries=None,
                    backoff_strategy="candidate-specific; bounded application exception retry",
                    handled_failure_classes=["process_crash", "worker_heartbeat_timeout", "db_deadlock", "socket_timeout", "connection_refused", "http_429", "http_502", "http_503", "rate_limit"],
                    is_retry_owner=True,
                    notes="DBOS exception retries default disabled (step retries_allowed=False); Restate recovery policy is server-controlled. Configure separately from crash recovery.",
                ),
                "all_tomorrow_semantic_work": LayerRetryPolicy(
                    layer_name="all_tomorrow_semantic_work",
                    default_retries=0,  # Semantic Work retries are explicit Run allocations
                    max_retries=0,
                    backoff_strategy="linear_manual",
                    handled_failure_classes=["task_semantic_failure", "policy_rejection"],
                    is_retry_owner=True,
                    notes="Allocates distinct logical Run instances, never silently retrying within same run.",
                ),
            }
        )

    def validate_single_ownership(self, failure_class: str) -> bool:
        """Verify that exactly one layer is the active owner for a given failure class."""
        owners = [
            p.layer_name
            for p in self.layers.values()
            if p.is_retry_owner and failure_class in p.handled_failure_classes
        ]
        return len(owners) == 1
