"""조사 목록: 사용자가 콘솔에서 '놀 때 무엇을 조사할지'를 정해 두면, PC가 쉬는 동안 Codex가 하나씩 조사한다.

  GET    /api/research                 주제 목록 + 각 주제의 최근 실행
  POST   /api/research                 주제 추가 {title, ask, project_id?, repeat_days?}
  PUT    /api/research/{id}            고치기(제목·요청·프로젝트·반복·켜기/끄기·지금 돌리기·순서)
  DELETE /api/research/{id}            주제 삭제(결과 파일은 남긴다)
  GET    /api/research/runs/{run}      결과 본문

파일은 셋이다: agenda.json은 이 API와 메타인지 세션의 조사 목록 도구(overseer.research_mcp)가
agenda.lock을 잡고 쓰고, runs.json과 results/는 실행기(overseer.idle_research)만 쓴다.
메타인지가 넣은 주제는 source="metacog"(와 reason)로 남아 콘솔에 '메타인지 제안'으로 보인다. 사용자가 그런 주제를
끄거나 지우면 declined.json에 남고, 메타인지는 같은 주제를 다시 넣거나 다시 켜지 못한다.
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
DECLINED = "declined.json"
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


def _key(text: str) -> str:
    return re.sub(r"\W+", "", text).lower()


class ResearchStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def topics(self) -> list[dict[str, Any]]:
        return load_topics(self.folder)

    def _save(self, topics: list[dict[str, Any]]) -> None:
        _write(self.folder / AGENDA, {"topics": topics})

    def _lock(self):
        from all_tomorrow.overseer.runtime import singleton
        self.folder.mkdir(parents=True, exist_ok=True)
        return singleton(self.folder / "agenda.lock", wait=10)

    def declined(self) -> list[dict[str, Any]]:
        """사용자가 끄거나 지운 메타인지 주제. 메타인지에 대한 사용자의 답이다."""
        return _read(self.folder / DECLINED, {"topics": []}).get("topics", [])

    def _decline(self, topic: dict[str, Any], how: str) -> None:
        if topic.get("source") != "metacog":
            return
        left = [d for d in self.declined() if d["id"] != topic["id"]]
        left.append({"id": topic["id"], "title": topic["title"], "ask": topic["ask"], "idea_id": topic.get("idea_id", ""),
                     "project_id": topic.get("project_id", ""), "how": how, "at": time.time()})
        _write(self.folder / DECLINED, {"topics": left[-200:]})

    def suggest(self, title: str, ask: str, reason: str, *, idea_id: str = "", project_id: str = "all-tomorrow",
                repeat_days: float = 0) -> dict[str, Any]:
        """메타인지 세션이 넣는 주제. 사용자가 전에 끄거나 지운 것과 같은 주제는 넣지 않는다."""
        title, ask, reason = title.strip(), ask.strip(), reason.strip()
        if not ask or not reason:
            raise ValueError("조사할 내용과 근거가 있어야 한다")
        with self._lock():
            for d in self.declined():
                if {_key(title), _key(ask)} & {_key(d["title"]), _key(d["ask"])} - {""}:
                    raise ValueError(f"사용자가 {d['how']} 주제와 같다: {d['id']} {d['title']}")
            topics = self.topics()
            if any(_key(ask) == _key(t["ask"]) for t in topics):
                raise ValueError("같은 요청의 주제가 이미 목록에 있다")
            topic = {"id": "R-" + time.strftime("%y%m%d") + "-" + uuid.uuid4().hex[:4],
                     "title": title or ask.splitlines()[0][:60], "ask": ask, "project_id": project_id.strip() or "all-tomorrow",
                     "repeat_days": max(0.0, min(float(repeat_days), 365.0)), "enabled": True, "created": time.time(),
                     "run_now_at": None, "source": "metacog", "reason": reason}
            if idea_id.strip():
                topic["idea_id"] = idea_id.strip()
            topics.append(topic)
            self._save(topics)
        return topic

    def revise(self, topic_id: str, *, title: str | None = None, ask: str | None = None, reason: str | None = None,
               repeat_days: float | None = None, project_id: str | None = None) -> dict[str, Any]:
        """메타인지가 자기가 넣은 주제만 고친다. 사용자가 끈 주제는 건드리지 않는다(켜기는 사용자 몫)."""
        with self._lock():
            topics = self.topics()
            topic = next((t for t in topics if t["id"] == topic_id), None)
            if topic is None:
                raise KeyError(topic_id)
            if topic.get("source") != "metacog":
                raise ValueError("사용자가 넣은 주제는 고치지 않는다")
            if not topic.get("enabled", True) or any(d["id"] == topic_id for d in self.declined()):
                raise ValueError("사용자가 끈 주제다")
            for name, value in (("title", title), ("ask", ask), ("reason", reason), ("project_id", project_id)):
                if value is not None and value.strip():
                    topic[name] = value.strip()
            if repeat_days is not None:
                topic["repeat_days"] = max(0.0, min(float(repeat_days), 365.0))
            self._save(topics)
        return topic

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
        with self._lock():
            topics = self.topics()
            topics.append(topic)
            self._save(topics)
        return topic

    def create_followup(self, idea_id: str, request: str) -> dict[str, Any]:
        """아이디어 '추가 조사': idea_id가 붙은 주제를 만들고 바로 차례가 되게 한다('지금 돌리기'와 같다).
        ask에는 사용자의 짧은 요청 원문만 둔다. 맥락은 실행기가 돌릴 때 아이디어에서 읽어 붙인다."""
        request = request.strip()
        if not request:
            raise ValueError("추가 조사 요청이 비어 있다")
        now = time.time()
        topic = {"id": "R-" + time.strftime("%y%m%d") + "-" + uuid.uuid4().hex[:4],
                 "title": "추가 조사 · " + request.splitlines()[0][:40], "ask": request, "idea_id": idea_id,
                 "project_id": "all-tomorrow", "repeat_days": 0, "enabled": True, "created": now, "run_now_at": now}
        with self._lock():
            topics = self.topics()
            topics.append(topic)
            self._save(topics)
        return topic

    def followups(self, idea_id: str) -> list[dict[str, Any]]:
        """그 아이디어의 추가 조사 이력: 요청 원문, 실행 상태, 결과 링크(run id). 최근 것이 앞."""
        return [t for t in reversed(self.overview()) if t.get("idea_id") == idea_id]

    def update(self, topic_id: str, patch: TopicPatch) -> dict[str, Any]:
        with self._lock():
            topics = self.topics()
            index = next((i for i, t in enumerate(topics) if t["id"] == topic_id), None)
            if index is None:
                raise KeyError(topic_id)
            topic = topics[index]
            was_enabled = topic.get("enabled", True)
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
            if was_enabled and not topic["enabled"]:
                self._decline(topic, "끈")
            elif topic["enabled"] and not was_enabled:   # 사용자가 다시 켜면 거절이 풀린다
                _write(self.folder / DECLINED, {"topics": [d for d in self.declined() if d["id"] != topic_id]})
        return topic

    def delete(self, topic_id: str) -> None:
        with self._lock():
            topics = self.topics()
            left = [t for t in topics if t["id"] != topic_id]
            if len(left) == len(topics):
                raise KeyError(topic_id)
            self._save(left)
            self._decline(next(t for t in topics if t["id"] == topic_id), "지운")

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
