from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from all_tomorrow.contracts import ContractError, new_id


class LessonStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PROMOTED = "promoted"


@dataclass(frozen=True, slots=True)
class Lesson:
    project_id: str
    title: str
    body: str
    tags: frozenset[str]
    evidence_refs: tuple[str, ...]
    lesson_id: str = field(default_factory=lambda: new_id("lesson"))
    status: LessonStatus = LessonStatus.CANDIDATE
    reuse_count: int = 0

    def __post_init__(self) -> None:
        if not self.project_id or not self.title or not self.body:
            raise ContractError("lesson requires project_id, title, and body")
        if not self.evidence_refs:
            raise ContractError("lesson requires provenance evidence")


@dataclass(frozen=True, slots=True)
class LessonMatch:
    lesson: Lesson
    matched_tags: frozenset[str]
    score: float


@dataclass(frozen=True, slots=True)
class ProjectBootstrap:
    project_id: str
    requested_tags: frozenset[str]
    lesson_candidates: tuple[LessonMatch, ...]


class LessonCatalog:
    """Tag retrieval is deliberately truth-preserving: it selects candidates, not facts."""

    def __init__(self) -> None:
        self._lessons: dict[str, Lesson] = {}

    def add(self, lesson: Lesson) -> None:
        if lesson.lesson_id in self._lessons:
            raise ContractError(f"lesson already exists: {lesson.lesson_id}")
        self._lessons[lesson.lesson_id] = lesson

    def find_candidates(
        self,
        tags: frozenset[str],
        *,
        exclude_project_id: str | None = None,
        limit: int = 10,
    ) -> tuple[LessonMatch, ...]:
        matches: list[LessonMatch] = []
        for lesson in self._lessons.values():
            if lesson.status not in {LessonStatus.ACCEPTED, LessonStatus.PROMOTED}:
                continue
            if exclude_project_id and lesson.project_id == exclude_project_id:
                continue
            overlap = tags & lesson.tags
            if not overlap:
                continue
            score = len(overlap) / max(len(tags | lesson.tags), 1)
            matches.append(LessonMatch(lesson, overlap, score))
        return tuple(sorted(matches, key=lambda item: (-item.score, -item.lesson.reuse_count, item.lesson.lesson_id))[:limit])

    def bootstrap(self, project_id: str, tags: frozenset[str]) -> ProjectBootstrap:
        return ProjectBootstrap(
            project_id=project_id,
            requested_tags=tags,
            lesson_candidates=self.find_candidates(tags, exclude_project_id=project_id),
        )

