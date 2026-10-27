"""API와 다른 프로세스에서 실행하는 분당 health 검사. 상태는 재기동에도 보존한다."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import time

import httpx

from all_tomorrow.overseer import reports
from all_tomorrow.overseer.workspace import save

log = logging.getLogger(__name__)


def healthy() -> bool:
    port = int(os.environ.get("ALL_TOMORROW_PORT", "5476"))
    try:
        # 새 연결로 accept까지 확인한다. 프록시/리다이렉트로 다른 서버를 검사하지 않는다.
        with httpx.Client(timeout=3, trust_env=False) as client:
            response = client.get(f"http://127.0.0.1:{port}/healthz")
            return response.status_code == 200 and response.json().get("ok") is True
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def powershell(script: str, *args: str) -> str:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); " + script, *args],
        capture_output=True, encoding="utf-8", errors="replace", timeout=25, check=True,
    )
    return result.stdout.strip()


def diagnose() -> dict:
    # 이름/명령줄/요청 내용은 수집하지 않는다. 권한이 없으면 오류 종류만 보존한다.
    port = int(os.environ.get("ALL_TOMORROW_PORT", "5476"))
    try:
        return json.loads(powershell(
            "$ErrorActionPreference='Stop'; "
            f"$c=@(Get-NetTCPConnection -LocalPort {port} -ErrorAction Stop); "
            "$owners=@($c | Where-Object State -eq Listen | Select-Object -ExpandProperty OwningProcess -Unique); "
            "@{connections=@($c | Group-Object State | Select-Object Name,Count); "
            "processes=@(foreach($owner in $owners){$p=Get-Process -Id $owner; "
            "@{pid=$p.Id;handles=$p.HandleCount;threads=@($p.Threads | "
            "Select-Object Id,ThreadState)}})} | ConvertTo-Json -Depth 6 -Compress"
        ))
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return {"unavailable": type(error).__name__}


def restart(task: str) -> None:
    # 작업 이름을 허용 문자로 검증한다. API 작업만 종료하고 정지 확인 뒤 시작한다.
    if not task or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in task):
        raise ValueError("invalid task name")
    powershell(
        "$ErrorActionPreference='Stop'; "
        f"$task='{task}'; Stop-ScheduledTask -TaskName $task; "
        "$deadline=(Get-Date).AddSeconds(15); "
        "while((Get-ScheduledTask -TaskName $task).State -eq 'Running'){"
        "if((Get-Date) -gt $deadline){throw 'API task stop timeout'}; Start-Sleep -Milliseconds 200}; "
        "Start-ScheduledTask -TaskName $task"
    )


def record(base: Path, event: str, **details) -> None:
    entry = {"at": time.time(), "event": event, **details}
    line = json.dumps(entry, ensure_ascii=False)
    # 별도 기록과 API 기록 모두 남긴다. 진단 실패에도 복구를 시도할 수 있게 한다.
    for name in ("api-watchdog.jsonl", "api.log"):
        try:
            with (base / name).open("a", encoding="utf-8") as file:
                file.write(line + "\n")
        except OSError as error:
            log.error("API watchdog record failed: %s", type(error).__name__)


def wake_session(base: Path, task: str, wake=None) -> str:
    """사람 없이 도는 관제(메타인지 세션)를 깨운다. 실패해도 감시는 계속한다."""
    from all_tomorrow.overseer import metacog_session
    try:
        return (wake or metacog_session.wake)(base, metacog_session.Incident(
            fingerprint=metacog_session.fingerprint("api", "restart_blocked"), source="api_watchdog",
            title="중앙 API 재기동 한도 도달",
            detail=("헬스 검사 연속 실패로 1시간 재기동 3회 한도에 닿았다. api-watchdog.json의 blocked를 지우기 전에는 "
                    f"감시가 재시작하지 않는다. 예약 작업 {task}, 기록 api-watchdog.jsonl·api.log."),
            facts={"server_id": "api", "task": task}))
    except Exception as error:
        log.error("metacog wake failed: %s", type(error).__name__)
        return "error"


def check_once(base: Path, *, task="AllTomorrow-DP7-api", probe=healthy,
               recover=restart, diagnostics=diagnose, now=None, wake=None) -> str:
    now = time.time() if now is None else now
    path = base / "api-watchdog.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if state.get("blocked"):
        wake_session(base, task, wake)   # 앞서 다른 세션이 돌아 미뤄졌으면 다시 시도(같은 지문은 한 번만)
        return "blocked"  # 관제가 상태 파일을 지우기 전에는 재시작하지 않는다.
    if probe():
        state["failures"] = 0
        save(path, state)
        try:
            from all_tomorrow.overseer import metacog_session
            metacog_session.resolve(base, "api")
        except Exception as error:
            log.error("metacog resolve failed: %s", type(error).__name__)
        return "healthy"
    state["failures"] = state.get("failures", 0) + 1
    attempts = [at for at in state.get("attempts", []) if now - at < 3600]
    state["attempts"] = attempts
    save(path, state)
    record(base, "health_failed", failures=state["failures"])
    if state["failures"] < 3:
        return "unhealthy"
    if len(attempts) >= 3:
        reports.enqueue(base, f"api-watchdog-limit-{int(attempts[-1])}",
                        "[보고] 중앙 API 헬스 검사 연속 실패. 1시간 재기동 3회 한도에 도달하여 "
                        "자동 복구를 중단했습니다. api-watchdog.jsonl 확인 및 수동 점검이 필요합니다.")
        state["blocked"] = True
        save(path, state)
        record(base, "restart_blocked")
        wake_session(base, task, wake)
        return "blocked"
    # 실패한 재시작도 횟수에 포함한다. 중간에 죽어도 재시도 폭주하지 않는다.
    attempts.append(now)
    state["failures"] = 0
    save(path, state)
    try:
        info = diagnostics()
    except Exception as error:
        info = {"unavailable": type(error).__name__}
    record(base, "restart_requested", task=task, diagnostics=info)
    try:
        recover(task)
    except Exception as error:
        record(base, "restart_failed", error=type(error).__name__)
        return "restart_failed"
    record(base, "restart_started", task=task)
    return "restarted"  # 실제 회복은 다음 health 검사로만 판정한다.
