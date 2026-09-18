import pytest

from all_tomorrow.contracts import (
    ContractError,
    NodeResult,
    NodeStatus,
    PipelineSpec,
    PipelineStep,
    UserQuestion,
)


def test_need_user_requires_question() -> None:
    with pytest.raises(ContractError, match="requires user_question"):
        NodeResult(status=NodeStatus.NEED_USER)


def test_question_requires_fields() -> None:
    with pytest.raises(ContractError, match="must not be empty"):
        UserQuestion(question="Which repo?", reason="Ambiguous", blocked_step="resolve", required_fields=())


def test_pipeline_rejects_unknown_static_target() -> None:
    with pytest.raises(ContractError, match="unknown step"):
        PipelineSpec(
            pipeline_id="broken",
            version=1,
            status="active",
            steps=(PipelineStep(id="one", type="test", next_step="missing"),),
        )

