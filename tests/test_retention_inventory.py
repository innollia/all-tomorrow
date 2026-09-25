"""Verification for D-RET-01: Recovery payload and log retention inventory existence and consistency."""

from pathlib import Path
import pytest


def test_d_ret_01_retention_inventory_document_exists_and_covers_required_surfaces() -> None:
    """D-RET-01: Verify that retention inventory document exists and defines 5-canary & 6-surface rules."""
    doc_path = Path("docs/architecture/retention-inventory.md")
    assert doc_path.exists(), "retention-inventory.md must exist in docs/architecture"

    content = doc_path.read_text(encoding="utf-8")

    # Verify 5 Data Classifications (Canaries)
    expected_classifications = [
        "EPHEMERAL_CREDENTIAL",
        "GOAL_SEMANTIC_PROMPT",
        "TOOL_INTERMEDIATE_PAYLOAD",
        "PAYLOAD_RAW_IMMUTABLE",
        "CORRELATION_TOKEN",
    ]
    for classification in expected_classifications:
        assert classification in content, f"Missing data classification '{classification}' in inventory"

    # Verify 6 Storage/Telemetry Surfaces
    expected_surfaces = [
        "Surface 1: Process Logs",
        "Surface 2: LiteLLM Proxy",
        "Surface 3: OpenTelemetry Telemetry Spans",
        "Surface 4: PostgreSQL Application DB",
        "Surface 5: Durable Backend Journal",
        "Surface 6: Artifact Store",
    ]
    for surface in expected_surfaces:
        assert surface in content, f"Missing storage surface '{surface}' in inventory"

    # Verify mandatory scrubbing and invariant guarantees
    assert "store_prompts_in_spend_logs = False" in content
    assert "turn_off_message_logging = True" in content
    assert "capture_content = False" in content
    assert "CompletionEvidence" in content
