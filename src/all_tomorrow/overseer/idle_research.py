"""놀 때 생산하기: PC가 쉬고 Codex 잔량이 남으면, 사용자가 콘솔 '조사 목록'에 정해 둔 주제를 Codex가 하나씩 조사한다.

- 무엇을 조사할지는 사용자가 정한다(console/research.py, agenda.json). 이 모듈은 언제·얼마나만 정한다.
- 한 번에 하나. 실행기 예약 작업이 1분마다 tick을 부른다: 끝난 실행을 거두고, 차례가 된 주제를 띄운다.
- 차례: 켜진 주제를 목록 위에서부터. 한 번도 안 돌았거나, 반복 주기(repeat_days)가 지났거나,
  실패 뒤 6시간이 지났거나, '지금 돌리기'를 눌렀으면 차례다. 반복 주제는 지난 결과를 들려 보내 바뀐 것 위주로 쓰게 한다.
- 조건: PC 미사용 10분 이상('지금 돌리기'는 무시), Codex 사용량 창이 모두 80% 미만, 하루 8회, research.paused 없음.
- Codex는 웹 검색을 켜고(-c web_search="live") 그 주제의 프로젝트 폴더에서 돈다. 파일은 고치지 않게 한다.
- 결과는 results/<실행 id>.md로 남기고, 끝날 때 보고 1건을 낸다.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from all_tomorrow.console.research import RESULTS, load_runs, load_topics, research_dir, save_runs

log = logging.getLogger(__name__)

PAUSE = "research.paused"
RETRY_AFTER = 6 * 3600
PROMPT = """너는 All Tomorrow의 유휴 조사 담당이다. 사용자가 정해 둔 주제를 웹 검색으로 조사해 한국어 보고서 하나로 답한다.
사용자는 지금 자리에 없다. 묻지 말고 끝까지 조사한다.

규칙:
- 파일을 만들거나 고치지 않는다. 명령으로 바꾸는 일(설치·커밋·삭제)도 하지 않는다. 읽기와 웹 검색만 한다.
- 주장마다 출처 링크를 붙인다. 날짜가 중요한 사실은 언제 기준인지 적는다. 모르는 것은 모른다고 적는다.
- 이 폴더({cwd})는 이 주제와 관련된 프로젝트다. 필요하면 README·docs를 읽어 맥락을 잡는다.
- 마지막 답이 그대로 보고서가 된다. 형식:
  ## 한 줄 결론
  ## 찾은 것   (항목마다 출처)
  ## 우리에게 주는 뜻   (이 프로젝트·사업에 바로 쓸 수 있는 것)
  ## 더 볼 것

주제: {title}
요청:
{ask}
{previous}"""


def settings() -> dict:
    env = os.environ.get
    return {"idle_seconds": float(env("ALL_TOMORROW_RESEARCH_IDLE_SECONDS", "600")),
            "daily": int(env("ALL_TOMORROW_RESEARCH_DAILY", "8")),
            "max_percent": float(env("ALL_TOMORROW_RESEARCH_MAX_PERCENT", "80")),
            "timeout": int(env("ALL_TOMORROW_RESEARCH_TIMEOUT", "1800"))}


def quota_ok(base: Path, max_percent: float, now: float) -> tuple[bool, str]:
    import json
    try:
        snapshot = json.loads((base / "subscription-usage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "사용량 모름"
    codex = next((p for p in snapshot.get("providers", []) if p.get("id") == "codex"), None)
    if not codex or codex.get("status") != "connected":
        return False, "Codex 사용량 모름"
    for window in codex.get("windows", []):
        try:
            reset = datetime.fromisoformat(window["resets_at"]).timestamp() if window.get("resets_at") else None
        except ValueError:
            reset = None
        if (reset is None or reset > now) and float(window.get("percent", 0)) >= max_percent:
            return False, f"Codex {window.get('label')} {window.get('percent'):g}%"
    return True, "잔량 있음"


def due(topic: dict, runs: list[dict], now: float, idle_ok: bool) -> bool:
    if not topic.get("enabled", True):
        return False
    mine = [r for r in runs if r.get("topic_id") == topic["id"]]
    last = mine[-1] if mine else None
    if topic.get("run_now_at") and (last is None or topic["run_now_at"] > last["started"]):
        return True
    if not idle_ok:
        return False
    if last is None:
        return True
    if last.get("status") != "SUCCESS":
        return now - last["started"] >= RETRY_AFTER
    repeat = float(topic.get("repeat_days") or 0)
    return repeat > 0 and now - last["started"] >= repeat * 86400


def build_task(topic: dict, runs: list[dict], folder: Path, cwd: str) -> str:
    previous = ""
    done = [r for r in runs if r.get("topic_id") == topic["id"] and r.get("status") == "SUCCESS" and r.get("result_file")]
    if done:
        try:
            text = (folder / RESULTS / done[-1]["result_file"]).read_text(encoding="utf-8")
            when = time.strftime("%Y-%m-%d", time.localtime(done[-1]["started"]))
            previous = (f"\n지난 결과({when}). 이번에는 이 뒤로 새로 바뀐 것·새로 나온 것 위주로 쓰고, 그대로인 것은 짧게 적는다:\n"
                        f"<previous>\n{text[:6000]}\n</previous>\n")
        except OSError:
            pass
    return PROMPT.format(cwd=cwd, title=topic["title"], ask=topic["ask"], previous=previous)


def _finish(folder: Path, run: dict, info: dict, base: Path) -> None:
    from all_tomorrow.overseer import reports
    status = info.get("status", "UNKNOWN")
    result = info.get("result") or {}
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    output = payload.get("output") if status == "SUCCESS" else None
    run["status"] = status if output else ("FAILED" if status == "SUCCESS" else status)
    run["finished"] = time.time()
    if output:
        name = run["id"] + ".md"
        path = folder / RESULTS / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {run['title']}\n\n{output.strip()}\n", encoding="utf-8")
        run["result_file"] = name
        reports.enqueue(base, "research-" + run["id"],
                        f"[보고] 유휴 조사 끝: {run['title']} — 콘솔 '조사 목록'에서 결과를 볼 수 있습니다.")
    else:
        error = result.get("error") or info.get("stderr_tail") or status
        run["error"] = str(error)[:300]


def tick(base: Path, idle: float | None, *, now: float | None = None,
         start: Callable[..., dict] | None = None, read: Callable[[str], dict] | None = None,
         folder: Path | None = None) -> str:
    """반환: 무엇을 했는지 한 단어(running|finished|started|paused|idle|budget|quota|none)."""
    now = time.time() if now is None else now
    folder = folder or research_dir()
    if start is None or read is None:
        from all_tomorrow import mcp_server
        start = start or mcp_server.start_run
        # @mcp.tool로 감싼 get_run 대신 같은 일을 하는 read_run을 직접 부른다.
        read = read or (lambda run_id: mcp_server.read_run(mcp_server.RUNS_DIR / run_id))
    runs = load_runs(folder)
    active = next((r for r in runs if r.get("status") == "RUNNING"), None)
    if active:
        try:
            info = read(active["run_id"])
        except (OSError, ValueError):
            info = {"status": "LOST"}
        if info.get("status") == "RUNNING":
            return "running"
        _finish(folder, active, info, base)
        save_runs(folder, runs)
        return "finished"
    if (base / PAUSE).exists():
        return "paused"
    cfg = settings()
    if len([r for r in runs if now - r["started"] < 86400]) >= cfg["daily"]:
        return "budget"
    idle_ok = idle is not None and idle >= cfg["idle_seconds"]
    topic = next((t for t in load_topics(folder) if due(t, runs, now, idle_ok)), None)
    if topic is None:
        return "none" if idle_ok else "idle"
    ok, reason = quota_ok(base, cfg["max_percent"], now)
    if not ok:
        return "quota"
    from all_tomorrow import mcp_server
    project = mcp_server.load_projects().get(topic.get("project_id") or "all-tomorrow")
    project_id = topic.get("project_id") if project else "all-tomorrow"
    cwd = (project or mcp_server.load_projects().get("all-tomorrow", {})).get("path", "")
    run = {"id": "RR-" + time.strftime("%y%m%d-%H%M%S", time.localtime(now)), "topic_id": topic["id"],
           "title": topic["title"], "project_id": project_id, "started": now, "status": "RUNNING"}
    try:
        meta = start(project_id, "codex", build_task(topic, runs, folder, cwd),
                     worker_options={"timeout_seconds": cfg["timeout"]}, argv_suffix=["-c", 'web_search="live"'])
    except Exception as error:
        run.update(status="FAILED", error=type(error).__name__ + ": " + str(error)[:200], finished=now)
        runs.append(run)
        save_runs(folder, runs)
        log.warning("유휴 조사 시작 실패: %s", type(error).__name__)
        return "failed"
    run["run_id"] = meta["run_id"]
    runs.append(run)
    save_runs(folder, runs)
    log.info("유휴 조사 시작: %s (%s)", topic["title"], meta["run_id"])
    return "started"
