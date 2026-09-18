import pytest

from all_tomorrow.contracts import ContractError
from all_tomorrow.evaluation import EvaluationScore, EvaluationService, ImprovementProposal


def test_candidate_is_only_promoted_without_regression() -> None:
    proposal = ImprovementProposal("pipeline", "coding", "coding@1", "coding@2", "reduce failures")
    decision = EvaluationService.compare(
        proposal,
        EvaluationScore("coding-bench", 8, 2, 0.72),
        EvaluationScore("coding-bench", 9, 1, 0.81),
        minimum_cases=10,
    )
    assert decision.accepted


def test_different_dataset_cannot_justify_promotion() -> None:
    proposal = ImprovementProposal("prompt", "router", "a", "b", "change routing")
    with pytest.raises(ContractError, match="same dataset"):
        EvaluationService.compare(
            proposal,
            EvaluationScore("old", 1, 0, 1.0),
            EvaluationScore("new", 1, 0, 1.0),
        )

