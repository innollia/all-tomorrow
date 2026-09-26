"""04A — LiteLLM + PydanticAI model wiring verification.

Offline checks for 04A-02 (no provider branch), 04A-03 (retry ceiling not
multiplied), 04A-04 (usage unknown not forged to 0), and 04A-05 (committed proxy
config carries privacy defaults and no literal secret). The live PydanticAI→
Proxy call (04A-01) and the running-gateway canary follow the existing
test_litellm_gateway_privacy harness under AT_TEST_LITELLM_BIN.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

import yaml

from all_tomorrow.harness.retry_matrix import RetryMatrix
from all_tomorrow.ports.agent import AgentUsage
from all_tomorrow.adapters.pydantic_ai import _extract_usage


# 04A-04: usage unknown must not be forged into a zero-token measurement
def test_04a_04_unknown_usage_not_forged_to_zero() -> None:
    class _NoUsage:
        def usage(self):  # provider reported nothing
            return None

    u = _extract_usage(_NoUsage())
    assert u.usage_known is False
    # A default AgentUsage (explicit construction) is known; the gap is only the
    # unmeasured case above.
    assert AgentUsage(total_tokens=0).usage_known is True


def test_04a_04_real_usage_is_preserved() -> None:
    class _Usage:
        request_tokens = 11
        response_tokens = 22
        total_tokens = 33

    class _Result:
        def usage(self):
            return _Usage()

    u = _extract_usage(_Result())
    assert u.usage_known is True
    assert (u.prompt_tokens, u.completion_tokens, u.total_tokens) == (11, 22, 33)


# 04A-03: retry budget does not multiply across layers; exactly one owner per class
def test_04a_03_retry_ceiling_single_owner() -> None:
    matrix = RetryMatrix.standard_harness_matrix()
    # The auto-retry owners must be unique per failure class (no nested multiply).
    for failure_class in ("validation_error", "process_crash", "rate_limit", "task_semantic_failure"):
        owners = [
            p.layer_name
            for p in matrix.layers.values()
            if p.is_retry_owner and failure_class in p.handled_failure_classes
        ]
        assert len(owners) <= 1, f"{failure_class} has multiple auto-retry owners: {owners}"
    # Gateway + provider SDK retries are pinned to 0 so they cannot multiply.
    assert matrix.layers["litellm_gateway"].max_retries == 0
    assert matrix.layers["provider_sdk"].max_retries == 0


# 04A-02: All Tomorrow core does not branch on a provider SDK
def test_04a_02_no_provider_sdk_branch_in_core() -> None:
    # Provider SDK imports (openai, anthropic, …) belong ONLY in the adapter layer.
    core_dirs = [
        Path("src/all_tomorrow/domain"),
        Path("src/all_tomorrow/storage"),
        Path("src/all_tomorrow/bridge"),
    ]
    banned = ("import openai", "from openai", "import anthropic", "from anthropic",
              "import google.genai", "litellm")
    for d in core_dirs:
        for py in d.rglob("*.py"):
            src = py.read_text(encoding="utf-8")
            code = " ".join(
                tok.string
                for tok in tokenize.generate_tokens(io.StringIO(src).readline)
                if tok.type not in (tokenize.COMMENT, tokenize.STRING)
            ).lower()
            for b in banned:
                assert b not in code, f"{py} branches on a provider SDK: {b}"


# 04A-05: committed proxy config has privacy defaults and no literal secret
def test_04a_05_proxy_config_privacy_defaults_no_literal_secret() -> None:
    path = Path("config/litellm-proxy.example.yaml")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))

    gs = cfg["general_settings"]
    assert gs["store_prompts_in_spend_logs"] is False
    assert gs["turn_off_message_logging"] is True
    # master key and provider keys are env references, never literals.
    assert str(gs["master_key"]).startswith("os.environ/")
    for entry in cfg["model_list"]:
        api_key = entry["litellm_params"]["api_key"]
        assert str(api_key).startswith("os.environ/"), f"literal key in {entry['model_name']}"
        assert entry["litellm_params"]["num_retries"] == 0  # D-LOCK-04

    assert cfg["litellm_settings"]["callbacks"] == []
    assert cfg["litellm_settings"]["num_retries"] == 0

    # Canary: no obvious literal secret anywhere in the file.
    raw = path.read_text(encoding="utf-8")
    for marker in ("sk-", "api-key:", "AKIA"):
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert marker not in stripped or "os.environ/" in stripped, (
                f"possible literal secret in config: {line!r}"
            )
