"""조사 목록: 사용자가 콘솔에서 '놀 때 무엇을 조사할지'를 정해 두면, PC가 쉬는 동안 Codex가 하나씩 조사한다.

  GET    /api/research                 주제 목록 + 각 주제의 최근 실행
  POST   /api/research                 주제 추가 {title, ask, project_id?, repeat_days?}
  PUT    /api/research/{id}            고치기(제목·요청·프로젝트·반복·켜기/끄기·지금 돌리기·순서)
  DELETE /api/research/{id}            주제 삭제(결과 파일은 남긴다)
  GET    /api/research/runs/{run}      결과 본문

파일은 셋이고 쓰는 쪽이 하나씩이다: agenda.json은 이 API만, runs.json과 results/는 실행기
(overseer.idle_research)만 쓴다. 그래서 둘이 같은 파일을 동시에 고치는 일이 없다.
모델을 부르지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext

AGENDA = "agenda.json"
RUNS = "runs.json"
RESULTS = "results"


def research_dir() -> Path:
    """웹과 같은 기본값. 실행기(PC 쪽)도 이 경로를 쓴다."""
    from all_tomorrow.overseer.environment import REPO
    return Path(os.environ.get("ALL_TOMORROW_CONSOLE_DATA") or REPO / ".artifacts" / "console") / "research"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_topics(folder: Path) -> list[dict[str, Any]]:
    return _read(folder / AGENDA, {"topics": []}).get("topics", [])


def load_runs(folder: Path) -> list[dict[str, Any]]:
    return _read(folder / RUNS, {"runs": []}).get("runs", [])


def save_runs(folder: Path, runs: list[dict[str, Any]]) -> None:
    _write(folder / RUNS, {"runs": runs[-300:]})


class TopicRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    ask: str = Field(min_length=1, max_length=8000)
    project_id: str = Field(default="all-tomorrow", max_length=80)
    repeat_days: float = Field(default=0, ge=0, le=365)


class TopicPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    ask: str | None = Field(default=None, min_length=1, max_length=8000)
    project_id: str | None = Field(default=None, max_length=80)
    repeat_days: float | None = Field(default=None, ge=0, le=365)
    enabled: bool | None = None
    run_now: bool | None = None      # 다음 점검에서 PC 사용 중이어도 돌린다
    move: int | None = Field(default=None, ge=-1, le=1)   # -1 위로, 1 아래로(위가 먼저 돈다)


class ResearchStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def topics(self) -> list[dict[str, Any]]:
        return load_topics(self.folder)

    def _save(self, topics: list[dict[str, Any]]) -> None:
        _write(self.folder / AGENDA, {"topics": topics})

    def overview(self) -> list[dict[str, Any]]:
        runs = load_runs(self.folder)
        out = []
        for topic in self.topics():
            mine = [r for r in runs if r.get("topic_id") == topic["id"]]
            out.append({**topic, "runs": list(reversed(mine[-5:]))})
        return out

    def create(self, body: TopicRequest) -> dict[str, Any]:
        ask = body.ask.strip()
        if not ask:
            raise ValueError("조사할 내용이 비어 있다")
        topic = {"id": "R-" + time.strftime("%y%m%d") + "-" + uuid.uuid4().hex[:4],
                 "title": body.title.strip() or ask.splitlines()[0][:60], "ask": ask,
                 "project_id": body.project_id.strip() or "all-tomorrow", "repeat_days": body.repeat_days,
                 "enabled": True, "created": time.time(), "run_now_at": None}
        topics = self.topics()
        topics.append(topic)
        self._save(topics)
        return topic

    def update(self, topic_id: str, patch: TopicPatch) -> dict[str, Any]:
        topics = self.topics()
        index = next((i for i, t in enumerate(topics) if t["id"] == topic_id), None)
        if index is None:
            raise KeyError(topic_id)
        topic = topics[index]
        for name in ("title", "project_id", "repeat_days", "enabled"):
            value = getattr(patch, name)
            if isinstance(value, str):
                value = value.strip()
                if not value:      # 빈 제목·프로젝트로는 바꾸지 않는다
                    continue
            if value is not None:
                topic[name] = value
        if patch.ask is not None:
            if not patch.ask.strip():
                raise ValueError("조사할 내용이 비어 있다")
            topic["ask"] = patch.ask.strip()
        if patch.run_now:
            topic["run_now_at"], topic["enabled"] = time.time(), True
        if patch.move:
            other = index + patch.move
            if 0 <= other < len(topics):
                topics[index], topics[other] = topics[other], topics[index]
        self._save(topics)
        return topic

    def delete(self, topic_id: str) -> None:
        topics = self.topics()
        left = [t for t in topics if t["id"] != topic_id]
        if len(left) == len(topics):
            raise KeyError(topic_id)
        self._save(left)

    def result(self, run_id: str) -> dict[str, Any]:
        run = next((r for r in load_runs(self.folder) if r.get("id") == run_id), None)
        if run is None or not run.get("result_file") or not re.fullmatch(r"[\w.-]+", run["result_file"]):
            raise KeyError(run_id)
        try:
            text = (self.folder / RESULTS / run["result_file"]).read_text(encoding="utf-8")
        except OSError as error:
            raise KeyError(run_id) from error
        return {**run, "text": text}


def build_router(ctx: ConsoleContext) -> APIRouter:
    store = ResearchStore(ctx.feature_dir("research"))
    router = APIRouter(prefix="/api/research")

    @router.get("")
    async def overview(_: str = Depends(ctx.current_user)) -> list[dict[str, Any]]:
        return store.overview()

    @router.post("")
    async def create(body: TopicRequest, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        try:
            return store.create(body)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/runs/{run_id}")
    async def result(run_id: str, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        try:
            return store.result(run_id)
        except KeyError as error:
            raise HTTPException(404, "no such result") from error

    @router.put("/{topic_id}")
    async def update(topic_id: str, body: TopicPatch, _: str = Depends(ctx.current_user)) -> dict[str, Any]:
        try:
            return store.update(topic_id, body)
        except KeyError as error:
            raise HTTPException(404, "no such topic") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.delete("/{topic_id}", status_code=204)
    async def delete(topic_id: str, _: str = Depends(ctx.current_user)) -> None:
        try:
            store.delete(topic_id)
        except KeyError as error:
            raise HTTPException(404, "no such topic") from error

    return router
