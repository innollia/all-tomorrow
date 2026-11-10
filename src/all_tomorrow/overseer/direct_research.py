"""아이디어 '바로 조사': 사용자가 고른 CLI·모델이 추가 조사를 쪼개고, 과제를 동시에 돌려 결과를 넣는다.

- 무엇을 돌릴지는 extra_jobs 표에 있다(ideas_rounds.run_extra가 넣는다). task ""가 쪼개기, S6이 과제 하나다.
- 쪼개기가 끝나면 답을 계획에 잇고 과제마다 일을 넣는다. 과제가 끝나면 결과를 처음 조사와 같은 결과로 넣어, 압축·종합이 평소대로 잇는다.
- 사용자가 누른 일이라 PC 사용 여부·하루 횟수·사용량 상한을 보지 않는다. research.paused가 있으면 새로 시작하지 않는다.
- 작업자는 저장소가 아니라 일마다 만든 빈 폴더에서 돈다. 웹에서 읽은 글이 저장소를 고치게 두지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from all_tomorrow.console import ideas_followup, ideas_jev
from all_tomorrow.console.research import research_dir
from all_tomorrow.overseer import auto_worker, idle_research

log = logging.getLogger(__name__)

MAX_RUNNING = 6
MODEL_CACHE = 600
WORKERS = {"claude": "Claude", "codex": "Codex", "antigravity": "Antigravity", "opencode": "OpenCode"}
# Sonnet이 맨 위라 기본값이다. Fable은 사용자가 직접 고를 때만 쓴다.
CLAUDE_MODELS = [("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-opus-5-5", "Opus 5.5"),
                 ("claude-haiku-5-5", "Haiku 5.5"), ("claude-fable-5-1", "Fable 5.1")]
_models: dict[str, Any] = {"at": 0.0, "list": []}


def _cli_lines(worker: str, *args: str) -> list[str]:
    from all_tomorrow.local_workers import EXECUTABLES, discover_executable
    exe = discover_executable(worker) or EXECUTABLES[worker]
    try:
        done = subprocess.run([exe, *args], capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as error:
        log.warning("%s 모델 목록 실패: %s", worker, type(error).__name__)
        return []
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def _list(worker: str) -> list[dict[str, str]]:
    if worker == "claude":
        return [{"id": mid, "name": name} for mid, name in CLAUDE_MODELS]
    if worker == "codex":
        try:
            cache = json.loads((Path.home() / ".codex" / "models_cache.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [{"id": m["slug"], "name": m["slug"]} for m in cache.get("models", []) if m.get("visibility") == "list"]
    if worker == "antigravity":
        rows = [line.split("\t") for line in _cli_lines(worker, "models")]
        return [{"id": r[0], "name": r[1]} for r in rows if len(r) == 2]
    return [{"id": line, "name": line} for line in _cli_lines(worker, "models") if "/" in line]


def models() -> list[dict[str, Any]]:
    """화면의 CLI·모델 고르기. PC마다, 때마다 달라서 각 CLI에게 묻고 10분 기억한다."""
    if time.time() - _models["at"] >= MODEL_CACHE:
        with ThreadPoolExecutor(len(WORKERS)) as pool:
            found = dict(zip(WORKERS, pool.map(_list, WORKERS)))
        _models.update(at=time.time(), list=[{"id": w, "name": WORKERS[w], "models": found[w]} for w in WORKERS])
    return _models["list"]


def launch(worker: str, model: str, pages: Path) -> tuple[dict[str, Any], list[str], str]:
    """작업자 설정, 인자, 프롬프트 끝에 붙일 말. 넷 다 웹 검색이 켜져 있다."""
    from all_tomorrow.adapters import chrome_pages
    if worker == "claude":
        return {}, auto_worker.research_args(pages, sys.executable, model), chrome_pages.CLAUDE_NOTE
    if worker == "codex":
        return ({"model": model, "skip_git_repo_check": True},
                ["-c", 'web_search="live"', *chrome_pages.codex_args(pages), *chrome_pages.research_mcp_args()], chrome_pages.PROMPT_NOTE)
    if worker == "antigravity":
        return {"model": model, "effort": ""}, [], ""   # 모델 이름에 추론 단계가 들어 있어 --effort를 주면 충돌한다
    return {"model": model, "auto": True}, [], ""


def _prompt(store: Any, job: dict[str, Any], idea: dict[str, Any]) -> str:
    if job["task"]:
        task = ideas_jev.task_prompt(idea["plan"], job["task"])
        return task + ideas_followup.DIRECT_TASK if task else ""
    with store.db() as db:
        return db.execute("SELECT prompt FROM extras WHERE idea_id = ? AND n = ?", (job["idea_id"], job["n"])).fetchone()["prompt"] \
            + ideas_followup.DIRECT_SPLIT


def _update(store: Any, job: dict[str, Any], **fields: Any) -> None:
    sets = ", ".join(f"{name} = ?" for name in fields)
    with store.db() as db:
        db.execute(f"UPDATE extra_jobs SET {sets} WHERE id = ?", (*fields.values(), job["id"]))


def _framed(job: dict[str, Any], output: str) -> str:
    """=== 줄을 빠뜨린 답(Haiku가 그랬다)을 결과 블록으로 싼다. 답이 적은 상태를 살리고, 적지 않았으면 불완전이다."""
    head, cut, rest = output.partition("\n---\n")
    status = re.search(r"상태\s*:\s*(완료|불완전|실패)", head)
    body = rest.strip().removesuffix("```").strip() if cut and status else output.strip()
    return (f"=== 자료봉 결과 ===\n아이디어 ID: {job['idea_id']}\n하위과제 ID: {job['task']}\n"
            f"상태: {status.group(1) if status else '불완전'}\n---\n{body}\n=== 끝 ===")


def _file(store: Any, job: dict[str, Any], output: str) -> None:
    """끝난 일의 답을 넣는다. 쪼개기면 과제마다 다음 일을 넣는다. 못 넣으면 ValueError."""
    from all_tomorrow.console.ideas import BLOCK, normalize
    if not job["task"]:
        tasks = ideas_jev.plan_tasks(output)
        if not tasks:
            raise ValueError("답에서 과제(### S6 · 제목)를 찾지 못했다")
        store.add_extra(job["idea_id"], output)
        with store.db() as db:
            for sid in tasks:
                db.execute("""INSERT INTO extra_jobs (idea_id, n, task, worker, model, status, created_at) VALUES (?,?,?,?,?,'WAIT',?)""",
                           (job["idea_id"], job["n"], sid, job["worker"], job["model"], job["created_at"]))
        return
    store.add_slots(job["idea_id"], [output if BLOCK.search(normalize(output)) else _framed(job, output)])
    if not any(r["subtask_id"] == job["task"] for r in store.get(job["idea_id"])["results"]):
        raise ValueError(f"답의 결과 블록이 {job['task']} 것이 아니다")


def _finish(store: Any, folder: Path, job: dict[str, Any], info: dict[str, Any]) -> None:
    result = info.get("result") or {}
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    output = (payload.get("output") or payload.get("response") or "") if info.get("status") == "SUCCESS" else ""
    done = time.time()
    if not output.strip() or output.lstrip().startswith("[수집 실패]"):
        error = output.strip()[:300] or result.get("error") or info.get("stderr_tail") or info.get("status")
        _update(store, job, status="FAILED", error=str(error)[:300], finished=done)
        return
    try:
        _file(store, job, output)
    except ValueError as error:
        _update(store, job, status="FAILED", error=str(error)[:300], finished=done)
        return
    _update(store, job, status="DONE", finished=done)
    idle_research._file_pages(folder, {"id": f"DR-{job['id']}", "idea_id": job["idea_id"]})


def _start(store: Any, folder: Path, job: dict[str, Any], start: Callable[..., dict]) -> None:
    idea = store.get(job["idea_id"])
    prompt = _prompt(store, job, idea) if idea else ""
    if not prompt:
        _update(store, job, status="FAILED", error="과제의 하위 프롬프트를 찾지 못했다", finished=time.time())
        return
    work = folder / "direct-work" / str(job["id"])
    work.mkdir(parents=True, exist_ok=True)
    options, suffix, note = launch(job["worker"], job["model"], folder / idle_research.PAGES / f"DR-{job['id']}")
    try:
        meta = start("all-tomorrow", job["worker"], prompt + note, cwd=work, argv_suffix=suffix,
                     worker_options={"timeout_seconds": idle_research.settings()["timeout"], **options})
    except Exception as error:
        _update(store, job, status="FAILED", error=type(error).__name__ + ": " + str(error)[:200], finished=time.time())
        return
    _update(store, job, status="RUNNING", run_id=meta["run_id"], started=time.time())
    log.info("바로 조사 시작: %s %s %s/%s", job["idea_id"], job["task"] or "쪼개기", job["worker"], job["model"])


def tick(base: Path, *, start: Callable[..., dict] | None = None, read: Callable[[str], dict] | None = None,
         folder: Path | None = None) -> str:
    """끝난 일을 거두고 기다리는 일을 띄운다. 반환: finished|started|paused|running|none."""
    from all_tomorrow.console.ideas import IdeaStore
    folder = folder or research_dir()
    if start is None or read is None:
        from all_tomorrow import mcp_server
        start = start or mcp_server.start_run
        read = read or (lambda run_id: mcp_server.read_run(mcp_server.RUNS_DIR / run_id))
    if not os.path.exists(folder.parent / "ideas"):
        return "none"
    store = IdeaStore(folder.parent / "ideas")

    def jobs(status: str) -> list[dict[str, Any]]:
        with store.db() as db:
            return [dict(j) for j in db.execute("SELECT * FROM extra_jobs WHERE status = ? ORDER BY id", (status,))]
    running = jobs("RUNNING")
    finished = False
    for job in running:
        try:
            info = read(job["run_id"])
        except (OSError, ValueError):
            info = {"status": "LOST"}
        if info.get("status") != "RUNNING":
            _finish(store, folder, job, info)
            running = [j for j in running if j["id"] != job["id"]]
            finished = True
    waiting = jobs("WAIT")   # 방금 끝난 쪼개기의 과제까지
    if (base / idle_research.PAUSE).exists():
        return "finished" if finished else "paused"
    for job in waiting[:max(0, MAX_RUNNING - len(running))]:
        _start(store, folder, job, start)
    if waiting:
        return "started"
    return "finished" if finished else "running" if running else "none"

