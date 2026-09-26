"""03C — Generic Sandbox Experiment verification (03C-01..06)."""

from __future__ import annotations

import pytest

from all_tomorrow.improve.experiment import (
    CriteriaTamperError,
    ExperimentError,
    ExperimentSpec,
    SandboxRunner,
    UnsupportedTargetError,
)


class FakePromptAdapter:
    target_type = "prompt"

    def __init__(self, fail_candidate=False, protected=False, saw_secret=None):
        self.fail_candidate = fail_candidate
        self.protected = protected
        self.saw_secret = saw_secret  # list to record if a secret was ever passed
        self.production_alias = "PROD-UNCHANGED"

    async def run_case(self, ref, case_id, *, network_allowed):
        if self.fail_candidate and ref == "cand":
            raise RuntimeError("candidate blew up")
        # Never receives a production credential — nothing to record.
        return f"{ref}:{case_id}:result"

    def touches_protected(self, candidate_ref):
        return self.protected


def _spec(**kw) -> ExperimentSpec:
    base = dict(
        proposal_id="p1", target_type="prompt", baseline_ref="base", candidate_ref="cand",
        case_set_ref="cs1", case_set_hash="CS", frozen_criteria_ref="cr1",
        frozen_criteria_hash="CR",
    )
    base.update(kw)
    return ExperimentSpec(**base)


def _runner(**adapter_kw) -> SandboxRunner:
    return SandboxRunner({"prompt": FakePromptAdapter(**adapter_kw)})


# 03C-02: baseline+candidate run identical frozen cases; drift is rejected.
async def test_03c_02_identical_frozen_cases() -> None:
    r = _runner()
    res = await r.run(_spec(), ["c1", "c2"], observed_case_set_hash="CS", observed_criteria_hash="CR")
    assert res.ok
    assert [o.case_id for o in res.case_outcomes] == ["c1", "c2"]
    # each case ran both refs
    assert res.case_outcomes[0].baseline_result_ref.startswith("base:")
    assert res.case_outcomes[0].candidate_result_ref.startswith("cand:")


async def test_03c_02_case_set_drift_rejected() -> None:
    r = _runner()
    with pytest.raises(ExperimentError):
        await r.run(_spec(), ["c1"], observed_case_set_hash="DRIFTED", observed_criteria_hash="CR")


# 03C-03: criteria tamper invalidates experiment.
async def test_03c_03_criteria_tamper_invalid() -> None:
    r = _runner()
    with pytest.raises(CriteriaTamperError):
        await r.run(_spec(), ["c1"], observed_case_set_hash="CS", observed_criteria_hash="CHANGED")


async def test_03c_03_candidate_touches_protected_invalid() -> None:
    r = _runner(protected=True)
    with pytest.raises(CriteriaTamperError):
        await r.run(_spec(), ["c1"], observed_case_set_hash="CS", observed_criteria_hash="CR")


# 03C-01: candidate failure is isolated — result records failure, production untouched.
async def test_03c_01_candidate_failure_isolated() -> None:
    adapter = FakePromptAdapter(fail_candidate=True)
    r = SandboxRunner({"prompt": adapter})
    res = await r.run(_spec(), ["c1"], observed_case_set_hash="CS", observed_criteria_hash="CR")
    assert not res.ok
    assert "candidate case error" in res.failure_reason
    assert adapter.production_alias == "PROD-UNCHANGED"  # production not mutated


# unsupported target → explicit failure.
async def test_03c_unsupported_target() -> None:
    r = _runner()
    with pytest.raises(UnsupportedTargetError):
        await r.run(_spec(target_type="code"), ["c1"], observed_case_set_hash="CS", observed_criteria_hash="CR")


# 03C-06: result carries a reproducible spec hash + per-case refs.
async def test_03c_06_reproducible_refs() -> None:
    r = _runner()
    spec = _spec()
    res = await r.run(spec, ["c1"], observed_case_set_hash="CS", observed_criteria_hash="CR")
    assert res.spec_hash == spec.spec_hash()
    assert res.artifact_refs == ("result:c1",)
    # spec hash is stable across identical specs (reproducible).
    assert _spec().spec_hash() == spec.spec_hash()
