from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from all_tomorrow.contracts import ContractError, Project, UserQuestion


@dataclass(frozen=True, slots=True)
class ProjectResolution:
    project: Project | None
    confidence: str
    question: UserQuestion | None = None


class ProjectRegistry:
    def __init__(self, projects: tuple[Project, ...]) -> None:
        ids = [project.project_id for project in projects]
        if len(ids) != len(set(ids)):
            raise ContractError("project ids must be unique")
        self._projects = {project.project_id: project for project in projects}

    @property
    def projects(self) -> tuple[Project, ...]:
        return tuple(self._projects.values())

    def resolve(self, candidate: str | None, *, blocked_step: str = "resolve_project") -> ProjectResolution:
        if candidate:
            normalized = candidate.strip().casefold()
            matches = [
                project
                for project in self._projects.values()
                if normalized == project.project_id.casefold()
                or normalized == project.name.casefold()
                or normalized in {alias.casefold() for alias in project.aliases}
            ]
            if len(matches) == 1:
                return ProjectResolution(matches[0], "exact")
            if len(matches) > 1:
                return ProjectResolution(None, "ambiguous", self._question(blocked_step, matches))
        return ProjectResolution(None, "unknown", self._question(blocked_step, list(self._projects.values())))

    @staticmethod
    def _question(blocked_step: str, candidates: list[Project]) -> UserQuestion:
        names = ", ".join(project.project_id for project in candidates) or "등록된 프로젝트 없음"
        return UserQuestion(
            question=f"어느 프로젝트를 대상으로 할까요? 후보: {names}",
            reason="mutation 또는 project state 조회 대상을 임의로 선택할 수 없습니다.",
            blocked_step=blocked_step,
            required_fields=("project_id",),
        )


def load_projects(path: str | Path) -> ProjectRegistry:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        raise ContractError("project catalog requires a projects list")
    projects: list[Project] = []
    for index, item in enumerate(data["projects"]):
        if not isinstance(item, dict):
            raise ContractError(f"projects[{index}] must be a mapping")
        projects.append(
            Project(
                project_id=item.get("id", ""),
                name=item.get("name", ""),
                owner=item.get("owner", ""),
                source_refs=tuple(item.get("source_refs", [])),
                aliases=frozenset(item.get("aliases", [])),
                maintainer_capabilities=frozenset(item.get("maintainer_capabilities", [])),
            )
        )
    return ProjectRegistry(tuple(projects))

