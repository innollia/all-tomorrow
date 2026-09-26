"""Tools and deterministic agent components for 00A-1 Common Harness.

Includes:
- Exactly one read-only tool
- Exactly one idempotency-guarded mutation tool stub
- Test hooks for explicit process kill injection
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .fixtures import SideEffectFixtureStore, SideEffectRecord
from .types import FailPoint, KillException


def read_inventory_tool(item_id: str) -> Dict[str, Any]:
    """Read-only tool stub for the walking skeleton harness."""
    return {
        "item_id": item_id,
        "name": f"Inventory item {item_id}",
        "read_only": True,
        "stock": 42,
    }


def mutation_stub_tool(
    store: SideEffectFixtureStore,
    idempotency_key: str,
    value: str,
    kill_hook: Optional[Callable[[FailPoint], None]] = None,
    fail_point: FailPoint = FailPoint.NONE,
) -> SideEffectRecord:
    """Mutation tool stub writing to the SideEffectFixtureStore with idempotency."""
    return store.record_mutation(
        idempotency_key=idempotency_key,
        value=value,
        kill_hook=kill_hook,
        fail_point_to_trigger=fail_point,
    )


def default_kill_hook(point: FailPoint) -> None:
    """Default kill hook throwing KillException."""
    raise KillException(point)
