"""Stage 2.1D — Attachment & Escalation Policy.

Attachments are turned into immutable ArtifactRefs (raw bytes never land on the
Request row). A versioned, deterministic preflight decides whether a request
needs durable execution / central resolution / NEED_USER. Untrusted attachment
content can never expand authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from all_tomorrow.domain.artifacts import compute_content_hash

INGRESS_POLICY_VERSION = "1"


class Escalation(StrEnum):
    INLINE = "INLINE"                 # simple, handle directly
    DURABLE = "DURABLE"               # needs a durable Run
    CENTRAL_RESOLUTION = "CENTRAL_RESOLUTION"  # cross-project/resource mutation
    NEED_USER = "NEED_USER"           # ambiguous mutation


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    artifact_id: str
    content_hash: str
    media_type: str


@dataclass(frozen=True, slots=True)
class PreflightInputs:
    needs_durable_execution: bool = False
    cross_project_mutation: bool = False
    central_state_update: bool = False
    background_restart_safe: bool = False
    mutation_effect_known: bool = True   # False → ambiguous


def attach(content: bytes, media_type: str, *, artifact_id: str) -> AttachmentRef:
    """Hash the bytes into an immutable ArtifactRef; the Request stores only the ref."""
    return AttachmentRef(artifact_id=artifact_id, content_hash=compute_content_hash(content),
                         media_type=media_type)


def preflight(inp: PreflightInputs) -> Escalation:
    """Versioned deterministic escalation decision."""
    if not inp.mutation_effect_known:
        return Escalation.NEED_USER
    if inp.cross_project_mutation or inp.central_state_update:
        return Escalation.CENTRAL_RESOLUTION
    if inp.needs_durable_execution or inp.background_restart_safe:
        return Escalation.DURABLE
    return Escalation.INLINE


def attachment_grants_authority(_ref: AttachmentRef) -> bool:
    """An attachment is untrusted DATA; it never grants authority (always False)."""
    return False
