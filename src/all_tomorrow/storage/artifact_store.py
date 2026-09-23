from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from all_tomorrow.domain.artifacts import ArtifactRef, compute_content_hash
from all_tomorrow.domain.errors import CanonicalError, ErrorCategory
from all_tomorrow.domain.ids import ArtifactId, new_artifact_id


class ArtifactIntegrityError(Exception):
    """Raised when artifact content does not match its expected content_hash."""


class ArtifactStoreProtocol(Protocol):
    """Protocol for storing and retrieving immutable artifacts."""

    async def store(
        self,
        content: bytes | str,
        media_type: str = "application/octet-stream",
        owner_id: str = "system",
    ) -> ArtifactRef:
        ...

    async def retrieve(self, ref: ArtifactRef) -> bytes:
        ...


class LocalArtifactStore:
    """Local filesystem implementation of immutable artifact storage."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def store(
        self,
        content: bytes | str,
        media_type: str = "application/octet-stream",
        owner_id: str = "system",
    ) -> ArtifactRef:
        data = content.encode("utf-8") if isinstance(content, str) else content
        digest = compute_content_hash(data)
        art_id = new_artifact_id()
        file_path = self.base_dir / f"{digest}.dat"
        if not file_path.exists():
            file_path.write_bytes(data)

        return ArtifactRef(
            artifact_id=art_id,
            content_hash=digest,
            size_bytes=len(data),
            media_type=media_type,
            storage_locator=str(file_path.resolve()),
            owner_id=owner_id,
        )

    async def retrieve(self, ref: ArtifactRef) -> bytes:
        file_path = Path(ref.storage_locator)
        if not file_path.exists():
            # Try finding by hash in base_dir
            file_path = self.base_dir / f"{ref.content_hash}.dat"
            if not file_path.exists():
                raise FileNotFoundError(f"Artifact {ref.artifact_id} not found at {ref.storage_locator}")

        data = file_path.read_bytes()
        actual_hash = compute_content_hash(data)
        if actual_hash != ref.content_hash:
            raise ArtifactIntegrityError(
                f"Artifact hash mismatch: expected {ref.content_hash}, got {actual_hash}"
            )
        return data
