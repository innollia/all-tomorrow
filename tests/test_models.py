import pytest

from all_tomorrow.contracts import ContractError
from all_tomorrow.models import CredentialRecord, ModelRequest, ModelRoute, ModelRouter


def test_model_router_uses_declared_fallback_not_arbitrary_provider() -> None:
    router = ModelRouter(
        (
            ModelRoute("smart", "provider-a", "a1", "secret:a", frozenset({"tools"}), "offline", ("backup",)),
            ModelRoute("backup", "provider-b", "b1", "secret:b", frozenset({"tools"}), "available"),
            ModelRoute("unrelated", "provider-c", "c1", "secret:c", frozenset({"tools"}), "available"),
        )
    )
    assert router.select(ModelRequest("smart", frozenset({"tools"}))).alias == "backup"


def test_plaintext_looking_api_key_is_rejected() -> None:
    with pytest.raises(ContractError, match="opaque"):
        CredentialRecord("openai", "owner", "sk-plaintext", "available", frozenset({"gpt"}))

