from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from all_tomorrow.delivery import RetentionClass
from all_tomorrow.domain.ids import ArtifactId, new_artifact_id, utc_now


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Canonical artifact reference.
    
    Protects execution journals and state stores from oversized raw payloads.
    Stores immutable content hash and storage locator.
    """
    artifact_id: ArtifactId
    content_hash: str
    size_bytes: int
    media_type: str = "application/octet-stream"
    storage_locator: str = ""
    owner_id: str = "system"
    retention_class: RetentionClass = RetentionClass.STANDARD
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id or not str(self.artifact_id).strip():
            raise ValueError("ArtifactRef.artifact_id must be non-empty")
        if not self.content_hash or not self.content_hash.strip():
            raise ValueError("ArtifactRef.content_hash must be non-empty")
        if self.size_bytes < 0:
            raise ValueError("ArtifactRef.size_bytes must be >= 0")


def compute_content_hash(data: bytes | str) -> str:
    """Computes deterministic SHA-256 hash of payload."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
