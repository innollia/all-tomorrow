"""Stage 3.4D — Artifact-bound Feedback & Follow-up.

Feedback binds to an EXACT artifact/build hash: applying feedback meant for one
artifact to a different build is refused. Explicit feedback drives an evaluation
and a successor Work with recorded lineage. An inferred preference hypothesis
never substitutes for or overrides explicit feedback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id


class FeedbackError(DomainError):
    pass


class ArtifactMismatchError(FeedbackError):
    pass


class FeedbackKind(StrEnum):
    EXPLICIT = "EXPLICIT"        # user said it directly
    INFERRED = "INFERRED"        # preference hypothesis


@dataclass(frozen=True, slots=True)
class Feedback:
    feedback_id: str
    artifact_id: str
    artifact_hash: str           # exact build hash this feedback is about
    kind: FeedbackKind
    body: str


@dataclass(frozen=True, slots=True)
class SuccessorWork:
    work_id: str
    from_feedback_id: str
    on_artifact_id: str
    on_artifact_hash: str


def bind_feedback(fb: Feedback, *, current_artifact_hash: str) -> None:
    """Verify the feedback targets the artifact build actually in hand.

    S3-34D-01: feedback for a different artifact hash must not be applied.
    """
    if fb.artifact_hash != current_artifact_hash:
        raise ArtifactMismatchError(
            f"feedback {fb.feedback_id} targets hash {fb.artifact_hash}, "
            f"current build is {current_artifact_hash}"
        )


def make_followup(fb: Feedback, *, current_artifact_hash: str) -> SuccessorWork:
    """Explicit feedback → successor Work with lineage (S3-34D-02).

    An inferred hypothesis alone cannot spawn a follow-up as if it were a command.
    """
    bind_feedback(fb, current_artifact_hash=current_artifact_hash)
    if fb.kind != FeedbackKind.EXPLICIT:
        raise FeedbackError("inferred preference cannot drive a follow-up as explicit feedback")
    return SuccessorWork(work_id=new_id("work"), from_feedback_id=fb.feedback_id,
                         on_artifact_id=fb.artifact_id, on_artifact_hash=fb.artifact_hash)


def resolve_priority(explicit: Feedback | None, inferred: Feedback | None) -> Feedback | None:
    """S3-34D-03: an explicit command wins over an inferred preference."""
    if explicit is not None and explicit.kind == FeedbackKind.EXPLICIT:
        return explicit
    return inferred
