"""05C — User-Owned Priority Policy.

Defines semantic priority so user commitments outrank autonomous background work,
plus safe preemption. Priority is derived from typed inputs (origin, commitment,
deadline, interruptibility), never from a raw domain string. Aging can nudge
P5/P6 up by one step but never past an active user request, and P0/P1 still
respect the non-interruptible mutation safety boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

PRIORITY_POLICY_VERSION = "1"


class Priority(IntEnum):
    P0 = 0  # urgent/safety/time-critical user commitment
    P1 = 1  # explicit high priority / near hard deadline
    P2 = 2  # current active user request
    P3 = 3  # scheduled user-owned Work
    P4 = 4  # proactive personal/manager Work
    P5 = 5  # autonomous research/self-improvement
    P6 = 6  # opportunistic maintenance/discovery


class Commitment(IntEnum):
    HARD = 0            # → P0/P1
    ACTIVE_REQUEST = 1  # → P2
    SCHEDULED = 2       # → P3
    PROACTIVE = 3       # → P4
    AUTONOMOUS = 4      # → P5
    OPPORTUNISTIC = 5   # → P6


@dataclass(frozen=True, slots=True)
class WorkPriorityInputs:
    commitment: Commitment
    explicit_high: bool = False
    near_hard_deadline: bool = False
    urgent_safety: bool = False
    interruptible: bool = True
    low_commitment_idea: bool = False   # "재밌겠다/나중에" → TODO candidate, not urgent


def classify_priority(inp: WorkPriorityInputs) -> Priority:
    """Map typed inputs to a semantic priority (policy-versioned)."""
    if inp.commitment == Commitment.HARD:
        return Priority.P0 if inp.urgent_safety else Priority.P1
    if inp.explicit_high or inp.near_hard_deadline:
        return Priority.P1
    # A low-commitment idea is never auto-urgent; it maps to background.
    if inp.low_commitment_idea:
        return Priority.P6
    return {
        Commitment.ACTIVE_REQUEST: Priority.P2,
        Commitment.SCHEDULED: Priority.P3,
        Commitment.PROACTIVE: Priority.P4,
        Commitment.AUTONOMOUS: Priority.P5,
        Commitment.OPPORTUNISTIC: Priority.P6,
    }[inp.commitment]


def aged_priority(base: Priority, waited_steps: int) -> Priority:
    """Age P5/P6 up by at most the waited steps, but never above P3.

    Aging alone never lifts autonomous work to P2 or above (an active user
    request), preventing starvation without letting background work jump the
    user's own request.
    """
    if base not in (Priority.P5, Priority.P6):
        return base
    aged = max(Priority.P3.value, base.value - max(0, waited_steps))
    return Priority(aged)


def outranks(a: Priority, b: Priority) -> bool:
    """True if priority ``a`` should dispatch before ``b`` (lower number wins)."""
    return a.value < b.value


class PreemptionDecision(IntEnum):
    DISPATCH_HIGHER_FIRST = 0   # pending: use backend priority/delay
    COOPERATIVE_YIELD = 1       # running + interruptible + safe boundary
    DO_NOT_KILL = 2             # running non-interruptible mutation: wait for boundary
    BLOCK_NEW_BACKGROUND = 3    # backend can't pause: stop new bg, finish current


def preemption(
    incoming: Priority,
    running: Priority,
    *,
    running_interruptible: bool,
    running_non_interruptible_mutation: bool,
    backend_supports_pause: bool,
) -> PreemptionDecision:
    """Decide how a higher-priority incoming Work preempts a running background Work."""
    if not outranks(incoming, running):
        return PreemptionDecision.DISPATCH_HIGHER_FIRST  # nothing to preempt
    if running_non_interruptible_mutation:
        # Never kill a non-interruptible external mutation mid-flight.
        return PreemptionDecision.DO_NOT_KILL
    if running_interruptible and backend_supports_pause:
        return PreemptionDecision.COOPERATIVE_YIELD
    # Backend cannot pause safely → don't start new bg, let current finish.
    return PreemptionDecision.BLOCK_NEW_BACKGROUND
