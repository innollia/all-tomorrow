"""Stage 3.4D — Artifact-bound feedback & follow-up verification (S3-34D-01..03)."""

from __future__ import annotations

import pytest

from all_tomorrow.feedback import (
    ArtifactMismatchError,
    Feedback,
    FeedbackError,
    FeedbackKind,
    bind_feedback,
    make_followup,
    resolve_priority,
)


def _fb(kind=FeedbackKind.EXPLICIT, h="hash-A"):
    return Feedback(feedback_id="f1", artifact_id="a1", artifact_hash=h, kind=kind, body="make it blue")


# S3-34D-01: feedback for the wrong artifact hash is not applied.
def test_34d_01_wrong_artifact_rejected() -> None:
    with pytest.raises(ArtifactMismatchError):
        bind_feedback(_fb(h="hash-A"), current_artifact_hash="hash-B")
    with pytest.raises(ArtifactMismatchError):
        make_followup(_fb(h="hash-A"), current_artifact_hash="hash-B")


# S3-34D-02: explicit feedback → follow-up with lineage.
def test_34d_02_followup_lineage() -> None:
    fb = _fb()
    sw = make_followup(fb, current_artifact_hash="hash-A")
    assert sw.from_feedback_id == "f1"
    assert sw.on_artifact_id == "a1" and sw.on_artifact_hash == "hash-A"


def test_34d_inferred_cannot_drive_followup() -> None:
    fb = _fb(kind=FeedbackKind.INFERRED)
    with pytest.raises(FeedbackError):
        make_followup(fb, current_artifact_hash="hash-A")


# S3-34D-03: explicit command priority over inferred preference.
def test_34d_03_explicit_priority() -> None:
    explicit = _fb(kind=FeedbackKind.EXPLICIT)
    inferred = Feedback(feedback_id="f2", artifact_id="a1", artifact_hash="hash-A",
                        kind=FeedbackKind.INFERRED, body="maybe green")
    assert resolve_priority(explicit, inferred) is explicit
    # with no explicit, inferred is used
    assert resolve_priority(None, inferred) is inferred
