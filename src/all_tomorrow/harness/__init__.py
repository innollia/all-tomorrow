"""00A-1 Common Harness package.

Provides walking-skeleton contracts, canonical test scenarios (D01-D12),
side-effect fixtures, and result schemas for evaluating durable execution candidates
(DBOS, Restate) without direct vendor dependencies in domain logic.
"""

from .adapter import BaselineMemoryAdapter, DurableAdapter
from .fixtures import (
    DuplicateMutationError,
    SideEffectFixtureStore,
    SideEffectRecord,
)
from .retry_matrix import LayerRetryPolicy, RetryMatrix
from .scenarios import ScenarioRunner
from .tools import default_kill_hook, mutation_stub_tool, read_inventory_tool
from .types import (
    ExecutionIdentity,
    FailPoint,
    HarnessInput,
    HarnessOutput,
    KillException,
    ScenarioId,
    ScenarioResult,
    TraceContext,
)

__all__ = [
    "DurableAdapter",
    "BaselineMemoryAdapter",
    "DuplicateMutationError",
    "SideEffectFixtureStore",
    "SideEffectRecord",
    "LayerRetryPolicy",
    "RetryMatrix",
    "ScenarioRunner",
    "default_kill_hook",
    "mutation_stub_tool",
    "read_inventory_tool",
    "ExecutionIdentity",
    "FailPoint",
    "HarnessInput",
    "HarnessOutput",
    "KillException",
    "ScenarioId",
    "ScenarioResult",
    "TraceContext",
]
