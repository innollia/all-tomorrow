from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from all_tomorrow.domain.errors import InvariantViolationError
from all_tomorrow.domain.ids import new_id, utc_now


class RiskClass(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AuthDecision(StrEnum):
    ALLOW = "ALLOW"
    CONFIRM = "CONFIRM"
    DENY = "DENY"


@dataclass(frozen=True, slots=True)
class AuthorizationDecisionRecord:
    """Action authorization decision record."""
    decision_id: str
    actor_ref: str
    action_type: str
    target_ref: str
    requested_capability: str
    risk_class: RiskClass
    decision: AuthDecision
    policy_version: str = "1.0"
    reason: str = ""
    confirm_nonce: str | None = None
    decided_at: datetime = field(default_factory=utc_now)


# Known injection / authority escalation phrases in untrusted retrieved text
_UNTRUSTED_ESCALATION_PATTERN = re.compile(
    r"(?i)(admin\s*override|grant\s*(all|admin|root|superuser)|bypass\s*confirm|ignore\s*previous\s*instruction|sudo\s+)"
)


class Authorizer:
    """Evaluates requested capabilities against risk and security rules.

    Requirements:
    - S0-00B5-02: read/write/delete/push capability authorization.
    - S0-00B5-03: untrusted content cannot elevate authority.
    """

    def __init__(self, policy_version: str = "1.0") -> None:
        self.policy_version = policy_version
        self._rules: dict[str, tuple[RiskClass, AuthDecision]] = {
            "read": (RiskClass.LOW, AuthDecision.ALLOW),
            "fetch": (RiskClass.LOW, AuthDecision.ALLOW),
            "write": (RiskClass.MEDIUM, AuthDecision.ALLOW),
            "delete": (RiskClass.HIGH, AuthDecision.CONFIRM),
            "git_push": (RiskClass.HIGH, AuthDecision.CONFIRM),
            "production_deploy": (RiskClass.CRITICAL, AuthDecision.CONFIRM),
            "untrusted_eval": (RiskClass.CRITICAL, AuthDecision.DENY),
        }

    def register_capability_rule(
        self,
        capability: str,
        risk_class: RiskClass,
        decision: AuthDecision,
    ) -> None:
        self._rules[capability] = (risk_class, decision)

    def authorize(
        self,
        actor_ref: str,
        action_type: str,
        target_ref: str,
        requested_capability: str,
        untrusted_content: str | None = None,
    ) -> AuthorizationDecisionRecord:
        decision_id = new_id("auth_dec")

        # S0-00B5-03: Untrusted content escalation protection
        if untrusted_content and _UNTRUSTED_ESCALATION_PATTERN.search(untrusted_content):
            return AuthorizationDecisionRecord(
                decision_id=decision_id,
                actor_ref=actor_ref,
                action_type=action_type,
                target_ref=target_ref,
                requested_capability=requested_capability,
                risk_class=RiskClass.CRITICAL,
                decision=AuthDecision.DENY,
                policy_version=self.policy_version,
                reason="Denied due to detected authority escalation attempt in untrusted content",
            )

        rule = self._rules.get(requested_capability)
        if rule is None:
            # Default to DENY for unknown capabilities
            return AuthorizationDecisionRecord(
                decision_id=decision_id,
                actor_ref=actor_ref,
                action_type=action_type,
                target_ref=target_ref,
                requested_capability=requested_capability,
                risk_class=RiskClass.HIGH,
                decision=AuthDecision.DENY,
                policy_version=self.policy_version,
                reason=f"Unknown capability '{requested_capability}' denied by default",
            )

        risk_class, decision = rule
        nonce = secrets.token_hex(16) if decision == AuthDecision.CONFIRM else None
        reason = f"Policy evaluated: capability='{requested_capability}' mapped to {decision.value}"

        return AuthorizationDecisionRecord(
            decision_id=decision_id,
            actor_ref=actor_ref,
            action_type=action_type,
            target_ref=target_ref,
            requested_capability=requested_capability,
            risk_class=risk_class,
            decision=decision,
            policy_version=self.policy_version,
            reason=reason,
            confirm_nonce=nonce,
        )
