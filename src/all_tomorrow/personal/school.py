"""Stage 3.1B — School Artifact Pipeline.

Flow: uploaded ArtifactRef -> extraction ArtifactRef -> classification -> owner
ref -> Goal/Work. Every extracted field carries page/range + extraction-version
provenance and a confidence; a low-confidence / unknown region is surfaced as
UNKNOWN, never turned into a fabricated fact. A re-uploaded artifact with the same
content hash is deduped. The central record holds the extraction result and refs,
not a replicated copy of the raw document telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from all_tomorrow.domain.errors import DomainError
from all_tomorrow.domain.ids import new_id

CONFIDENCE_FLOOR = 0.6   # below this, a region is UNKNOWN, not a fact


class SchoolPipelineError(DomainError):
    pass


class FieldState(StrEnum):
    EXTRACTED = "EXTRACTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExtractedField:
    name: str
    value: str | None
    confidence: float
    page: int
    span: tuple[int, int]
    extraction_version: str

    @property
    def state(self) -> FieldState:
        if self.value is None or self.confidence < CONFIDENCE_FLOOR:
            return FieldState.UNKNOWN
        return FieldState.EXTRACTED


@dataclass(frozen=True, slots=True)
class PipelineResult:
    upload_artifact_id: str
    extraction_artifact_id: str
    content_hash: str
    fields: tuple[ExtractedField, ...]
    work_id: str | None
    deduped: bool = False


class SchoolArtifactPipeline:
    def __init__(self) -> None:
        self._by_hash: dict[str, PipelineResult] = {}

    def process(self, *, upload_artifact_id: str, content_hash: str,
                fields: list[ExtractedField]) -> PipelineResult:
        # dedup by content hash
        if content_hash in self._by_hash:
            prior = self._by_hash[content_hash]
            return PipelineResult(
                upload_artifact_id=prior.upload_artifact_id,
                extraction_artifact_id=prior.extraction_artifact_id,
                content_hash=content_hash, fields=prior.fields,
                work_id=prior.work_id, deduped=True,
            )
        # Only confidently-extracted fields become actionable facts (→ Work).
        confident = [f for f in fields if f.state == FieldState.EXTRACTED]
        work_id = new_id("work") if confident else None
        result = PipelineResult(
            upload_artifact_id=upload_artifact_id,
            extraction_artifact_id=new_id("art"),
            content_hash=content_hash,
            fields=tuple(fields),
            work_id=work_id,
        )
        self._by_hash[content_hash] = result
        return result

    @staticmethod
    def facts(result: PipelineResult) -> list[ExtractedField]:
        """Fabrication guard: only EXTRACTED fields are facts; UNKNOWN stays unknown."""
        return [f for f in result.fields if f.state == FieldState.EXTRACTED]

    @staticmethod
    def unknown_regions(result: PipelineResult) -> list[ExtractedField]:
        return [f for f in result.fields if f.state == FieldState.UNKNOWN]
