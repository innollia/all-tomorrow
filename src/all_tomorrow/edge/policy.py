from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from all_tomorrow.contracts import ContractError


class EdgeAction(StrEnum):
    LOCAL_REPLY = "LOCAL_REPLY"
    LOCAL_TOOL = "LOCAL_TOOL"
    CENTRAL_QUERY = "CENTRAL_QUERY"
    CENTRAL_TASK = "CENTRAL_TASK"
    PROJECT_ACTION = "PROJECT_ACTION"
    USER_CLARIFICATION = "USER_CLARIFICATION"


@dataclass(frozen=True, slots=True)
class EdgeAnalysis:
    intent: str
    needs_shared_memory: bool = False
    needs_project_state: bool = False
    needs_cross_project_knowledge: bool = False
    needs_remote_tool: bool = False
    needs_long_running_task: bool = False
    needs_canonical_mutation: bool = False
    tool_risk: str | None = None

    @property
    def escalation_signals(self) -> frozenset[str]:
        names = (
            "needs_shared_memory",
            "needs_project_state",
            "needs_cross_project_knowledge",
            "needs_remote_tool",
            "needs_long_running_task",
            "needs_canonical_mutation",
        )
        return frozenset(name for name in names if getattr(self, name))


@dataclass(frozen=True, slots=True)
class _Rule:
    when: dict[str, Any]
    action: EdgeAction
    reason: str


@dataclass(frozen=True, slots=True)
class EdgeDecision:
    action: EdgeAction
    reason: str
    matched_rule: int | None


class EdgePolicy:
    def __init__(self, policy_id: str, rules: tuple[_Rule, ...], default_action: EdgeAction) -> None:
        self.policy_id = policy_id
        self.rules = rules
        self.default_action = default_action

    def decide(self, analysis: EdgeAnalysis) -> EdgeDecision:
        for index, rule in enumerate(self.rules):
            if self._matches(rule.when, analysis):
                return EdgeDecision(rule.action, rule.reason, index)
        return EdgeDecision(self.default_action, "default policy action", None)

    @staticmethod
    def _matches(condition: dict[str, Any], analysis: EdgeAnalysis) -> bool:
        for name, expected in condition.items():
            if name == "any_escalation_signal":
                if bool(analysis.escalation_signals) is not bool(expected):
                    return False
                continue
            if not hasattr(analysis, name):
                raise ContractError(f"unknown edge signal: {name}")
            if getattr(analysis, name) != expected:
                return False
        return True


def load_edge_policy(path: str | Path) -> EdgePolicy:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContractError("edge policy must be a mapping")
    policy_id = data.get("id")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise ContractError("edge policy id must be a non-empty string")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        raise ContractError("edge policy rules must be a list")
    rules: list[_Rule] = []
    for index, item in enumerate(raw_rules):
        if not isinstance(item, dict) or not isinstance(item.get("when"), dict):
            raise ContractError(f"edge policy rule {index} requires a when mapping")
        try:
            action = EdgeAction(item["action"])
        except (KeyError, ValueError) as error:
            raise ContractError(f"edge policy rule {index} has invalid action") from error
        reason = item.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            raise ContractError(f"edge policy rule {index} requires a reason")
        rules.append(_Rule(when=item["when"], action=action, reason=reason))
    try:
        default_action = EdgeAction(data.get("default_action", "USER_CLARIFICATION"))
    except ValueError as error:
        raise ContractError("edge policy default_action is invalid") from error
    return EdgePolicy(policy_id, tuple(rules), default_action)

