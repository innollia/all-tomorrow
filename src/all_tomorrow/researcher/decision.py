"""02B — Researcher typed decisions.

The researcher's model output is closed into an action-specific typed decision,
not a free-form payload. Action/payload mismatch, unknown or cross-owner
evidence, and arbitrary status/SQL/path/credential fields are rejected before any
downstream mutation. Malformed output is never heuristically "fixed" into a
mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError


DECISION_SCHEMA_VERSION = "1"


class DecisionValidationError(DomainError):
    """A decision failed schema/authority validation and must not materialize."""


class Action(StrEnum):
    NOOP = "NOOP"
    CREATE_GOAL = "CREATE_GOAL"
    CREATE_WORK = "CREATE_WORK"
    REVISE_WORK = "REVISE_WORK"
    ASK_USER = "ASK_USER"
    PROPOSE_IMPROVEMENT = "PROPOSE_IMPROVEMENT"


# Fields a model payload may NEVER carry directly (would be blind-copied to state).
_FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "semantic_status", "status", "sql", "query", "path", "cwd",
    "credential", "api_key", "token", "secret", "revision",
})


@dataclass(frozen=True, slots=True)
class Decision:
    """A validated typed decision. Construct via ``validate_decision``."""
    decision_id: str
    action: Action
    summary: str
    reason: str
    evidence_refs: tuple[str, ...]
    payload: dict
    prompt_version: str
    decision_schema_version: str = DECISION_SCHEMA_VERSION


# Required payload keys per action (presence + no forbidden keys enforced).
_REQUIRED: dict[Action, frozenset[str]] = {
    Action.NOOP: frozenset(),
    Action.CREATE_GOAL: frozenset({"title", "objective"}),
    Action.CREATE_WORK: frozenset({"target_goal_id", "title", "objective"}),
    Action.REVISE_WORK: frozenset({"target_work_id", "revision_intent"}),
    Action.ASK_USER: frozenset({"target_work_id", "question"}),
    Action.PROPOSE_IMPROVEMENT: frozenset({"target_type", "target_id", "candidate_intent"}),
}


def validate_decision(
    *,
    decision_id: str,
    action: str,
    summary: str,
    reason: str,
    evidence_refs: list[str] | tuple[str, ...],
    payload: dict,
    prompt_version: str,
    known_evidence_refs: frozenset[str],
    owner_scope_refs: frozenset[str],
) -> Decision:
    """Validate an untrusted model decision into a typed Decision, or reject.

    ``known_evidence_refs`` are refs the snapshot actually surfaced; anything else
    is unknown. ``owner_scope_refs`` are the refs in the caller's user/project
    scope; a ref outside it cannot be used without an authority check (rejected).
    """
    try:
        act = Action(action)
    except ValueError as exc:
        raise DecisionValidationError(f"unknown action: {action!r}") from exc

    # Action/payload mismatch: required keys present.
    required = _REQUIRED[act]
    missing = required - set(payload.keys())
    if missing:
        raise DecisionValidationError(f"{act} missing payload keys: {sorted(missing)}")

    # NOOP carries no payload.
    if act == Action.NOOP and payload:
        raise DecisionValidationError("NOOP must carry no payload")

    # No forbidden control fields may be blind-copied from the model.
    forbidden = _FORBIDDEN_PAYLOAD_KEYS & set(payload.keys())
    if forbidden:
        raise DecisionValidationError(f"{act} payload carries forbidden keys: {sorted(forbidden)}")

    # Evidence must be known and in-scope.
    for ref in evidence_refs:
        if ref not in known_evidence_refs:
            raise DecisionValidationError(f"unknown evidence ref: {ref}")
        if owner_scope_refs and ref not in owner_scope_refs:
            raise DecisionValidationError(f"cross-owner evidence ref not permitted: {ref}")

    # Referenced target ids that name an owned entity must be in scope.
    for key in ("target_goal_id", "target_work_id", "target_id"):
        val = payload.get(key)
        if val is not None and owner_scope_refs and val not in owner_scope_refs:
            raise DecisionValidationError(f"cross-owner target {key}={val} not permitted")

    return Decision(
        decision_id=decision_id,
        action=act,
        summary=summary,
        reason=reason,
        evidence_refs=tuple(evidence_refs),
        payload=dict(payload),
        prompt_version=prompt_version,
    )
