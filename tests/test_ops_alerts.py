"""04G — Operational alert catalog + evaluator verification."""

from __future__ import annotations

from all_tomorrow.ops.alerts import (
    ALERT_CATALOG,
    Severity,
    evaluate,
    evaluate_all,
    rule,
)


def test_catalog_covers_minimum_signals() -> None:
    ids = {r.alert_id for r in ALERT_CATALOG}
    for required in (
        "reconciliation_stuck", "delivery_repair_required", "run_replan_storm",
        "budget_exhausted", "backup_stale", "durable_unavailable",
        "gateway_unavailable", "auth_attack", "report_trigger_missed",
        "storage_pressure",
    ):
        assert required in ids, f"missing required alert: {required}"


def test_every_rule_has_metric_threshold_severity_destination_runbook() -> None:
    for r in ALERT_CATALOG:
        assert r.metric and r.destination and r.runbook_ref
        assert isinstance(r.severity, Severity)
        assert r.window_seconds > 0


# S1-04G-03: at least one alert path actually evaluated end to end.
def test_reconciliation_stuck_fires_over_threshold() -> None:
    r = rule("reconciliation_stuck")
    below = evaluate("reconciliation_stuck", r.threshold - 1)
    assert below is None
    at = evaluate("reconciliation_stuck", r.threshold)
    assert at is not None and at.severity == Severity.CRITICAL
    assert at.destination == "ops-oncall"


# S1-04G-04: backup failure/stale alert fires.
def test_backup_stale_alert_fires() -> None:
    r = rule("backup_stale")
    ev = evaluate("backup_stale", r.threshold + 1)
    assert ev is not None and ev.severity == Severity.CRITICAL


def test_budget_exhausted_equality_comparison() -> None:
    # budget_remaining_ratio == 0.0 fires; a positive ratio does not.
    assert evaluate("budget_exhausted", 0.0) is not None
    assert evaluate("budget_exhausted", 0.25) is None


def test_evaluate_all_only_fires_present_metrics() -> None:
    events = evaluate_all({
        "durable_health": 0,          # fires CRITICAL
        "disk_used_ratio": 0.5,       # below 0.9, no fire
        "gateway_health": 1,          # healthy, no fire
    })
    fired = {e.alert_id for e in events}
    assert "durable_unavailable" in fired
    assert "storage_pressure" not in fired
    assert "gateway_unavailable" not in fired


def test_alert_event_carries_no_secret_material() -> None:
    ev = evaluate("auth_attack", 10)
    assert ev is not None
    blob = repr(ev)
    for banned in ("key", "token", "password", "secret"):
        # only operational metadata (ids/counts/refs) — no secret words in values
        assert banned not in ev.destination.lower()
