from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any

from all_tomorrow.contracts import ContractError, new_id


class Priority(IntEnum):
    P0_USER_INTERACTIVE = 0
    P1_URGENT = 1
    P2_ACTIVE_PROJECT = 2
    P3_MAINTENANCE = 3
    P4_RESEARCH = 4
    P5_EXPERIMENT = 5
    P6_IDLE = 6


class BackgroundTaskClass(StrEnum):
    MAINTENANCE = "maintenance"
    RESEARCH = "research"
    EVALUATION = "evaluation"
    INDEXING = "indexing"
    PROJECT_BACKGROUND = "project_background"
    REPORT_GENERATION = "report_generation"


@dataclass(frozen=True, slots=True)
class ScheduledWork:
    task_class: BackgroundTaskClass
    priority: Priority
    payload: dict[str, Any]
    project_id: str | None = None
    work_id: str = field(default_factory=lambda: new_id("work"))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class WorkQueue:
    """Cooperative priority queue. Workers must yield at node boundaries for P0 work."""

    def __init__(self) -> None:
        self._heap: list[tuple[int, datetime, str, ScheduledWork]] = []
        self._claimed: dict[str, ScheduledWork] = {}

    def enqueue(self, work: ScheduledWork) -> None:
        if work.work_id in self._claimed or any(item[2] == work.work_id for item in self._heap):
            raise ContractError(f"work already exists: {work.work_id}")
        heapq.heappush(self._heap, (int(work.priority), work.created_at, work.work_id, work))

    def claim(self) -> ScheduledWork | None:
        if not self._heap:
            return None
        _, _, work_id, work = heapq.heappop(self._heap)
        self._claimed[work_id] = work
        return work

    def complete(self, work_id: str) -> ScheduledWork:
        try:
            return self._claimed.pop(work_id)
        except KeyError as error:
            raise ContractError(f"work is not claimed: {work_id}") from error

    def should_yield(self, current_priority: Priority) -> bool:
        return bool(self._heap and self._heap[0][0] < int(current_priority))

