"""메타인지 = 사용자 없이 도는 관제. 이상이 생기면 헤드리스 Claude Code 세션 하나를 띄운다.

올투모로우 코드는 얇게 둔다: 언제 깨울지(wake/resolve), 무엇을 들려 보낼지(build_prompt: docs/overseer-role.md
+ 이상 기록), 얼마나 쓸지(하루 횟수·시간·턴 상한), 무엇을 남겼는지(metacog-journal.md 맨 위 + 보고 1건).
판단·조사·수리는 세션(도구를 가진 Claude)이 하고, 무거운 코딩·조사는 all-tomorrow MCP dispatch_task로 Codex에 맡긴다.

- 계기: server_watch(autostart 서버 3번 시작 실패로 재시도 중단)와 api_watchdog(API 재기동 한도).
- 지문(fingerprint) = 서버 id + 오류 종류. 같은 지문은 한 번만 깨운다. 서버가 살아나면(resolve) 지문을 지워
  다음에 같은 이상이 다시 생기면 다시 깨운다. 보고(reports.enqueue)도 깨울 때·세션이 끝날 때 한 번씩만.
- 세션은 감시 예약 작업이 떼어 낸 프로세스(`python -m all_tomorrow.overseer.metacog_session run`)에서 뜬다.
  Claude 데스크톱 앱 셸에서 띄우지 않는다(MSIX AppData 가상화).
- 비밀값: key-pool.env에서 온 환경 변수는 세션 환경에서 뺀다. 일지·보고는 redact를 거친다.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from all_tomorrow.adapters.workers import CLAUDE_DENY, _worker_environment
from all_tomorrow.overseer import reports
from all_tomorrow.overseer.environment import REPO
from all_tomorrow.overseer.workspace import save

log = logging.getLogger(__name__)

STATE = "metacog-incidents.json"
RUNS = "metacog-sessions.jsonl"
LOCK = "metacog-session.lock"
PAUSE = "metacog-session.paused"
JOURNAL = "metacog-journal.md"
WORKDIR = Path(os.environ.get("ALL_TOMORROW_METACOG_SESSION_CWD", r"C:\projects"))

# 권한은 사용자 터미널과 같게(사용자 설정·MCP·전체 도구, bypassPermissions). 사용자 규칙에서 나온 차단만 남긴다:
# git push, 비밀값 파일 읽기, rm -rf / reset --hard / git clean. 나머지 "먼저 묻는 일"은 overseer-role.md가 정한다.
DENY = CLAUDE_DENY


def settings() -> dict:
    env = os.environ.get
    return {"daily": int(env("ALL_TOMORROW_METACOG_SESSION_DAILY", "12")),
            "minutes": float(env("ALL_TOMORROW_METACOG_SESSION_MINUTES", "60")),
            "turns": int(env("ALL_TOMORROW_METACOG_SESSION_TURNS", "100")),
            "model": env("ALL_TOMORROW_METACOG_SESSION_MODEL", "")}


@dataclass
class Incident:
    fingerprint: str          # 서버 id + ":" + 오류 종류
    source: str               # server_watch | api_watchdog
    title: str                # 사람이 읽는 한 줄
    detail: str               # 마지막 상태, 켜는 방법 등
    facts: dict = field(default_factory=dict)


def fingerprint(server_id: str, kind: str) -> str:
    kind = re.sub(r"\d+", "N", kind or "unknown")          # "HTTP 503"와 "HTTP 502"는 같은 종류
    return f"{server_id}:{re.sub(r'\s+', ' ', kind).strip()[:80]}"


def load_state(base: Path) -> dict:
    try:
        return json.loads((base / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _safe_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "-", text).strip("-")[:60] or "incident"


def session_running(base: Path) -> bool:
    from all_tomorrow.overseer.runtime import singleton
    try:
        with singleton(base / LOCK):
            return False
    except OSError:
        return True


def wake(base: Path, incident: Incident, *, launch: Callable | None = None, now: float | None = None,
         running: Callable[[Path], bool] = session_running) -> str:
    """이상 하나를 받는다. 반환: woken|duplicate|paused|budget|busy. 매 점검마다 불러도 된다."""
    now = time.time() if now is None else now
    launch = launch or spawn
    state = load_state(base)
    incidents = state.setdefault("incidents", {})
    entry = incidents.get(incident.fingerprint)
    if entry and entry.get("woke"):
        return "duplicate"
    if entry is None:
        entry = incidents[incident.fingerprint] = {**asdict(incident), "opened": now, "woke": None}
    cfg = settings()
    runs = [t for t in state.get("runs", []) if now - t < 86400]
    state["runs"] = runs
    if (base / PAUSE).exists():
        result = "paused"
    elif len(runs) >= cfg["daily"]:
        result = "budget"
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        reports.enqueue(base, f"metacog-session-budget-{day}",
                        f"[보고] 메타인지 세션 하루 {cfg['daily']}회 상한에 닿아 '{incident.title}'을(를) 맡기지 못했습니다.")
    elif running(base):
        result = "busy"          # 다음 점검에서 다시 시도한다
    else:
        entry["woke"] = now
        runs.append(now)
        result = "woken"
    save(base / STATE, state)
    if result == "woken":
        try:
            launch(base, incident.fingerprint)
        except Exception as error:
            entry["woke"], entry["launch_error"] = None, type(error).__name__
            runs.remove(now)
            save(base / STATE, state)
            log.error("metacog session launch failed: %s", type(error).__name__)
            return "launch_failed"
    return result


def safe_wake(base: Path, incident: Incident) -> str:
    """감시 쪽 기본값. 깨우기가 실패해도 감시는 계속 돈다."""
    try:
        return wake(base, incident)
    except Exception as error:
        log.error("metacog wake failed: %s", type(error).__name__)
        return "error"


def resolve(base: Path, server_id: str) -> list[str]:
    """서버가 살아났다 = 상태가 바뀌었다. 그 서버의 지문을 지운다(다음 이상은 다시 깨운다)."""
    state = load_state(base)
    incidents = state.get("incidents", {})
    gone = [fp for fp in incidents if fp.split(":", 1)[0] == server_id]
    if gone:
        for fp in gone:
            closed = incidents.pop(fp)
            state.setdefault("closed", []).append({"fingerprint": fp, "opened": closed.get("opened"),
                                                   "closed": time.time(), "session": closed.get("session")})
        state["closed"] = state["closed"][-50:]
        save(base / STATE, state)
    return gone


def spawn(base: Path, fp: str) -> None:
    """감시 예약 작업(1분 제한) 밖으로 떼어 낸 프로세스로 세션 실행기를 띄운다."""
    argv = [sys.executable, "-m", "all_tomorrow.overseer.metacog_session", "--dir", str(base), "run", fp]
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    common = dict(cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
    try:
        subprocess.Popen(argv, creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), **common)
    except OSError:
        subprocess.Popen(argv, creationflags=flags, **common)


# ---- 세션 ------------------------------------------------------------------------------------

PROMPT = """너는 All Tomorrow의 메타인지다. 메타인지 = 사용자 없이 도는 관제. 아래 <role>의 관제 지침을 그대로 따른다.
지금 사람은 없다. 묻지 말고 스스로 조사하고 고친다. 단 지침의 "먼저 묻는 일"(사용자 자료 삭제, 권한·비용 확대,
남의(팀) 저장소 push, 비밀값 출력, 방향 선택)은 하지 말고 마지막 답의 "물을 것"에 남긴다. git push는 하지 않는다. 코드를 고쳤으면 지금 브랜치에 커밋하지 말고 `git switch -c metacog/<날짜>-<짧은 이름>`으로 새 브랜치를 만들어 거기에만 커밋하고, 일지에 브랜치 이름을 적는다. 합치는 것은 관제가 감사한 뒤에 한다.

깨운 이유(감시가 스스로 못 고친 이상):
- 제목: {title}
- 지문: {fingerprint} (출처 {source})
- 상태: {detail}
- 기록: {facts}

일하는 법:
- 근거부터 본다: 감시 상태 {base}\\server-watch.json, 기록 {base}\\server-watch.jsonl, API 감시 {base}\\api-watchdog.jsonl,
  서버 목록(감시가 지금 쓰는 파일) {registry}. 큰 판단 전에는 {base}\\control-brief.md(노션 요약 포함)를 읽는다.
  노션은 읽기만 한다. 비밀값 파일(~/.all-tomorrow/key-pool.env, .env, 자격 증명)은 열지 않는다.
- 같은 문제로 두 번 실패했거나 처음 보는 오류면 세 번째 시도 전에 oracle_ask(신탁)로 묻는다(project: 작업 폴더 이름).
- 무거운 코딩·조사는 all-tomorrow MCP dispatch_task(project_id, worker="codex", task)로 맡기고 get_run으로 결과를 확인한다.
- 이 세션은 감시 예약 작업에서 떼어 낸 프로세스다. 오래 도는 서버를 이 세션의 자식으로 직접 띄우지 않는다(세션이 끝나면 같이 죽는다).
  서버는 감시가 켜게 한다: 원인을 고친 뒤 server-watch.json에서 그 서버 항목을 "starts": 0, "blocked": false로 두고
  `schtasks /Run /TN AllTomorrow-DP7-api-watchdog`(감시 작업)를 실행한다. 감시의 서버 점검은 4분 간격이라
  server-watch.json의 last_sweep도 0으로 두면 바로 점검한다. 예약 작업 재시작은 `schtasks /End` 뒤 `/Run`.
- 고친 뒤 실제로 살아났는지(health 주소, 포트) 확인하고 끝낸다. 실행 상한: {turns}턴, {minutes:g}분.
- Tailscale·API·Eve 봇은 이번 이상과 직접 관계가 없으면 건드리지 않는다.

마지막 답은 일지에 그대로 들어간다. 한국어로 짧게, 정확히 이 형식만 쓴다:
### 본 것
(근거와 원인)
### 한 것
(실행한 조치, 바꾼 파일)
### 결과
(첫 줄은 해결|일부 해결|미해결 중 하나, 그 뒤 확인한 사실)
### 남은 것
(없으면 없음)
### 물을 것
(사람이 정해야 할 것, 없으면 없음)

<role>
{role}
</role>
"""


def registry_path() -> Path:
    from all_tomorrow.console import servers
    return Path(os.environ.get("ALL_TOMORROW_SERVER_REGISTRY") or servers.REGISTRY)


def build_prompt(base: Path, entry: dict, cfg: dict) -> str:
    role = (REPO / "docs" / "overseer-role.md").read_text(encoding="utf-8")
    return PROMPT.format(title=entry["title"], fingerprint=entry["fingerprint"], source=entry["source"],
                         detail=entry["detail"], facts=json.dumps(entry.get("facts", {}), ensure_ascii=False),
                         base=base, registry=registry_path(), turns=cfg["turns"], minutes=cfg["minutes"], role=role)


def mcp_config(base: Path) -> Path:
    """oracle·all-tomorrow만. DP7 Python으로 띄운다(Syncthing .venv 실행기는 예약 작업에서 안 뜬 적이 있다)."""
    servers = {"oracle": {"type": "stdio", "command": sys.executable, "args": ["-m", "all_tomorrow.overseer.oracle_mcp"]},
               "all-tomorrow": {"type": "stdio", "command": sys.executable, "args": ["-m", "all_tomorrow.mcp_server"]}}
    path = base / "metacog-mcp.json"
    save(path, {"mcpServers": servers})
    return path


def claude_executable() -> str:
    found = shutil.which("claude")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(local)


def build_argv(base: Path, cfg: dict) -> list[str]:
    argv = [claude_executable(), "-p", "--output-format", "json", "--max-turns", str(cfg["turns"]),
            "--mcp-config", str(mcp_config(base)),   # 사용자 MCP 위에 all-tomorrow·oracle을 더한다
            "--disallowedTools", ",".join(DENY), "--permission-mode", "bypassPermissions"]
    if cfg["model"]:          # 기본은 지정하지 않는다(최상위 고가 모델 금지)
        argv += ["--model", cfg["model"]]
    return argv


def session_env(key_pool: Path | None = None) -> dict:
    """key-pool.env에서 온 값(비밀값)은 세션 환경에서 뺀다. 이름만 읽는다. ANTHROPIC_API_KEY도 뺀다(구독 로그인)."""
    return _worker_environment({}, key_pool)


def run_claude(prompt: str, argv: list[str], *, cwd: Path, timeout: float) -> dict:
    """stdin으로 프롬프트를 넣고 JSON 결과를 읽는다. 시간을 넘기면 프로세스 트리를 끊는다."""
    started = time.monotonic()
    proc = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=session_env(),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        out, _ = proc.communicate(prompt.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            proc.kill()
        proc.communicate()
        return {"ok": False, "error": "timeout", "duration_s": round(time.monotonic() - started)}
    duration = round(time.monotonic() - started)
    try:
        data = json.loads(out.decode("utf-8", errors="replace"))
    except ValueError:
        return {"ok": False, "error": f"출력 해석 실패(rc={proc.returncode})", "duration_s": duration}
    return {"ok": data.get("subtype") == "success" and not data.get("is_error"),
            "error": "" if data.get("subtype") == "success" else str(data.get("subtype")),
            "text": data.get("result") or "", "turns": data.get("num_turns"),
            "duration_s": duration, "api_s": round((data.get("duration_api_ms") or 0) / 1000),
            "cost_usd": data.get("total_cost_usd"), "session_id": data.get("session_id"),
            "denials": len(data.get("permission_denials") or [])}


def result_line(text: str) -> str:
    m = re.search(r"###\s*결과\s*\n+\s*([^\n]+)", text or "")
    return m.group(1).strip() if m else "(결과 칸 없음)"


def write_journal(base: Path, entry: dict, result: dict, redact: Callable[[str], str]) -> None:
    path = base / JOURNAL
    stamp = time.strftime("%Y-%m-%d %H:%M")
    cost = result.get("cost_usd")
    meta = (f"- 세션: Claude 헤드리스 · 지문 `{entry['fingerprint']}` · {result.get('turns', '?')}턴 · "
            f"{result.get('duration_s', '?')}초" + (f" · 환산 ${cost:.2f}" if isinstance(cost, (int, float)) else "")
            + (f" · 세션 {result['session_id']}" if result.get("session_id") else ""))
    body = result.get("text") or f"(세션 실패: {result.get('error', '알 수 없음')})"
    if result.get("error") and result.get("text"):
        body += f"\n\n(세션 종료 사유: {result['error']})"
    lines = [f"## {stamp} 메타인지 세션 — {entry['title']}", "", meta, "", body.strip(), ""]
    old = path.read_text(encoding="utf-8") if path.exists() else "# 메타인지 일지\n\n최신이 위.\n\n"
    head, sep, rest = old.partition("\n\n최신이 위.\n\n")
    if not sep:
        head, rest = "# 메타인지 일지", old
    temp = path.with_suffix(".md.tmp")
    temp.write_text(f"{head}\n\n최신이 위.\n\n" + redact("\n".join(lines)) + "\n" + rest, encoding="utf-8")
    temp.replace(path)


def default_redact() -> Callable[[str], str]:
    from all_tomorrow.overseer.redact import Redactor, default_secret_files
    return Redactor.from_files(default_secret_files(Path.home()))


def run(base: Path, fp: str, *, runner: Callable[..., dict] = run_claude,
        redact: Callable[[str], str] | None = None) -> dict:
    """떼어 낸 프로세스의 본문: 잠금 → 세션 → 일지 → 보고 1건."""
    from all_tomorrow.overseer.runtime import singleton
    cfg = settings()
    redact = redact or default_redact()
    try:
        lock = singleton(base / LOCK)
        lock.__enter__()
    except OSError:
        state = load_state(base)           # 다른 세션이 돌고 있다: 다음 점검에서 다시 깨우게 되돌린다
        entry = state.get("incidents", {}).get(fp)
        if entry:
            entry["woke"] = None
            state["runs"] = state.get("runs", [])[:-1]
            save(base / STATE, state)
        return {"ok": False, "error": "busy"}
    try:
        entry = load_state(base).get("incidents", {}).get(fp)
        if entry is None:
            return {"ok": False, "error": "incident gone"}
        prompt = build_prompt(base, entry, cfg)
        result = runner(prompt, build_argv(base, cfg), cwd=WORKDIR, timeout=cfg["minutes"] * 60)
        write_journal(base, entry, result, redact)
        summary = {k: result.get(k) for k in ("ok", "error", "turns", "duration_s", "api_s", "cost_usd",
                                              "session_id", "denials")}
        summary["result"] = result_line(result.get("text", ""))
        with (base / RUNS).open("a", encoding="utf-8") as file:
            file.write(json.dumps({"at": time.time(), "fingerprint": fp, **summary}, ensure_ascii=False) + "\n")
        state = load_state(base)
        if fp in state.get("incidents", {}):
            state["incidents"][fp]["session"] = summary
        else:   # 세션이 고쳐서 감시가 먼저 resolve했다: 닫힌 기록에 붙인다
            for closed in reversed(state.get("closed", [])):
                if closed["fingerprint"] == fp and closed.get("opened") == entry.get("opened"):
                    closed["session"] = summary
                    break
        save(base / STATE, state)
        asks = re.search(r"###\s*물을 것\s*\n+(.+?)(?:\n###|\Z)", result.get("text", ""), re.S)
        ask = asks.group(1).strip() if asks and not asks.group(1).strip().startswith("없음") else ""
        content = (f"[메타인지] {entry['title']} → {summary['result'] if result.get('text') else '세션 실패: ' + str(result.get('error'))}"
                   + (f"\n물을 것: {ask[:400]}" if ask else "") + "\n자세한 내용: metacog-journal.md")
        reports.enqueue(base, f"metacog-session-{_safe_id(fp)}-{int(entry['opened'])}", redact(content))
        return summary
    finally:
        lock.__exit__(None, None, None)


def main(argv: list[str] | None = None) -> int:
    from all_tomorrow.overseer.environment import load_key_pool
    from all_tomorrow.overseer.store import default_dir
    parser = argparse.ArgumentParser(prog="all_tomorrow.overseer.metacog_session")
    parser.add_argument("--dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="지문 하나의 세션을 실행한다(감시가 떼어 낸 프로세스로 부른다)")
    r.add_argument("fingerprint")
    sub.add_parser("status", help="열린 이상과 최근 세션")
    args = parser.parse_args(argv)
    load_key_pool()
    base = args.dir or default_dir()
    if args.cmd == "status":
        print(json.dumps(load_state(base), ensure_ascii=False, indent=2))
        return 0
    logging.basicConfig(filename=base / "metacog-session.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log.info("session start fingerprint=%s pid=%s", args.fingerprint, os.getpid())
    try:
        summary = run(base, args.fingerprint)
    except Exception as error:
        log.exception("session failed: %s", type(error).__name__)
        return 1
    log.info("session end %s", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
