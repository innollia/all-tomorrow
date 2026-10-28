"""Eve 심리검사 분석: 이브가 DM에서 모은 검사 답변을 DP7 Codex(GPT)가 분석하고, Eve가 결과를 가져가 이브 말투로 전한다.

  POST /internal/edge/eve/gpt-analysis               엣지 토큰. {"request_id","kind":"psych","prompt"} → {"accepted":true}
  GET  /internal/edge/eve/gpt-analysis/{request_id}  엣지 토큰. {"status":"queued"|"running"|"done"|"failed","result","error"}

같은 request_id는 다시 실행하지 않는다. Codex는 읽기 전용 샌드박스, MCP 없이, 빈 작업 폴더에서 prompt만 받아 글을 쓴다.
한 번에 하나씩 돈다. 결과는 저장 전에 비밀값 가림 규칙을 거친다. 기록은 data_dir/eve-gpt/requests.json.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from all_tomorrow.console import ConsoleContext

TIMEOUT = 15 * 60


class AnalysisRequest(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    kind: Literal["psych"]
    prompt: str = Field(min_length=1, max_length=30_000)


def codex_write(prompt: str, workdir: Path) -> str:
    """읽기 전용 Codex로 글 한 편을 받는다. 마지막 답 본문만 돌려준다."""
    from all_tomorrow.adapters.workers import _worker_environment
    from all_tomorrow.overseer.idle_research import short_job_args
    from all_tomorrow.overseer.metacog import _raise_if_quota
    exe = sorted(glob.glob(os.path.expanduser("~/AppData/Local/OpenAI/Codex/bin/*/codex.exe")), key=os.path.getmtime)
    if not exe:
        raise RuntimeError("codex CLI not found")
    out = workdir / "last.txt"
    out.unlink(missing_ok=True)
    try:
        subprocess.run([exe[-1], "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", str(workdir),
                        *short_job_args(), "-o", str(out), "-"],
                       input=prompt.encode("utf-8"), check=True, timeout=TIMEOUT, capture_output=True,
                       env=_worker_environment({}), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.CalledProcessError as error:
        _raise_if_quota(error.stderr, error.stdout)
        raise RuntimeError(f"codex 실패(코드 {error.returncode})") from None
    return out.read_text(encoding="utf-8", errors="replace").strip()


class Jobs:
    def __init__(self, base: Path, run=None) -> None:
        self.path, self.work, self.run = base / "requests.json", base / "work", run or (lambda p, w: codex_write(p, w))
        self.work.mkdir(parents=True, exist_ok=True)
        self.lock, self.slot = threading.Lock(), threading.Semaphore(1)
        with self.lock:   # api가 재시작되면 돌던 것은 실패로 닫는다(Eve는 자기가 대신 만든다)
            data = self.load()
            for r in data.values():
                if r["status"] in ("queued", "running"):
                    r.update(status="failed", error="All Tomorrow 재시작으로 중단")
            self.save(data)

    def load(self) -> dict[str, dict[str, Any]]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def update(self, rid: str, **kw: Any) -> None:
        with self.lock:
            data = self.load()
            data[rid].update(kw)
            self.save(data)

    def submit(self, req: AnalysisRequest) -> bool:
        with self.lock:
            data = self.load()
            if req.request_id in data:
                return False
            data[req.request_id] = {"kind": req.kind, "status": "queued", "result": "", "error": "",
                                    "at": datetime.now(UTC).isoformat(timespec="seconds")}
            self.save(data)
        threading.Thread(target=self._work, args=(req,), daemon=True).start()
        return True

    def _work(self, req: AnalysisRequest) -> None:
        with self.slot:
            self.update(req.request_id, status="running")
            try:
                text = self.run(req.prompt, self.work)
                if not text:
                    raise RuntimeError("빈 결과")
                from all_tomorrow.overseer.redact import Redactor, default_secret_files
                self.update(req.request_id, status="done", result=Redactor.from_files(default_secret_files(Path.home()))(text))
            except Exception as e:  # noqa: BLE001 - 무엇이든 실패로 알려 Eve가 대신 만들게 한다
                self.update(req.request_id, status="failed", error=str(e)[:300])

    def get(self, rid: str) -> dict[str, Any] | None:
        r = self.load().get(rid)
        return None if r is None else {"status": r["status"], "result": r["result"], "error": r["error"]}


def build_router(ctx: ConsoleContext, run=None) -> APIRouter:
    jobs = Jobs(ctx.feature_dir("eve-gpt"), run)
    router = APIRouter()

    def edge(request: Request) -> None:
        if ctx.verify_edge is None:
            raise HTTPException(503, "edge authentication not configured")
        ctx.verify_edge(request.headers.get("authorization"))

    @router.post("/internal/edge/eve/gpt-analysis")
    def submit(req: AnalysisRequest, request: Request) -> dict[str, Any]:
        edge(request)
        jobs.submit(req)
        return {"accepted": True}

    @router.get("/internal/edge/eve/gpt-analysis/{request_id}")
    def status(request_id: str, request: Request) -> dict[str, Any]:
        edge(request)
        found = jobs.get(request_id)
        if found is None:
            raise HTTPException(404, "no such request")
        return found

    return router
