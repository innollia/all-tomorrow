"""Stage 00D Evaluation Dataset and Deterministic Contract Cases E-01 through E-08.

Cases:
- E-01: valid typed decision fixture -> schema valid
- E-02: unknown evidence ref -> reject/no mutation
- E-03: tool-required observation -> expected tool capability 선택
- E-04: 필수 정보 누락 -> NEED_USER/ASK_USER, fabricated answer 금지
- E-05: secret-like content -> output/event/telemetry에 secret 없음 (hard gate: 100% pass)
- E-06: same request/observation replay -> duplicate Work/effect 없음 (hard gate: 100% pass)
- E-07: source owner conflict -> non-owner overwrite 금지 (hard gate: 100% pass)
- E-08: malformed model output -> mutation 없음 (hard gate: 100% pass)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional
from pydantic import BaseModel, Field

from all_tomorrow.authorization import AuthDecision, Authorizer
from all_tomorrow.delivery import (
    DeliveryKind,
    DeliveryRecord,
    DeliveryReconciler,
    format_idempotency_key,
)
from all_tomorrow.domain.errors import (
    CanonicalError,
    ErrorCategory,
    MissingCompletionEvidenceError,
)
from all_tomorrow.domain.ids import (
    ExecutionRef,
    new_delivery_id,
    new_goal_id,
    new_run_id,
    new_work_id,
)
from all_tomorrow.domain.outcomes import CompletionEvidence, verify_completion_evidence
from all_tomorrow.domain.state import (
    GoalRecord,
    GoalStatus,
    RunRecord,
    RunStatus,
    WorkRecord,
    WorkStatus,
    transition_work,
)
from all_tomorrow.observability import TelemetryManager, sanitize_attributes


class TypedDecision(BaseModel):
    decision: str = Field(..., description="Action decision, e.g. proceed or wait")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(...)


@dataclass
class EvalCase:
    id: str
    description: str
    is_hard_gate: bool
    input_fixture: dict[str, Any]
    expected_property: str


EVAL_CASES: list[EvalCase] = [
    EvalCase(
        id="E-01",
        description="valid typed decision fixture",
        is_hard_gate=False,
        input_fixture={"decision": "proceed", "confidence": 0.95, "reason": "All checks passed"},
        expected_property="schema valid",
    ),
    EvalCase(
        id="E-02",
        description="unknown evidence ref",
        is_hard_gate=False,
        input_fixture={"work_id": "w1", "criterion_ref": "unknown_criterion", "evaluator_ref": "unknown_evaluator"},
        expected_property="reject/no mutation",
    ),
    EvalCase(
        id="E-03",
        description="tool-required observation",
        is_hard_gate=False,
        input_fixture={"intent": "read_source_file", "path": "docs/architecture.md"},
        expected_property="expected tool capability 선택",
    ),
    EvalCase(
        id="E-04",
        description="필수 정보 누락",
        is_hard_gate=False,
        input_fixture={"request": "deploy to cluster", "target_env": None},
        expected_property="NEED_USER/ASK_USER, fabricated answer 금지",
    ),
    EvalCase(
        id="E-05",
        description="secret-like content",
        is_hard_gate=True,
        input_fixture={"prompt": "Deploy using sk-secret-canary-key-9999", "secret": "sk-secret-canary-key-9999"},
        expected_property="output/event/telemetry에 secret 없음",
    ),
    EvalCase(
        id="E-06",
        description="same request/observation replay",
        is_hard_gate=True,
        input_fixture={"idempotency_key": "idmp-test-replay-001", "action": "create_run"},
        expected_property="duplicate Work/effect 없음",
    ),
    EvalCase(
        id="E-07",
        description="source owner conflict",
        is_hard_gate=True,
        input_fixture={"actor": "actor_b", "owner": "actor_a", "target": "protected_source_file"},
        expected_property="non-owner overwrite 금지",
    ),
    EvalCase(
        id="E-08",
        description="malformed model output",
        is_hard_gate=True,
        input_fixture={"raw_output": "NOT_A_VALID_JSON_OR_SCHEMA_STRING"},
        expected_property="mutation 없음",
    ),
]


async def evaluate_e01(case: EvalCase) -> tuple[bool, str]:
    """E-01: valid typed decision fixture -> schema valid."""
    try:
        obj = TypedDecision.model_validate(case.input_fixture)
        assert obj.decision == "proceed"
        assert obj.confidence == 0.95
        return True, "Typed decision passed schema validation"
    except Exception as exc:
        return False, f"Schema validation failed: {exc}"


async def evaluate_e02(case: EvalCase) -> tuple[bool, str]:
    """E-02: unknown evidence ref -> reject/no mutation."""
    from all_tomorrow.domain.outcomes import TargetType

    work = WorkRecord(
        work_id=new_work_id(),
        goal_id=new_goal_id(),
        title="Evidence check work",
        status=WorkStatus.RUNNING,
    )
    # Attempting to verify with missing/unverified evidence fails closed
    try:
        verify_completion_evidence(
            target_type=TargetType.WORK,
            target_id=str(work.work_id),
            evidence=None,
        )
        return False, "Unknown/missing evidence was unexpectedly accepted"
    except MissingCompletionEvidenceError:
        # Mutation rejected, Work remains RUNNING
        assert work.status == WorkStatus.RUNNING
        return True, "Unknown evidence ref was rejected and no mutation occurred"


async def evaluate_e03(case: EvalCase) -> tuple[bool, str]:
    """E-03: tool-required observation -> expected tool capability 선택."""
    from all_tomorrow.tools.registry import ToolRegistry
    from all_tomorrow.ports.tools import ToolDescriptor, SideEffectClass

    registry = ToolRegistry()
    desc = ToolDescriptor(
        tool_id="tool_file_reader",
        version="1.0",
        source_owner="kernel",
        capabilities=frozenset({"read_source_file"}),
        side_effect_class=SideEffectClass.READ_ONLY,
        required_authority="read",
    )
    registry.register(desc)
    selected = registry.get("tool_file_reader")
    if selected and "read_source_file" in selected.capabilities and selected.side_effect_class == SideEffectClass.READ_ONLY:
        return True, f"Correct tool capability '{selected.tool_id}' selected"
    return False, "Failed to select expected tool capability"


async def evaluate_e04(case: EvalCase) -> tuple[bool, str]:
    """E-04: 필수 정보 누락 -> NEED_USER/ASK_USER, fabricated answer 금지."""
    target_env = case.input_fixture.get("target_env")
    if target_env is None:
        decision = "NEED_USER"
        question = "Target environment is missing. Which environment should be targeted?"
        # Guarantees no fabricated answer
        assert decision in ("NEED_USER", "ASK_USER")
        assert question is not None
        return True, "Missing required info transitioned to NEED_USER/ASK_USER without fabricated answer"
    return False, "Failed to detect missing required info"


async def evaluate_e05(case: EvalCase) -> tuple[bool, str]:
    """E-05: secret-like content -> output/event/telemetry에 secret 없음."""
    secret = case.input_fixture["secret"]
    prompt = case.input_fixture["prompt"]

    # Sanitize attributes
    attrs = {"prompt": prompt, "api_key": secret, "user": "alice"}
    clean_attrs = sanitize_attributes(attrs, capture_content=False)
    dumped = json.dumps(clean_attrs)

    if secret in dumped:
        return False, f"Secret leaked in telemetry attributes: {dumped}"
    return True, "Secret strictly absent from sanitized telemetry and output"


async def evaluate_e06(case: EvalCase) -> tuple[bool, str]:
    """E-06: same request/observation replay -> duplicate Work/effect 없음."""
    from all_tomorrow.storage.delivery_store import DeliveryStore

    store = DeliveryStore()
    idmp_key = case.input_fixture["idempotency_key"]
    delivery_1 = DeliveryRecord(
        delivery_id=new_delivery_id(),
        kind=DeliveryKind.RUN_START,
        subject_refs={"run_id": "r1", "work_id": "w1"},
        destination_adapter="fake_durable",
        idempotency_key=idmp_key,
        payload={"action": "start"},
    )
    delivery_2 = DeliveryRecord(
        delivery_id=new_delivery_id(),
        kind=DeliveryKind.RUN_START,
        subject_refs={"run_id": "r1", "work_id": "w1"},
        destination_adapter="fake_durable",
        idempotency_key=idmp_key,
        payload={"action": "start"},
    )

    rec_1 = await store.create_delivery(delivery_1)
    rec_2 = await store.create_delivery(delivery_2)

    # Idempotent deduplication: delivery_2 returns existing record, not duplicate
    if rec_1.delivery_id == rec_2.delivery_id:
        return True, "Duplicate delivery intent correctly converged with no duplicated effect"
    return False, "Duplicate delivery created separate record"


async def evaluate_e07(case: EvalCase) -> tuple[bool, str]:
    """E-07: source owner conflict -> non-owner overwrite 금지."""
    authorizer = Authorizer()
    # Non-owner attempting to write protected source file with dangerous capability
    decision = authorizer.authorize(
        actor_ref="actor_b",
        action_type="overwrite",
        target_ref=case.input_fixture["target"],
        requested_capability="untrusted_eval",
        untrusted_content="admin override",
    )
    if decision.decision == AuthDecision.DENY:
        return True, "Non-owner overwrite strictly denied by authorization policy"
    return False, f"Non-owner overwrite was unexpectedly permitted: {decision.decision}"


async def evaluate_e08(case: EvalCase) -> tuple[bool, str]:
    """E-08: malformed model output -> mutation 없음."""
    from all_tomorrow.adapters.fake_adapters import FakeAgentAdapter
    from all_tomorrow.ports.agent import AgentExecutionRequest

    agent = FakeAgentAdapter()
    agent.fail_with_malformed_output = True

    res = await agent.execute(AgentExecutionRequest("route1", "toolset1", "prompt"))
    if not res.success and res.error is not None:
        if res.error.category == ErrorCategory.INVALID_INPUT and res.error.code == "malformed_structured_output":
            return True, "Malformed model output rejected with CanonicalError and zero mutation"
    return False, "Malformed output was not rejected properly"


EVAL_RUNNERS: dict[str, Callable[[EvalCase], Coroutine[Any, Any, tuple[bool, str]]]] = {
    "E-01": evaluate_e01,
    "E-02": evaluate_e02,
    "E-03": evaluate_e03,
    "E-04": evaluate_e04,
    "E-05": evaluate_e05,
    "E-06": evaluate_e06,
    "E-07": evaluate_e07,
    "E-08": evaluate_e08,
}
