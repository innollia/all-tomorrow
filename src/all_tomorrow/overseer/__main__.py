"""python -m all_tomorrow.overseer collect [--source NAME ...] | stats"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from all_tomorrow.overseer.redact import Redactor, default_secret_files
from all_tomorrow.overseer.sources import Roots
from all_tomorrow.overseer.store import SessionStore, default_dir

log = logging.getLogger("all_tomorrow.overseer")


def collect(store: SessionStore, roots: Roots, redact, sources: list[str] | None = None) -> dict[str, dict]:
    report: dict[str, dict] = {}
    for name, listing in roots.listings().items():
        if sources and name not in sources:
            continue
        known = store.fingerprints(name)
        counts = {"found": 0, "new": 0, "changed": 0, "same": 0, "failed": 0}
        started = time.monotonic()
        for item in listing():
            counts["found"] += 1
            previous = known.get(item.session_id)
            if previous == item.fingerprint:
                counts["same"] += 1
                continue
            try:
                store.put(item.load(), item.fingerprint, redact)
            except Exception:  # one unreadable session must not stop the rest
                counts["failed"] += 1
                log.exception("failed to collect %s %s", name, item.session_id)
                continue
            counts["new" if previous is None else "changed"] += 1
            if (counts["new"] + counts["changed"]) % 50 == 0:
                store.commit()
        store.commit()
        counts["seconds"] = round(time.monotonic() - started, 1)
        report[name] = counts
        log.info("%s %s", name, counts)
    return report


GATEWAY_LITELLM_CANDIDATES = (
    # Per-PC venv (not synced): .artifacts is inside the Syncthing-shared C:\projects, and a venv
    # copied from the other PC points at that PC's Python (DP7, 2026-10-20).
    Path(os.environ.get("LOCALAPPDATA", "")) / "all-tomorrow" / "gateway-venv" / "Scripts" / "litellm.exe",
    Path(__file__).resolve().parents[3] / ".artifacts" / "gateway-venv" / "Scripts" / "litellm.exe",
)
DISTILL_BUDGET_SECONDS = 35 * 60   # leave room for the metacognition wake inside the 55-minute task limit
# The hourly task wakes metacognition at most this often: each wake spends Codex subscription usage (user, 2026-10-20).


def _ensure_gateway() -> bool:
    """Start the local model gateway if it is down (it does not start on boot)."""
    import subprocess
    if _gateway_alive():
        return True
    litellm = next((p for p in GATEWAY_LITELLM_CANDIDATES if p.is_file()), None)
    if litellm is None:
        log.warning("no gateway venv found; distillation skipped")
        return False
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) \
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    logfile = open(default_dir() / "gateway.log", "ab")
    subprocess.Popen([sys.executable.replace("pythonw.exe", "python.exe"), "-m", "all_tomorrow.idea_factory",
                      "gateway", "--litellm", str(litellm)], cwd=str(Path(__file__).resolve().parents[3]),
                     stdout=logfile, stderr=logfile, stdin=subprocess.DEVNULL, creationflags=flags)
    for _ in range(36):
        time.sleep(5)
        if _gateway_alive():
            log.info("started model gateway (%s)", litellm)
            return True
    log.warning("model gateway did not come up; distillation skipped")
    return False


def _metacog_due(store: SessionStore) -> bool:
    from datetime import datetime, timezone
    from all_tomorrow.overseer import metacog
    from all_tomorrow.overseer.schedule import idle_seconds, wake_delay
    from all_tomorrow.usage import collect
    delay, reason = wake_delay(collect(), idle_seconds(default_dir()))
    if delay is None:
        log.info("metacog deferred: %s", reason)
        return False
    last = metacog.last_wake(store.con)
    if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < delay:
        return False
    return True


def _gateway_alive() -> bool:
    import httpx
    from all_tomorrow.idea_factory.llm import gateway_url
    try:
        return httpx.get(f"{gateway_url()}/health/liveliness", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


def _load_gateway_key() -> None:
    """The gateway master key lives in the key pool, like for the idea factory."""
    if os.environ.get("IDEA_FACTORY_GATEWAY_KEY"):
        return
    pool = Path.home() / ".all-tomorrow" / "key-pool.env"
    for line in pool.read_text(encoding="utf-8").splitlines():
        if line.startswith("IDEA_FACTORY_GATEWAY_KEY="):
            os.environ["IDEA_FACTORY_GATEWAY_KEY"] = line.split("=", 1)[1].strip().strip("'\"")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="all_tomorrow.overseer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--source", action="append", choices=list(Roots.default().listings()))
    sub.add_parser("stats")
    sub.add_parser("sync-health", help="Syncthing 점검 및 제한된 자동 복구")
    d = sub.add_parser("distill")
    d.add_argument("--pilot", type=int, default=0, help="sessions per source for a sample run")
    d.add_argument("--session", action="append", default=[], help="source:session_id")
    d.add_argument("--pending", type=int, default=0, help="distill up to N new/changed sessions")
    r = sub.add_parser("run", help="scheduled task: collect, distill (time budget), publish for the other PC, "
                                   "one metacognition wake")
    r.add_argument("--no-metacog", action="store_true", help="this PC only collects; another PC runs the wake")
    r.add_argument("--collect-only", action="store_true",
                   help="collect and publish for the other PC only: no model calls at all (aaaa, 2026-10-20)")
    m = sub.add_parser("metacog", help="one metacognition wake over what changed since the last one")
    m.add_argument("--force", action="store_true", help="wake even if nothing changed")
    sub.add_parser("cards")
    sub.add_parser("brief", help="write brief.md: projects, activity, oracle stats, Notion profile")
    sub.add_parser("control-brief", help="write control-brief.md: direction, Notion, Discord, metacognition, activity")
    parser.add_argument("--dir", type=Path, default=None)
    args = parser.parse_args(argv)

    base = args.dir or default_dir()
    base.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(base / "overseer.log", encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)

    store = SessionStore(base / "overseer.sqlite")
    try:
        if args.cmd in ("run", "sync-health"):
            import json
            from all_tomorrow.overseer import sync_health
            result = sync_health.run(base, store, collect_only=getattr(args, "collect_only", False))
            if args.cmd == "sync-health":
                print(json.dumps(result, ensure_ascii=False))
                return 0
        if args.cmd in ("collect", "run"):
            redact = Redactor.from_files(default_secret_files(Path.home()))
            log.info("redactor loaded %d secret values", redact.value_count)
            collect(store, Roots.default(), redact, getattr(args, "source", None))
        scheduled = args.cmd == "run"
        no_metacog = getattr(args, "no_metacog", False)
        if scheduled and getattr(args, "collect_only", False):
            log.info("published %s for the other PC", store.publish(base))
            return 0
        if scheduled:
            args.cmd, args.session, args.pilot, args.pending = "distill", [], 0, 20
        if args.cmd == "distill":
            from all_tomorrow.overseer import distill as dist
            redact = Redactor.from_files(default_secret_files(Path.home()))
            _load_gateway_key()
            dist.ensure_schema(store.con)
            targets = [tuple(s.split(":", 1)) for s in args.session]
            if args.pilot:
                targets += dist.pilot_sessions(store.con, args.pilot)
            if args.pending:
                if _ensure_gateway():
                    targets += dist.pending_sessions(store.con, args.pending)
            started = time.monotonic()
            for source, session_id in targets:
                if scheduled and time.monotonic() - started > DISTILL_BUDGET_SECONDS:
                    log.info("distill time budget used; the rest stays pending")
                    break
                try:
                    made = dist.distill_session(store.con, source, session_id, redact=redact, secrets=redact.values)
                except Exception:  # gateway down / quota: leave it pending for the next run
                    log.exception("distill failed %s/%s", source, session_id)
                    continue
                log.info("distilled %s/%s -> %d cards", source, session_id, made)
            if not scheduled:
                return 0
            log.info("published %s for the other PC", store.publish(base))
            _refresh_control_brief(store, base)
            if no_metacog or not _metacog_due(store):
                return 0
            args.cmd, args.force = "metacog", False
        if args.cmd == "metacog":
            from all_tomorrow.overseer import brief, metacog
            redact = Redactor.from_files(default_secret_files(Path.home()))
            from all_tomorrow.overseer.environment import load_key_pool
            load_key_pool()
            if os.environ.get("ALL_TOMORROW_DATABASE_URL"):
                from all_tomorrow.async_runtime import run_async
                from all_tomorrow.overseer.runtime import with_store, observe_once
                result = run_async(with_store(lambda central: observe_once(central, store, base, force=args.force)))
            else:
                result = metacog.wake(store.con, base, redact=redact, projects=brief.load_projects(),
                                      notion=brief.load_notion(), force=args.force)
                log.warning("PostgreSQL 미설정: 관찰만 했으며 Work 실행 고리는 켜지지 않았습니다")
            log.info("metacog wake %s %s: %d observations, %d actions", result["status"], result["reason"],
                     len(result["observations"]), len(result["actions"]))
            return 0
        if args.cmd == "control-brief":
            from all_tomorrow.overseer.control_brief import refresh
            print(refresh(store.con, base))
            return 0
        if args.cmd == "brief":
            from all_tomorrow.overseer import brief
            text = brief.render(store.con, brief.load_projects(), brief.load_notion())
            (base / "brief.md").write_text(text, encoding="utf-8")
            print(base / "brief.md")
            return 0
        if args.cmd == "cards":
            from all_tomorrow.overseer import distill as dist
            dist.ensure_schema(store.con)
            for row in store.con.execute(
                    "select card_id, status, agent, project, outcome, problem, solution from cards "
                    "order by project, created_at"):
                print(" | ".join(str(x) for x in row))
            return 0
        for source, n, subagents, users, errors, chars in store.stats():
            print(f"{source:12} sessions={n} subagent={subagents} user_msgs={users} "
                  f"errors={errors} chars={chars}")
    finally:
        store.close()
    return 0


def _refresh_control_brief(store, base):
    from all_tomorrow.overseer.control_brief import refresh
    try:
        log.info("control briefing updated: %s", refresh(store.con, base))
    except Exception as error:
        log.warning("control briefing failed (previous file kept): %s", type(error).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
