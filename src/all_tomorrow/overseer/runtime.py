"""DP7 예약 작업 진입점. 웹·작업 계층·메타인지를 서로 다른 프로세스로 띄운다."""
from __future__ import annotations

import argparse
import asyncio
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
def singleton(path: Path):
    # OS 파일 잠금은 프로세스가 죽으면 해제된다. 새 lease/queue를 만들지 않는다.
    with path.open("a+b") as file:
        file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


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
                         projects=brief.load_projects(), notion=brief.load_notion(), force=force, usage=usage)


async def serve(component: str, base: Path):
    from all_tomorrow import usage
    from all_tomorrow.overseer import reports
    from all_tomorrow.overseer.loop import execute_pending
    from all_tomorrow.overseer.redact import Redactor, default_secret_files
    from all_tomorrow.overseer.schedule import idle_seconds, wake_delay
    from all_tomorrow.console.usage import UsageStore
    next_wake = 0.0
    sessions = SessionStore(base / "overseer.sqlite") if component == "overseer" else None
    try:
        while True:
            try:
                load_key_pool()
                redact = Redactor.from_files(default_secret_files(Path.home()))
                await asyncio.to_thread(reports.flush, base)
                idle = idle_seconds(base)
                if component == "executor":
                    if idle is not None and idle >= 300:
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
                    delay, reason = wake_delay(snapshot, idle)
                    if delay is not None and time.monotonic() >= next_wake:
                        log.info("메타인지: %s", reason)
                        await with_store(lambda store: observe_once(store, sessions, base, usage=snapshot))
                        next_wake = time.monotonic() + delay
            except Exception as error:
                log.warning("%s 실행 실패: %s", component, type(error).__name__)
            await asyncio.sleep(60)
    finally:
        if sessions:
            sessions.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=("api", "executor", "overseer", "collect", "activity"))
    args = parser.parse_args(argv)
    load_key_pool()
    os.chdir(REPO)
    base = Path(os.environ.get("ALL_TOMORROW_OVERSEER_DIR", default_dir()))
    base.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=base / (args.component + ".log"), encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    with singleton(base / (args.component + ".lock")):
        log.info("runtime started component=%s pid=%s parent_pid=%s", args.component, os.getpid(), os.getppid())
        if args.component == "api":
            if not os.environ.get("ALL_TOMORROW_DATABASE_URL"):
                raise ValueError("DP7 백엔드는 PostgreSQL 설정이 필요합니다")
            os.environ.setdefault("ALL_TOMORROW_PORT", "5476")
            os.environ.setdefault("ALL_TOMORROW_MIGRATIONS", str(REPO / "migrations"))
            from all_tomorrow.web import run
            run()
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
