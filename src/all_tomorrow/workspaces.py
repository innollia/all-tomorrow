"""Stage 3.3C — Multi-Executor Workspace.

A workspace is a per-executor checkout with an explicit lifecycle and full
provenance (source/branch/HEAD/dirty/root/provisioning). An offline workspace
reports its last-known state with a freshness stamp rather than a live claim; a
dirty checkout is never auto-reset (reconciliation-required is surfaced instead);
a source mismatch is rejected; and adding a new host must not branch the core
naming — every host addresses the same logical workspace by the same name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import utc_now


class WorkspaceError(DomainError):
    pass


class SourceMismatchError(WorkspaceError):
    pass


class DirtyResetRefused(WorkspaceError):
    pass


class WorkspaceState(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    PROVISIONING = "PROVISIONING"
    READY_CLEAN = "READY_CLEAN"
    READY_DIRTY = "READY_DIRTY"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class WorkspaceProvenance:
    source_url: str
    branch: str
    head_sha: str
    dirty: bool
    root_path: str
    provisioned_by: str


@dataclass(slots=True)
class Workspace:
    name: str                     # logical name, identical across hosts (S3-33C-04)
    host: str
    state: WorkspaceState
    provenance: WorkspaceProvenance
    observed_at: datetime = field(default_factory=utc_now)
    freshness: timedelta = timedelta(minutes=5)

    def is_state_fresh(self, now: datetime | None = None) -> bool:
        now = now or utc_now()
        return (now - self.observed_at) <= self.freshness

    def usable_now(self, now: datetime | None = None) -> bool:
        """S3-33C-01: an offline/stale workspace is not claimed as live-usable."""
        if self.state == WorkspaceState.OFFLINE:
            return False
        if not self.is_state_fresh(now):
            return False
        return self.state in (WorkspaceState.READY_CLEAN, WorkspaceState.READY_DIRTY)

    def assert_source(self, expected_source: str, expected_branch: str) -> None:
        """S3-33C-03: a checkout whose source/branch differs is rejected."""
        if self.provenance.source_url != expected_source or self.provenance.branch != expected_branch:
            raise SourceMismatchError(
                f"workspace {self.name} is {self.provenance.source_url}@{self.provenance.branch}, "
                f"expected {expected_source}@{expected_branch}"
            )

    def prepare_clean(self) -> WorkspaceState:
        """S3-33C-02: never auto-reset a dirty checkout — require reconciliation."""
        if self.provenance.dirty:
            self.state = WorkspaceState.RECONCILIATION_REQUIRED
            raise DirtyResetRefused(
                f"workspace {self.name} has uncommitted changes; auto-reset refused"
            )
        return self.state


def register_host(name: str, host: str, provenance: WorkspaceProvenance,
                  state: WorkspaceState = WorkspaceState.PROVISIONING) -> Workspace:
    """Adding a host reuses the logical name — no core-name branch (S3-33C-04)."""
    return Workspace(name=name, host=host, state=state, provenance=provenance)
