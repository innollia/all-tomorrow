"""03E — Protected Change Classification and Handoff.

Classifies a candidate change as ORDINARY, PROTECTED, or (fail-closed) UNKNOWN,
excluding protected/unknown changes from automatic promotion. Any of a mechanical
protected-surface touch, a semantic authority-expansion signal, an unknown/
insufficient detector result, a new unclassified authority surface, or a change
to the classifier/policy itself → APPROVAL_REQUIRED.

"Not proven ordinary" is never treated as ordinary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum


class Classification(StrEnum):
    ORDINARY = "ORDINARY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


# Versioned mechanical protected surfaces (config/hash-managed in production).
MECHANICAL_PROTECTED_SURFACES: frozenset[str] = frozenset({
    "approval_authority", "deployment_credential", "signing_credential",
    "budget_ceiling", "concurrency_ceiling", "rate_ceiling",
    "secret_policy", "permission_policy", "production_write_role",
    "kill_switch", "rollback_enforcement", "audit_enforcement",
    "provenance_enforcement", "protection_classifier", "protection_policy",
    "retention_policy", "security_policy",
})

# Semantic authority-expansion signals.
SEMANTIC_SIGNALS: frozenset[str] = frozenset({
    "expand_cost_ceiling", "expand_resource_ceiling", "expand_permission_scope",
    "expand_secret_scope", "expand_production_write", "weaken_approval",
    "weaken_rollback", "weaken_audit", "weaken_kill_switch",
    "shrink_protected_surface", "create_bypass", "new_credential_surface",
    "new_deployment_surface",
})

PROTECTION_POLICY_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ChangeDescriptor:
    proposal_id: str
    proposal_revision: int
    candidate_hash: str
    baseline_hash: str
    touched_surfaces: frozenset[str] = frozenset()
    semantic_signals: frozenset[str] = frozenset()
    detector_confident: bool = True          # False → unknown/insufficient
    new_unclassified_surface: bool = False
    changes_classifier_or_policy: bool = False


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    classification: Classification
    protected_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HandoffPackage:
    """Immutable package handed to 04E. Any drift invalidates it."""
    proposal_id: str
    proposal_revision: int
    candidate_hash: str
    baseline_hash: str
    protected_reasons: tuple[str, ...]
    requested_boundary_change: str
    protection_policy_version: str
    nonce: str
    expires_at: str
    handoff_hash: str = ""

    def compute_hash(self) -> str:
        return hashlib.sha256("\x1f".join([
            self.proposal_id, str(self.proposal_revision), self.candidate_hash,
            self.baseline_hash, ",".join(self.protected_reasons),
            self.requested_boundary_change, self.protection_policy_version, self.nonce,
        ]).encode()).hexdigest()


def classify(change: ChangeDescriptor) -> ClassificationResult:
    reasons: list[str] = []

    mech = change.touched_surfaces & MECHANICAL_PROTECTED_SURFACES
    if mech:
        reasons.append(f"mechanical protected surface: {sorted(mech)}")
    sem = change.semantic_signals & SEMANTIC_SIGNALS
    if sem:
        reasons.append(f"semantic authority expansion: {sorted(sem)}")
    if not change.detector_confident:
        reasons.append("detector unknown/insufficient (fail-closed)")
    if change.new_unclassified_surface:
        reasons.append("new unclassified authority surface")
    if change.changes_classifier_or_policy:
        reasons.append("changes classifier/protection policy itself")

    if reasons:
        return ClassificationResult(Classification.APPROVAL_REQUIRED, tuple(reasons))
    return ClassificationResult(Classification.ORDINARY, ())


def build_handoff(
    change: ChangeDescriptor,
    result: ClassificationResult,
    *,
    requested_boundary_change: str,
    nonce: str,
    expires_at: str,
) -> HandoffPackage:
    if result.classification != Classification.APPROVAL_REQUIRED:
        raise ValueError("handoff only built for APPROVAL_REQUIRED changes")
    pkg = HandoffPackage(
        proposal_id=change.proposal_id,
        proposal_revision=change.proposal_revision,
        candidate_hash=change.candidate_hash,
        baseline_hash=change.baseline_hash,
        protected_reasons=result.protected_reasons,
        requested_boundary_change=requested_boundary_change,
        protection_policy_version=PROTECTION_POLICY_VERSION,
        nonce=nonce,
        expires_at=expires_at,
    )
    from dataclasses import replace
    return replace(pkg, handoff_hash=pkg.compute_hash())


def handoff_valid(pkg: HandoffPackage, current_candidate_hash: str, current_proposal_revision: int) -> bool:
    """A handoff is invalid if the candidate/proposal changed since it was built."""
    if pkg.candidate_hash != current_candidate_hash:
        return False
    if pkg.proposal_revision != current_proposal_revision:
        return False
    return pkg.handoff_hash == pkg.compute_hash()
