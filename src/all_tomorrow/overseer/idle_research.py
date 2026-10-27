"""놀 때 생산하기: PC가 쉬고 Codex 잔량이 남으면, 사용자가 콘솔 '조사 목록'에 정해 둔 주제를 Codex가 하나씩 조사한다.

- 무엇을 조사할지는 사용자가 정한다(console/research.py, agenda.json). 이 모듈은 언제·얼마나만 정한다.
- 한 번에 하나. 실행기 예약 작업이 1분마다 tick을 부른다: 끝난 실행을 거두고, 차례가 된 주제를 띄운다.
- 차례: 켜진 주제를 목록 위에서부터. 한 번도 안 돌았거나, 반복 주기(repeat_days)가 지났거나,
  실패 뒤 6시간이 지났거나, '지금 돌리기'를 눌렀으면 차례다. 반복 주제는 지난 결과를 들려 보내 바뀐 것 위주로 쓰게 한다.
- 조건: PC 미사용 10분 이상('지금 돌리기'는 무시), Codex 사용량 창이 모두 80% 미만, 하루 8회, research.paused 없음.
- Codex는 사용자 설정(플러그인·MCP)과 웹 검색을 켜고(-c web_search="live") 그 주제의 프로젝트 폴더에서 돈다. 파일은 고치지 않게 한다(프롬프트로).
- 자유 자료와 하위 과제 결과는 원문을 보관만 하고, 저장되면 압축 작업(kind=compress)을 먼저 띄운다(PC 사용 여부·하루 횟수와 무관, 웹 검색 없음).
- 압축할 것이 없으면 종합 작업(kind=synth): 아이디어 하나의 종합본(정리본의 본문)을 이전 종합본 + 새 압축본으로 다시 만든다.
  원문은 넣지 않는다. 압축과 같은 조건·같은 Codex 경로다.
- 결과는 results/<실행 id>.md로 남기고, 끝날 때 보고 1건을 낸다.
- 아이디어에 연결된 주제(idea_id, 아이디어 화면의 '추가 조사')는 돌릴 때 아이디어 맥락을 붙이고, 끝나면 결과를 그 아이디어의 자유 자료로 넣는다.
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
PAGES = "pages"            # 조사 중 크롬으로 읽은 로그인 페이지 원문(pages/<실행 id>/)
COMPRESS_RETRY = 1800      # 압축·종합이 실패하면 30분 뒤 다시, 같은 입력으로 3번 실패하면 그만둔다
COMPRESS_TRIES = 3
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
    if topic.get("idea_id"):   # 아이디어 추가 조사: 짧은 요청에 그 아이디어의 지금 맥락을 붙인다
        prompt = _followup_prompt(topic, folder)
        if prompt:
            return prompt
    return PROMPT.format(cwd=cwd, title=topic["title"], ask=topic["ask"], previous=previous)


def _followup_prompt(topic: dict, folder: Path) -> str:
    from all_tomorrow.console import ideas_followup
    from all_tomorrow.console.ideas import IdeaStore
    try:
        idea = IdeaStore(folder.parent / "ideas").get(topic["idea_id"])
        return ideas_followup.build_prompt(idea, topic["ask"], "codex") if idea else ""
    except Exception as error:   # 맥락을 못 읽어도 요청 원문으로 조사는 한다
        log.warning("추가 조사 맥락 읽기 실패: %s", type(error).__name__)
        return ""


def _file_material(folder: Path, run: dict, output: str) -> str:
    """끝난 추가 조사를 그 아이디어의 자유 자료로 넣는다(아이디어 DB 쓰기는 IdeaStore를 재사용). 반환: 보고에 덧붙일 말."""
    from all_tomorrow.console import ideas_followup
    from all_tomorrow.console.ideas import IdeaStore
    from all_tomorrow.adapters.chrome_pages import FAILED_MARK
    if output.lstrip().startswith(FAILED_MARK):   # 못 가져온 보고는 자료·종합에 넣지 않는다
        run["material_skipped"] = "collection_failed"
        return " 요청한 자료를 가져오지 못한 보고라 아이디어 자료로는 넣지 않았습니다."
    try:
        store = IdeaStore(folder.parent / "ideas")
        if store.get(run["idea_id"]) is None:
            return " (아이디어가 지워져 자료로는 넣지 못했습니다)"
        run["material_id"] = store.add_material(run["idea_id"], ideas_followup.material_item(run.get("request", ""), output, run["id"]))
        store.write_brief(run["idea_id"])
        return f" 아이디어 {run['idea_id']}의 자유 자료로 들어갔습니다(압축본은 곧 정리본에 반영)."
    except Exception as error:
        run["material_error"] = type(error).__name__
        log.warning("추가 조사 자료 넣기 실패: %s", type(error).__name__)
        return " (아이디어 자료로 넣기는 실패했습니다)"


def _file_pages(folder: Path, run: dict) -> str:
    """조사 중 크롬으로 읽은 페이지 원문을 그 아이디어의 자유 자료로 하나씩 넣는다(압축은 자료 압축이 맡는다)."""
    from all_tomorrow.adapters import chrome_pages
    from all_tomorrow.console.ideas import IdeaStore
    pages = chrome_pages.archived(folder / PAGES / run["id"])
    if not pages:
        return ""
    try:
        store = IdeaStore(folder.parent / "ideas")
        idea = store.get(run["idea_id"])
        if idea is None:
            return ""
        have = {(m["url"], m["body"]) for m in idea["materials"]}
        added = 0
        for page in pages:
            if (page["url"], page["text"]) in have:
                continue
            store.add_material(run["idea_id"], {"kind": "url", "label": page["url"], "url": page["url"],
                                                "title": page["title"] or page["url"], "body": page["text"],
                                                "note": f"사용자 크롬(로그인)으로 읽은 원문 · 실행 {run['id']}"})
            added += 1
        run["pages_filed"] = added
        if added:
            store.write_brief(run["idea_id"])
        return f" 크롬으로 읽은 페이지 {added}건도 원문 자료로 넣었습니다." if added else ""
    except Exception as error:
        run["pages_error"] = type(error).__name__
        log.warning("크롬 페이지 자료 넣기 실패: %s", type(error).__name__)
        return " (크롬으로 읽은 페이지를 자료로 넣기는 실패했습니다)"


def _run_item(run: dict) -> str:
    """압축 실행이 맡은 것: "M<id>"(자유 자료) 또는 "R<id>"(하위 과제 결과). 예전 실행은 material_id만 있다."""
    return run.get("item") or f"M{run.get('material_id')}"


def _blocked(mine: list[dict], now: float) -> bool:
    failed = [r for r in mine if r.get("status") != "SUCCESS"]
    # Codex를 못 띄운 실패(EXECUTABLE_NOT_FOUND)는 입력 탓이 아니라 횟수에 넣지 않는다. 예전에는 긴 요청이
    # 명령줄 한도에 걸려 이렇게 기록돼 종합이 영영 멈췄다.
    tries = [r for r in failed if r.get("status") != "EXECUTABLE_NOT_FOUND"]
    return len(tries) >= COMPRESS_TRIES or bool(failed and now - failed[-1]["started"] < COMPRESS_RETRY)


def next_compress(folder: Path, runs: list[dict], now: float) -> dict | None:
    """압축을 기다리는 것 하나(오래된 것부터). 방금 실패한 것·세 번 실패한 것은 건너뛴다."""
    from all_tomorrow.console.ideas import IdeaStore
    if not (folder.parent / "ideas" / "ideas.sqlite").is_file():
        return None
    for item in IdeaStore(folder.parent / "ideas").pending_summaries():
        if not _blocked([r for r in runs if r.get("kind") == "compress" and _run_item(r) == item["key"]], now):
            return item
    return None


def next_synth(folder: Path, runs: list[dict], now: float) -> dict | None:
    """종합이 밀린 아이디어 하나의 일감(IdeaStore.synth_job). 같은 입력으로 방금·세 번 실패한 것은 건너뛴다."""
    from all_tomorrow.console.ideas import IdeaStore
    if not (folder.parent / "ideas" / "ideas.sqlite").is_file():
        return None
    store = IdeaStore(folder.parent / "ideas")
    for idea_id in store.pending_syntheses():
        job = store.synth_job(idea_id)
        if job and not _blocked([r for r in runs if r.get("kind") == "synth" and r.get("idea_id") == idea_id
                                 and r.get("sigs") == job["sigs"]], now):
            return job
    return None


def _start_synth(folder: Path, job: dict, runs: list[dict], now: float, start: Callable[..., dict], cfg: dict) -> str:
    from all_tomorrow.adapters import chrome_pages
    from all_tomorrow.console import ideas_followup
    from all_tomorrow.console.ideas import IdeaStore
    idea = IdeaStore(folder.parent / "ideas").get(job["idea_id"])
    if idea is None:
        return "none"
    run = {"id": "RS-" + time.strftime("%y%m%d-%H%M%S", time.localtime(now)), "kind": "synth", "idea_id": job["idea_id"],
           "sigs": job["sigs"], "incremental": bool(job["previous"]), "title": "종합: " + idea["title"][:40],
           "project_id": "all-tomorrow", "started": now, "status": "RUNNING"}
    try:
        meta = start("all-tomorrow", "codex", ideas_followup.synth_prompt(idea, job),
                     worker_options={"timeout_seconds": min(cfg["timeout"], 900)},
                     argv_suffix=chrome_pages.research_mcp_args())
    except Exception as error:
        run.update(status="FAILED", error=type(error).__name__ + ": " + str(error)[:200], finished=now)
        runs.append(run)
        save_runs(folder, runs)
        return "failed"
    run["run_id"] = meta["run_id"]
    runs.append(run)
    save_runs(folder, runs)
    log.info("아이디어 종합 시작: %s (%s)", idea["title"][:30], meta["run_id"])
    return "synth"


def _start_compress(folder: Path, item: dict, runs: list[dict], now: float, start: Callable[..., dict], cfg: dict) -> str:
    """원문은 두고 압축본만 만들게 한다: 웹 검색 없음, PC 사용 여부와 상관없이 바로."""
    from all_tomorrow import mcp_server
    from all_tomorrow.adapters import chrome_pages
    from all_tomorrow.console import ideas_followup
    from all_tomorrow.console.ideas import IdeaStore
    store = IdeaStore(folder.parent / "ideas")
    idea, material = store.get(item["idea_id"]), store.item(item["key"])
    if idea is None or material is None:
        return "none"
    run = {"id": "RC-" + time.strftime("%y%m%d-%H%M%S", time.localtime(now)) + f"-{item['key']}", "kind": "compress",
           "idea_id": item["idea_id"], "item": item["key"], "title": "압축: " + item["title"][:40],
           "project_id": "all-tomorrow", "started": now, "status": "RUNNING"}
    if item["key"].startswith("M"):
        run["material_id"] = item["id"]
    try:
        meta = start("all-tomorrow", "codex", ideas_followup.compress_prompt(idea, material),
                     worker_options={"timeout_seconds": min(cfg["timeout"], 900)},
                     argv_suffix=chrome_pages.research_mcp_args())
    except Exception as error:
        run.update(status="FAILED", error=type(error).__name__ + ": " + str(error)[:200], finished=now)
        runs.append(run)
        save_runs(folder, runs)
        return "failed"
    run["run_id"] = meta["run_id"]
    runs.append(run)
    save_runs(folder, runs)
    log.info("압축 시작: %s %s (%s)", item["key"], item["title"][:30], meta["run_id"])
    return "compress"


def _finish_compress(folder: Path, run: dict, output: str | None) -> None:
    from all_tomorrow.console.ideas import IdeaStore
    if not output:
        return
    try:
        if not IdeaStore(folder.parent / "ideas").set_summary(_run_item(run), output):
            run["status"], run["error"] = "FAILED", "자료가 없거나 압축본이 비었다"
    except Exception as error:
        run["status"], run["error"] = "FAILED", type(error).__name__


def _finish_synth(folder: Path, run: dict, output: str | None) -> None:
    from all_tomorrow.console.ideas import IdeaStore
    if not output:
        return
    try:
        if not IdeaStore(folder.parent / "ideas").set_synthesis(run["idea_id"], output, run["sigs"]):
            run["status"], run["error"] = "FAILED", "아이디어가 없거나 종합본이 비었다"
    except Exception as error:
        run["status"], run["error"] = "FAILED", type(error).__name__


def _finish(folder: Path, run: dict, info: dict, base: Path) -> None:
    from all_tomorrow.overseer import reports
    status = info.get("status", "UNKNOWN")
    result = info.get("result") or {}
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    output = payload.get("output") if status == "SUCCESS" else None
    run["status"] = status if output else ("FAILED" if status == "SUCCESS" else status)
    run["finished"] = time.time()
    if run.get("kind") in ("compress", "synth"):   # 결과 파일·보고 없이 압축본·종합본만 아이디어에 넣는다
        if run["kind"] == "compress":
            _finish_compress(folder, run, output)
        else:
            _finish_synth(folder, run, output)
        if run["status"] != "SUCCESS":
            run.setdefault("error", str((result.get("error") or info.get("stderr_tail") or status))[:300])
        return
    if output:
        name = run["id"] + ".md"
        path = folder / RESULTS / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {run['title']}\n\n{output.strip()}\n", encoding="utf-8")
        run["result_file"] = name
        tail = _file_material(folder, run, output) + _file_pages(folder, run) if run.get("idea_id") else ""
        reports.enqueue(base, "research-" + run["id"],
                        f"[보고] 유휴 조사 끝: {run['title']} — 콘솔 '조사 목록'에서 결과를 볼 수 있습니다.{tail}")
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
    # 압축·종합은 짧은 일이라 PC가 쉬는지·하루 횟수와 상관없이 주제보다 먼저. 종합은 압축할 것이 없을 때만.
    job = next_compress(folder, runs, now)
    if job and quota_ok(base, cfg["max_percent"], now)[0]:
        started = _start_compress(folder, job, runs, now, start, cfg)
        if started != "none":
            return started
    synth = None if job else next_synth(folder, runs, now)
    if synth and quota_ok(base, cfg["max_percent"], now)[0]:
        started = _start_synth(folder, synth, runs, now, start, cfg)
        if started != "none":
            return started
    if len([r for r in runs if now - r["started"] < 86400 and r.get("kind") not in ("compress", "synth")]) >= cfg["daily"]:
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
    if topic.get("idea_id"):
        run.update(idea_id=topic["idea_id"], request=topic["ask"])
    try:
        from all_tomorrow.adapters import chrome_pages
        meta = start(project_id, "codex", build_task(topic, runs, folder, cwd) + chrome_pages.PROMPT_NOTE,
                     worker_options={"timeout_seconds": cfg["timeout"]},
                     argv_suffix=["-c", 'web_search="live"', *chrome_pages.codex_args(folder / PAGES / run["id"]),
                                  *chrome_pages.research_mcp_args()])
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
