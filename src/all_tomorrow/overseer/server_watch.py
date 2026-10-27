"""DP7 서버 목록(config/infrastructure.json) 전체 감시: 죽은 autostart 서버를 적힌 방법으로 켜고,
부팅 10분 뒤 한 번 요약(boot-report.md)을 쓴다. api-watchdog 작업이 매분 부르고, 점검은 5분 간격으로 줄인다.

- API(id=api)와 감시 자신은 api_watchdog.check_once가 맡는다(부팅 직후 느린 응답을 3분 기다리는 규칙).
- 같은 서버를 MAX_STARTS번 켰는데도 다음 점검에서 죽어 있으면 재시도를 멈추고 reports.enqueue로 보고한다.
  서버가 다시 살아나면 상태를 지운다. 비밀값은 다루지 않는다(시작 명령에 비밀값을 적지 않는다).
- 재시도를 멈출 때 메타인지 세션(metacog_session: 헤드리스 Claude)을 깨운다. 같은 지문(서버 id+오류 종류)은
  한 번만 깨우고, 서버가 살아나면 지문을 지워 다음 이상 때 다시 깨운다.
- 시험·리허설: ALL_TOMORROW_SERVER_REGISTRY(서버 목록 사본 경로), ALL_TOMORROW_SERVER_SWEEP_SECONDS(점검 간격).
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from all_tomorrow.console import servers
from all_tomorrow.overseer import api_watchdog, metacog_session, reports
from all_tomorrow.overseer.workspace import save

log = logging.getLogger(__name__)

SWEEP_SECONDS = 240       # 1분 주기 작업 안에서 5분 안팎마다 한 번
MAX_STARTS = 3
BOOT_REPORT_AFTER = 600   # 부팅 10분 뒤
GAP_SECONDS = 180         # 이보다 오래 이 감시가 안 돌았으면 PC가 꺼졌다 켜진 것으로 본다
HANDLED_ELSEWHERE = frozenset({"api", "api-watchdog"})
STATE = "server-watch.json"
LOG = "server-watch.jsonl"


def load_registry():
    """감시가 쓰는 서버 목록. ALL_TOMORROW_SERVER_REGISTRY가 있으면 그 사본(시험·리허설)."""
    override = os.environ.get("ALL_TOMORROW_SERVER_REGISTRY")
    return servers.load_registry(Path(override)) if override else servers.load_registry()


def sweep_seconds() -> float:
    try:
        return float(os.environ.get("ALL_TOMORROW_SERVER_SWEEP_SECONDS") or SWEEP_SECONDS)
    except ValueError:
        return SWEEP_SECONDS


def error_kind(entry: dict, detail: str) -> str:
    """지문의 오류 종류: 시작 예외 이름이 있으면 그것, 없으면 마지막 상태 문구."""
    return entry.get("last_error") or detail


def local_host() -> str:
    return platform.node().split(".")[0].lower()


def local_services(registry) -> list:
    host = local_host()
    return [s for s in registry.services if s.host_id == host]


def observe(service) -> tuple[str, str]:
    """(ok|failed|unknown, 이유). 읽기 전용."""
    health = service.health
    if health.kind == "http":
        try:
            with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as client:
                code = client.get(health.target).status_code
        except httpx.HTTPError:
            return "failed", "HTTP 응답 없음"
        return ("ok", f"HTTP {code}") if 200 <= code < 300 else ("failed", f"HTTP {code}")
    if health.kind == "tcp":
        try:
            with socket.create_connection((health.target, service.ports[0]), 1.5):
                return "ok", f"TCP {service.ports[0]} 연결"
        except OSError:
            return "failed", f"TCP {service.ports[0]} 연결 실패"
    if health.kind == "tailscale":
        return servers.observe_tailscale()
    if health.kind == "docker":
        return servers.observe_docker()
    if health.kind in ("windows_task", "process"):
        return servers.windows_observation(health)
    return "unknown", "확인 방법 없음"


def user_logged_on() -> bool:
    """트레이 앱처럼 로그온 세션이 필요한 서버는 로그온 전에는 켜지 않는다(로그인 방식 Tailscale)."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq explorer.exe", "/NH"], capture_output=True,
                             text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return "explorer.exe" in out.lower()


def start(service) -> None:
    spec = service.start
    if spec.kind == "task":
        api_watchdog.powershell(
            "$ErrorActionPreference='Stop'; "
            f"$t=Get-ScheduledTask -TaskName '{spec.task}'; "
            "if ($t.State -ne 'Running') { Start-ScheduledTask -TaskName $t.TaskName }"
        )
        return
    if spec.kind == "command":
        argv = [sys.executable if part == "{python}" else part for part in spec.command]
        cwd = Path(spec.cwd)
        if not cwd.is_dir():
            raise FileNotFoundError("작업 폴더 없음")
    else:
        argv = [spec.path, *spec.args]
        cwd = Path(spec.path).parent
        if not Path(spec.path).is_file():
            raise FileNotFoundError("프로그램 없음")
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    common = dict(cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    try:
        # 예약 작업이 끝나도 같이 죽지 않게 작업 객체에서 떼어 낸다. 허용되지 않으면 그냥 띄운다.
        subprocess.Popen(argv, creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), **common)
    except OSError:
        subprocess.Popen(argv, creationflags=flags, **common)


def describe_start(service) -> str:
    spec = service.start
    if spec is None:
        return "켜는 방법 없음"
    if spec.kind == "task":
        return f"예약 작업 {spec.task}"
    if spec.kind == "command":
        return "명령 " + " ".join(spec.command) + f" (작업 폴더 {spec.cwd})"
    return "프로그램 " + spec.path


def record(base: Path, event: str, **details) -> None:
    try:
        with (base / LOG).open("a", encoding="utf-8") as file:
            file.write(json.dumps({"at": time.time(), "event": event, **details}, ensure_ascii=False) + "\n")
    except OSError as error:
        log.error("server-watch record failed: %s", type(error).__name__)


def load_state(base: Path) -> dict:
    try:
        return json.loads((base / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sweep(base: Path, *, registry=None, probe=observe, starter=start, logged_on=user_logged_on,
          now=None, interval=None, enqueue=reports.enqueue, wake=None) -> dict | None:
    """autostart 서버 점검 한 번. 점검 간격 전이면 None. 서버 id → 결과."""
    now = time.time() if now is None else now
    interval = sweep_seconds() if interval is None else interval
    wake = wake or metacog_session.safe_wake
    state = load_state(base)
    if now - state.get("last_sweep", 0) < interval:
        return None
    state["last_sweep"] = now
    registry = registry or load_registry()
    entries = state.setdefault("servers", {})
    results: dict[str, str] = {}
    for service in local_services(registry):
        if service.autostart not in ("boot", "logon") or service.id in HANDLED_ELSEWHERE:
            continue
        entry = entries.setdefault(service.id, {"starts": 0})
        entry.setdefault("starts", 0)  # 메타인지·관제가 blocked/starts를 지워 재시도를 풀 수 있다
        status, detail = probe(service)
        entry["status"], entry["detail"], entry["checked"] = status, detail, now
        if status == "ok":
            if entry.get("blocked") or entry.get("starts"):
                record(base, "recovered", server=service.id)
            entry.update(starts=0, blocked=False)
            entry.pop("last_error", None)
            try:
                metacog_session.resolve(base, service.id)
            except Exception as error:
                log.error("metacog resolve failed: %s", type(error).__name__)
            results[service.id] = "healthy"
            continue
        if status == "unknown":
            results[service.id] = "unknown"  # 확인할 수 없으면 건드리지 않는다
            continue
        if entry.get("blocked"):
            # 깨우기가 바빠서(다른 세션 실행 중) 미뤄졌으면 다시 시도한다. 같은 지문은 wake가 걸러 낸다.
            wake(base, blocked_incident(service, entry, detail))
            results[service.id] = "blocked"
            continue
        if service.autostart == "logon" and not logged_on():
            entry["detail"] = detail + " · 로그온 전이라 대기"
            results[service.id] = "waiting_logon"
            continue
        if entry["starts"] >= MAX_STARTS:
            entry["blocked"] = True
            record(base, "start_blocked", server=service.id, starts=entry["starts"], detail=detail)
            woke = wake(base, blocked_incident(service, entry, detail))
            record(base, "metacog_wake", server=service.id, result=woke)
            follow = ("메타인지 세션을 깨워 맡겼습니다(결과는 metacog-journal.md와 다음 보고)." if woke == "woken"
                      else "server-watch.jsonl 확인 및 수동 점검이 필요합니다.")
            enqueue(base, f"server-watch-{service.id}-{int(now)}",
                    f"[보고] 서버 {service.name}({service.id})가 꺼져 있고 자동 시작 {entry['starts']}번이 모두 "
                    f"소용없었습니다. 재시도를 멈췄습니다. 마지막 상태: {detail}. 켜는 방법: {describe_start(service)}. "
                    + follow)
            results[service.id] = "blocked"
            continue
        # 실패한 시작도 횟수에 포함한다. 실제 회복은 다음 점검의 health로만 판정한다.
        entry["starts"] += 1
        entry["last_start"] = now
        record(base, "start_requested", server=service.id, attempt=entry["starts"], detail=detail)
        try:
            starter(service)
        except Exception as error:
            entry["last_error"] = type(error).__name__
            # PowerShell 오류 끝부분만 남긴다(경로·명령줄에는 비밀값이 없다).
            why = (getattr(error, "stderr", "") or "")[-200:].strip() if isinstance(getattr(error, "stderr", ""), str) else ""
            record(base, "start_failed", server=service.id, error=type(error).__name__, stderr=why)
            results[service.id] = "start_failed"
        else:
            entry.pop("last_error", None)
            record(base, "start_launched", server=service.id)
            results[service.id] = "started"
    save(base / STATE, state)
    return results


def blocked_incident(service, entry: dict, detail: str):
    kind = error_kind(entry, detail)
    return metacog_session.Incident(
        fingerprint=metacog_session.fingerprint(service.id, kind), source="server_watch",
        title=f"서버 {service.name}({service.id}) 자동 시작 {entry.get('starts', 0)}번 실패",
        detail=f"마지막 상태: {detail}. 시작 예외: {entry.get('last_error') or '없음'}. 켜는 방법: {describe_start(service)}",
        facts={"server_id": service.id, "ports": list(service.ports), "health": service.health.model_dump(),
               "autostart": service.autostart, "starts": entry.get("starts", 0)})


def tick_uptime() -> float:
    if platform.system() != "Windows":
        return float("inf")
    kernel = ctypes.windll.kernel32
    kernel.GetTickCount64.restype = ctypes.c_ulonglong
    return kernel.GetTickCount64() / 1000


def boot_report(base: Path, *, registry=None, probe=observe, now=None, uptime=None,
                enqueue=reports.enqueue) -> str:
    """부팅(또는 장시간 중단 뒤 재개) 10분이 지나면 한 번 쓴다. 반환: written|waiting|done."""
    now = time.time() if now is None else now
    state = load_state(base)
    uptime = tick_uptime() if uptime is None else uptime
    epoch = now - uptime
    last_run = state.get("last_run")
    if last_run is None:
        # 처음 도는 때: 이미 오래 켜져 있었다면 부팅 보고를 새로 쓰지 않는다.
        state["boot_epoch"], state["boot_reported"] = epoch, now - epoch >= BOOT_REPORT_AFTER
    elif now - last_run > GAP_SECONDS:
        # 이 감시가 한참 안 돌았다 = PC가 꺼졌다 켜졌다(빠른 시작은 tick을 초기화하지 않는다).
        state["boot_epoch"], state["boot_reported"] = now, False
    elif epoch > state.get("boot_epoch", 0) + GAP_SECONDS:
        state["boot_epoch"], state["boot_reported"] = epoch, False
    state["last_run"] = now
    boot_epoch = state["boot_epoch"]
    if state.get("boot_reported"):
        save(base / STATE, state)
        return "done"
    if now - boot_epoch < BOOT_REPORT_AFTER:
        save(base / STATE, state)
        return "waiting"
    registry = registry or load_registry()
    rows = []
    for service in local_services(registry):
        if service.health.kind == "none" or service.id == "api-watchdog":
            continue
        status, detail = probe(service)
        entry = state.get("servers", {}).get(service.id, {})
        rows.append((service, status, detail, entry))
    save_report(base, rows, boot_epoch, now, enqueue)
    state["boot_reported"] = True
    save(base / STATE, state)
    return "written"


def save_report(base: Path, rows: list, boot_epoch: float, now: float, enqueue) -> None:
    label = {"ok": "살아남", "failed": "죽음", "unknown": "확인 불가"}
    alive = [s.name for s, st, _, _ in rows if st == "ok"]
    dead = [(s, d, e) for s, st, d, e in rows if st == "failed" and s.autostart in ("boot", "logon")]
    observed_dead = [s.name for s, st, _, _ in rows if st == "failed" and s.autostart not in ("boot", "logon")]
    unknown = [s.name for s, st, _, _ in rows if st == "unknown"]
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    boot = time.strftime("%H:%M", time.localtime(boot_epoch))
    summary = f"살아남 {len(alive)} / 죽음 {len(dead)}" + (f" ({', '.join(s.name for s, _, _ in dead)})" if dead else "")
    lines = [f"# 부팅 보고 ({stamp})", "", f"부팅(또는 재개) {boot}, 10분 뒤 점검.", "", f"요약: {summary}", "",
             "| 서버 | 자동 시작 | 상태 | 이유 / 자동 시작 기록 |", "|---|---|---|---|"]
    for service, status, detail, entry in rows:
        note = detail
        if entry.get("starts"):
            note += f" · 자동 시작 {entry['starts']}번 시도"
        if entry.get("blocked"):
            note += " · 재시도 중단(보고함)"
        lines.append(f"| {service.name} | {service.autostart or '-'} | {label[status]} | {note} |")
    if observed_dead:
        lines += ["", "관찰만 하는 서버(자동 시작 안 함)가 꺼져 있음: " + ", ".join(observed_dead)]
    if unknown:
        lines += ["", "확인하지 못함: " + ", ".join(unknown)]
    temp = base / "boot-report.md.tmp"
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp.replace(base / "boot-report.md")
    if dead:
        detail = "; ".join(f"{s.name}: {d}" for s, d, _ in dead)
        enqueue(base, f"boot-report-{int(boot_epoch)}",
                f"[보고] 부팅 10분 뒤 점검: 죽어 있는 서버 {len(dead)}개 — {detail}. 자세한 내용은 boot-report.md.")


def boot_summary(base: Path) -> str:
    """control_brief 한 줄. 파일이 없으면 빈 문자열."""
    path = base / "boot-report.md"
    try:
        text = path.read_text(encoding="utf-8")
        when = time.strftime("%m-%d %H:%M", time.localtime(path.stat().st_mtime))
    except OSError:
        return ""
    line = next((l for l in text.splitlines() if l.startswith("요약:")), "")
    return f"부팅 보고 ({when}): {line.removeprefix('요약:').strip()}" if line else ""


def run(base: Path) -> None:
    """api-watchdog 작업이 매분 부르는 진입점. 예외가 API 검사를 막지 않게 호출자가 감싼다."""
    results = sweep(base)
    if results:
        log.info("server sweep: %s", results)
    boot_report(base)
