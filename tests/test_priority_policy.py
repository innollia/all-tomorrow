"""05C — User-Owned Priority Policy verification."""

from __future__ import annotations

from all_tomorrow.priority import (
    Commitment,
    PreemptionDecision,
    Priority,
    WorkPriorityInputs,
    aged_priority,
    classify_priority,
    outranks,
    preemption,
)


def test_hard_commitment_maps_p0_p1() -> None:
    assert classify_priority(WorkPriorityInputs(Commitment.HARD, urgent_safety=True)) == Priority.P0
    assert classify_priority(WorkPriorityInputs(Commitment.HARD)) == Priority.P1


def test_low_commitment_idea_not_urgent() -> None:
    p = classify_priority(WorkPriorityInputs(Commitment.AUTONOMOUS, low_commitment_idea=True))
    assert p == Priority.P6  # "재밌겠다/나중에" is background, never auto-P0


def test_active_request_outranks_autonomous() -> None:
    active = classify_priority(WorkPriorityInputs(Commitment.ACTIVE_REQUEST))
    auto = classify_priority(WorkPriorityInputs(Commitment.AUTONOMOUS))
    assert active == Priority.P2 and auto == Priority.P5
    assert outranks(active, auto)


def test_aging_bounded_never_past_p3() -> None:
    # P5 waiting a long time ages toward P3, never P2.
    assert aged_priority(Priority.P5, waited_steps=10) == Priority.P3
    assert aged_priority(Priority.P6, waited_steps=1) == Priority.P5
    # non-background priorities are unaffected by aging
    assert aged_priority(Priority.P2, waited_steps=10) == Priority.P2


def test_aging_never_beats_active_request() -> None:
    aged = aged_priority(Priority.P5, waited_steps=99)
    active = Priority.P2
    assert not outranks(aged, active)  # background never jumps the user's active request


def test_preemption_non_interruptible_mutation_not_killed() -> None:
    d = preemption(Priority.P0, Priority.P5, running_interruptible=False,
                   running_non_interruptible_mutation=True, backend_supports_pause=True)
    assert d == PreemptionDecision.DO_NOT_KILL


def test_preemption_cooperative_yield() -> None:
    d = preemption(Priority.P1, Priority.P5, running_interruptible=True,
                   running_non_interruptible_mutation=False, backend_supports_pause=True)
    assert d == PreemptionDecision.COOPERATIVE_YIELD


def test_preemption_block_new_background_when_no_pause() -> None:
    d = preemption(Priority.P1, Priority.P5, running_interruptible=True,
                   running_non_interruptible_mutation=False, backend_supports_pause=False)
    assert d == PreemptionDecision.BLOCK_NEW_BACKGROUND


def test_no_preemption_when_incoming_not_higher() -> None:
    d = preemption(Priority.P5, Priority.P2, running_interruptible=True,
                   running_non_interruptible_mutation=False, backend_supports_pause=True)
    assert d == PreemptionDecision.DISPATCH_HIGHER_FIRST
