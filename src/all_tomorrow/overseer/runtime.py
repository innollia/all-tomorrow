"""DP7 예약 작업 진입점. 웹·작업 계층·메타인지를 서로 다른 프로세스로 띄운다."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

from all_tomorrow.async_runtime import run_async

from all_tomorrow.overseer.environment import REPO, load_key_pool, project_registry
from all_tomorrow.overseer.store import default_dir, SessionStore

log = logging.getLogger("all_tomorrow.overseer")


@contextmanager
def singleton(path: Path, wait: float = 0.0):
    # OS 파일 잠금은 프로세스가 죽으면 해제된다. 새 lease/queue를 만들지 않는다.
    # wait > 0: 재시작 직후 이전 프로세스가 아직 잠금을 쥐고 있을 수 있어 그만큼 기다린다.
    deadline = time.monotonic() + wait
    with path.open("a+b") as file:
        while True:
            file.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        yield


def wait_port_free(port: int, timeout: float, host: str = "127.0.0.1") -> bool:
    """True once nothing accepts on host:port (the old API has let go), False on timeout."""
    import socket
    deadline = time.monotonic() + timeout
    while True:
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex((host, port)) != 0:
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)


async def with_store(callback):
    from all_tomorrow.storage.semantic_store import PostgresGoalWorkRunStore
    from all_tomorrow.storage.postgres import PostgresStore
    url = os.environ.get("ALL_TOMORROW_DATABASE_URL")
    if not url:
        raise ValueError("ALL_TOMORROW_DATABASE_URL을 설정해야 합니다")
    store = PostgresGoalWorkRunStore(url)
    await store.open()
    try:
        await PostgresStore(url, pool=store.pool).migrate(REPO / "migrations")
        return await callback(store)
    finally:
        await store.close()


async def observe_once(store, sessions, base, *, force=False, usage=None):
    from all_tomorrow.overseer import brief
    from all_tomorrow.overseer.loop import observe
    from all_tomorrow.overseer.redact import Redactor, default_secret_files
    redact = Redactor.from_files(default_secret_files(Path.home()))
    return await observe(store, sessions, base, registry=project_registry(), redact=redact,
                         projects=brief.load_projects(), notion=brief.load_notion, force=force, usage=usage)


async def serve(component: str, base: Path):
    from all_tomorrow import usage
    from all_tomorrow.overseer import reports
    from all_tomorrow.overseer.loop import execute_pending
    from all_tomorrow.overseer.redact import Redactor, default_secret_files
    from all_tomorrow.overseer.schedule import idle_seconds, settings, wake_gate
    from all_tomorrow.console.usage import UsageStore
    next_wake = 0.0
    gate_reason = None
    sessions = SessionStore(base / "overseer.sqlite") if component == "overseer" else None
    try:
        while True:
            try:
                load_key_pool()
                redact = Redactor.from_files(default_secret_files(Path.home()))
                await asyncio.to_thread(reports.flush, base)
                idle = idle_seconds(base)
                # 이 파일이 있으면 메타인지 깨어남과 그 Work 실행을 멈춘다. 사용량 수집·보고는 계속한다.
                paused = (base / "metacog.paused").exists()
                if component == "executor":
                    if not paused and idle is not None and idle >= 300:
                        await with_store(lambda store: execute_pending(store, base, registry=project_registry(),
                                                                        redact=redact, limit=1))
                else:
                    snapshot = await asyncio.to_thread(usage.collect)
                    UsageStore(base / "subscription-usage.json").store(snapshot)
                    token = usage.collector_token(usage.TOKEN_ENV)
                    if token:
                        try:
                            await asyncio.to_thread(usage.push, snapshot,
                                os.environ.get("ALL_TOMORROW_URL", "http://127.0.0.1:5476"), token)
                        except Exception as error:
                            log.warning("사용량 push 실패: %s", type(error).__name__)
                    # 로그인 갱신이 불가능하면 파일 보고와 Discord로 사용자에게 알린다.
                    for provider in snapshot["providers"]:
                        if provider["status"] in {"needs_login", "not_logged_in"}:
                            reports.enqueue(base, "login-" + provider["id"] + "-" + time.strftime("%Y-%m-%d"),
                                            f"[질문] {provider['name']} 사용량 조회에 다시 로그인이 필요합니다.")
                    config = settings()
                    ready, reason = wake_gate(idle, config)
                    if paused:
                        ready, reason = False, "일시정지 파일 있음"
                    # 깨우지 않는 이유도 바뀔 때마다 남긴다. 예전에는 이유 없이 멈춰 원인을 알 수 없었다.
                    if reason != gate_reason:
                        log.info("메타인지 확인 조건: %s", reason)
                        gate_reason = reason
                    if ready and time.monotonic() >= next_wake:
                        # 확인 자체는 코드만 쓴다. 변화·최소 간격·하루 상한은 metacog.wake가 판단한다.
                        await with_store(lambda store: observe_once(store, sessions, base, usage=snapshot))
                        next_wake = time.monotonic() + config["check_interval"]
            except Exception as error:
                log.warning("%s 실행 실패: %s", component, type(error).__name__)
            await asyncio.sleep(60)
    finally:
        if sessions:
            sessions.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=("api", "executor", "overseer", "collect", "activity", "api-watchdog"))
    parser.add_argument("--api-task", default="AllTomorrow-DP7-api")
    args = parser.parse_args(argv)
    load_key_pool()
    os.chdir(REPO)
    base = Path(os.environ.get("ALL_TOMORROW_OVERSEER_DIR", default_dir()))
    base.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=base / (args.component + ".log"), encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    # API는 /End 직후 /Run(또는 watchdog 재시작)으로 바로 다시 뜬다. 이전 프로세스가 잠금과 포트를
    # 놓을 때까지 기다리지 않으면 잠금 OSError로 rc=1 종료한다.
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(singleton(base / (args.component + ".lock"), wait=30 if args.component == "api" else 0))
        except OSError:
            log.error("runtime lock busy component=%s pid=%s", args.component, os.getpid())
            raise
        log.info("runtime started component=%s pid=%s parent_pid=%s", args.component, os.getpid(), os.getppid())
        if args.component == "api":
            if not os.environ.get("ALL_TOMORROW_DATABASE_URL"):
                raise ValueError("DP7 백엔드는 PostgreSQL 설정이 필요합니다")
            os.environ.setdefault("ALL_TOMORROW_PORT", "5476")
            if not wait_port_free(int(os.environ["ALL_TOMORROW_PORT"]), 30):
                log.error("api port %s still in use after 30s", os.environ["ALL_TOMORROW_PORT"])
                raise SystemExit(1)
            os.environ.setdefault("ALL_TOMORROW_MIGRATIONS", str(REPO / "migrations"))
            from all_tomorrow.web import run
            run()
        elif args.component == "api-watchdog":
            from all_tomorrow.overseer.api_watchdog import check_once
            check_once(base, task=args.api_task)
        elif args.component == "activity":
            from all_tomorrow.overseer.schedule import local_idle_seconds
            from all_tomorrow.overseer.workspace import save
            while True:
                save(base / "pc-activity.json", {"at": time.time(), "idle_seconds": local_idle_seconds()})
                time.sleep(30)
        elif args.component == "collect":
            from all_tomorrow.overseer.__main__ import main as collect_main
            collect_main(["--dir", str(base), "run", "--no-metacog"])
        else:
            run_async(serve(args.component, base))


if __name__ == "__main__":
    main()
