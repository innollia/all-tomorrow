"""04G — Operational alerts: rule catalog + evaluator.

Encodes the minimum operational signals from operations-security-contract.md as
declarative rules, plus a pure evaluator so at least one alert path is actually
verified (S1-04G-03). No secret value ever appears in an alert; only ids,
counts, and non-secret categories (OPERATIONAL_METADATA).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class AlertRule:
    alert_id: str
    description: str
    metric: str            # metric/query name the collector exposes
    threshold: float
    window_seconds: int
    severity: Severity
    destination: str       # notification channel
    runbook_ref: str
    comparison: str = ">="  # >=, >, ==

    def _cmp(self, value: float) -> bool:
        if self.comparison == ">=":
            return value >= self.threshold
        if self.comparison == ">":
            return value > self.threshold
        if self.comparison == "==":
            return value == self.threshold
        raise ValueError(f"unsupported comparison: {self.comparison}")


@dataclass(frozen=True, slots=True)
class AlertEvent:
    alert_id: str
    severity: Severity
    value: float
    threshold: float
    destination: str
    runbook_ref: str


# Minimum operational signals (operations-security-contract.md §SLO/alerts).
ALERT_CATALOG: tuple[AlertRule, ...] = (
    AlertRule("reconciliation_stuck", "STARTING/no-ref Runs not reconciled in window",
              "runs_starting_no_ref_age_seconds", 900, 300, Severity.CRITICAL,
              "ops-oncall", "docs/deploy/aws-single-node.md#reconciliation", ">="),
    AlertRule("delivery_repair_required", "Delivery in REPAIR_REQUIRED",
              "delivery_repair_required_count", 1, 300, Severity.CRITICAL,
              "ops-oncall", "docs/deploy/aws-single-node.md#restore", ">="),
    AlertRule("run_replan_storm", "Repeated Run failure/replan storm",
              "run_failures_per_5m", 10, 300, Severity.WARNING,
              "ops-oncall", "docs/ops/secrets-and-alerts.md#replan-storm", ">="),
    AlertRule("budget_exhausted", "Token/resource budget exhausted",
              "budget_remaining_ratio", 0.0, 60, Severity.WARNING,
              "ops-oncall", "docs/ops/secrets-and-alerts.md#budget", "=="),
    AlertRule("backup_stale", "Backup failed or stale",
              "backup_age_seconds", 7200, 300, Severity.CRITICAL,
              "ops-oncall", "docs/deploy/aws-single-node.md#persistence--backup", ">="),
    AlertRule("durable_unavailable", "Durable backend unavailable",
              "durable_health", 0, 60, Severity.CRITICAL,
              "ops-oncall", "docs/deploy/aws-single-node.md", "=="),
    AlertRule("gateway_unavailable", "Model/tool gateway unavailable",
              "gateway_health", 0, 60, Severity.CRITICAL,
              "ops-oncall", "config/litellm-proxy.example.yaml", "=="),
    AlertRule("auth_attack", "Approval/auth attack threshold",
              "auth_failures_per_5m", 5, 300, Severity.CRITICAL,
              "security-oncall", "src/all_tomorrow/approval.py", ">="),
    AlertRule("report_trigger_missed", "Report/trigger missed",
              "missed_fires_count", 1, 3600, Severity.WARNING,
              "ops-oncall", "docs/ops/secrets-and-alerts.md#triggers", ">="),
    AlertRule("storage_pressure", "Disk/storage pressure",
              "disk_used_ratio", 0.9, 300, Severity.WARNING,
              "ops-oncall", "docs/ops/secrets-and-alerts.md#storage", ">="),
)

_BY_ID = {r.alert_id: r for r in ALERT_CATALOG}


def rule(alert_id: str) -> AlertRule:
    return _BY_ID[alert_id]


def evaluate(alert_id: str, value: float) -> AlertEvent | None:
    """Return an AlertEvent if the metric crosses the rule threshold, else None."""
    r = _BY_ID[alert_id]
    if r._cmp(value):
        return AlertEvent(
            alert_id=r.alert_id, severity=r.severity, value=value,
            threshold=r.threshold, destination=r.destination, runbook_ref=r.runbook_ref,
        )
    return None


def evaluate_all(metrics: dict[str, float]) -> list[AlertEvent]:
    """Evaluate every rule for which a metric is present."""
    events: list[AlertEvent] = []
    for r in ALERT_CATALOG:
        if r.metric in metrics:
            ev = evaluate(r.alert_id, metrics[r.metric])
            if ev is not None:
                events.append(ev)
    return events
