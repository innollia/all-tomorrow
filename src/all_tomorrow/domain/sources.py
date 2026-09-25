from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from all_tomorrow.domain.ids import ProjectId, utc_now


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Canonical reference to an external or upstream source of truth."""
    source_owner_id: str
    source_type: str
    source_id: str
    version: str
    canonical_locator: str
    observed_at: datetime = field(default_factory=utc_now)
    freshness_policy_ref: str | None = None
    access_scope: str = "default"
    read_authority: str = "read"
    write_authority: str = "write"

    def __post_init__(self) -> None:
        if not self.source_owner_id or not self.source_owner_id.strip():
            raise ValueError("SourceRef.source_owner_id must be non-empty")
        if not self.source_type or not self.source_type.strip():
            raise ValueError("SourceRef.source_type must be non-empty")
        if not self.source_id or not self.source_id.strip():
            raise ValueError("SourceRef.source_id must be non-empty")
        if not self.version or not self.version.strip():
            raise ValueError("SourceRef.version must be non-empty")
        if not self.canonical_locator or not self.canonical_locator.strip():
            raise ValueError("SourceRef.canonical_locator must be non-empty")


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """Canonical Project control plane record."""
    project_id: ProjectId
    owner_user_id: str
    title: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    source_refs: tuple[SourceRef, ...] = ()
    default_authority_policy_refs: tuple[str, ...] = ()
    allowed_executor_scope: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.owner_user_id or not self.owner_user_id.strip():
            raise ValueError("ProjectRecord.owner_user_id must be non-empty")
        if not self.title or not self.title.strip():
            raise ValueError("ProjectRecord.title must be non-empty")
