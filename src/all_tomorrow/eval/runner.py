"""Runner for Stage 00D Evaluation Suite (E-01 ~ E-08).

Generates eval artifacts and verifies the Stage 0 gate:
- E-05, E-06, E-07, E-08 must pass 100%.
- All cases with expected properties must pass.
- Single mean score cannot compensate hard contract failures.
- Unmeasured metrics are not filled with zeros.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from all_tomorrow.eval.dataset import EVAL_CASES, EVAL_RUNNERS, EvalCase


@dataclass
class EvalCaseResult:
    id: str
    description: str
    is_hard_gate: bool
    passed: bool
    details: str
    expected_property: str


@dataclass
class EvalReport:
    suite_id: str
    timestamp: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    hard_gate_failures: int
    gate_cleared: bool
    results: list[EvalCaseResult]


async def run_evaluation_suite(
    artifact_path: Path | str | None = None,
) -> EvalReport:
    """Run E-01 ~ E-08 evaluation cases and optionally persist artifact."""
    results: list[EvalCaseResult] = []
    hard_gate_failures = 0
    passed_count = 0

    for case in EVAL_CASES:
        runner = EVAL_RUNNERS.get(case.id)
        if runner is None:
            passed = False
            details = f"No runner found for {case.id}"
        else:
            try:
                passed, details = await runner(case)
            except Exception as exc:
                passed = False
                details = f"Runner exception: {exc}"

        if passed:
            passed_count += 1
        elif case.is_hard_gate:
            hard_gate_failures += 1

        results.append(
            EvalCaseResult(
                id=case.id,
                description=case.description,
                is_hard_gate=case.is_hard_gate,
                passed=passed,
                details=details,
                expected_property=case.expected_property,
            )
        )

    total = len(EVAL_CASES)
    failed = total - passed_count
    # Stage 0 Gate: E-05, E-06, E-07, E-08 must pass 100% AND all expected property cases pass
    gate_cleared = (hard_gate_failures == 0) and (failed == 0)

    report = EvalReport(
        suite_id="00D-EVAL-SUITE-E01-E08",
        timestamp=datetime.now(UTC).isoformat(),
        total_cases=total,
        passed_cases=passed_count,
        failed_cases=failed,
        hard_gate_failures=hard_gate_failures,
        gate_cleared=gate_cleared,
        results=results,
    )

    if artifact_path:
        out_path = Path(artifact_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report_dict = {
            "suite_id": report.suite_id,
            "timestamp": report.timestamp,
            "total_cases": report.total_cases,
            "passed_cases": report.passed_cases,
            "failed_cases": report.failed_cases,
            "hard_gate_failures": report.hard_gate_failures,
            "gate_cleared": report.gate_cleared,
            "results": [asdict(r) for r in report.results],
        }
        out_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")

    return report
