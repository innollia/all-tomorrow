"""Idea factory CLI.

  python -m all_tomorrow.idea_factory gateway --litellm <path to litellm executable>
  python -m all_tomorrow.idea_factory run "주제"
  python -m all_tomorrow.idea_factory resume        # recover workflows after a crash
  python -m all_tomorrow.idea_factory status
  python -m all_tomorrow.idea_factory evaluate [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

from all_tomorrow.idea_factory.config import REPO_ROOT, gateway_config, load_key_pool, load_roster

STORE_PATH = Path(os.environ.get("IDEA_FACTORY_STORE", REPO_ROOT / ".artifacts" / "idea-factory.sqlite"))
GATEWAY_CONFIG_PATH = REPO_ROOT / ".artifacts" / "idea-factory-gateway.yaml"


def _store():
    from all_tomorrow.idea_factory.store import Store
    return Store(STORE_PATH)


def _wait(store, topic_ids: list[str]) -> None:
    seen = 0
    while True:
        events = list(reversed(store.events(limit=500)))
        for event in events[seen:]:
            if event["topic_id"] in topic_ids or event["topic_id"] is None:
                print(f"{event['ts'][11:19]} [{event['kind']}] {event['text']}", flush=True)
        seen = len(events)
        if all((store.topic(t) or {}).get("status") != "RUNNING" for t in topic_ids):
            return
        time.sleep(3)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="idea_factory")
    sub = parser.add_subparsers(dest="command", required=True)
    gw = sub.add_parser("gateway")
    gw.add_argument("--litellm", default=os.environ.get("LITELLM_BIN"))
    gw.add_argument("--port", default="4000")
    sub.add_parser("gateway-config")
    run = sub.add_parser("run")
    run.add_argument("topic")
    sub.add_parser("resume")
    sub.add_parser("status")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    # The gateway master key lives in the key-pool file next to the provider keys.
    os.environ.setdefault("IDEA_FACTORY_GATEWAY_KEY", load_key_pool().get("IDEA_FACTORY_GATEWAY_KEY", ""))

    if args.command in ("gateway", "gateway-config"):
        pool = load_key_pool()
        config = gateway_config(load_roster(), list(pool))
        GATEWAY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        GATEWAY_CONFIG_PATH.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"{len(config['model_list'])} deployments → {GATEWAY_CONFIG_PATH}")
        if args.command == "gateway-config":
            return 0
        if not args.litellm:
            print("--litellm or LITELLM_BIN is required", file=sys.stderr)
            return 2
        if not os.environ.get("IDEA_FACTORY_GATEWAY_KEY"):
            print("IDEA_FACTORY_GATEWAY_KEY is required", file=sys.stderr)
            return 2
        env = {**os.environ, **pool, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        litellm_bin = str(Path(args.litellm).resolve()) if Path(args.litellm).exists() else args.litellm
        return subprocess.call([litellm_bin, "--config", str(GATEWAY_CONFIG_PATH), "--host", "127.0.0.1",
                                "--port", args.port], env=env)

    store = _store()
    if args.command == "status":
        print(json.dumps({"loop": store.loop_state(), "topics": store.topics(5),
                          "pending_proposals": len(store.proposals("PENDING"))}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "evaluate":
        from all_tomorrow.idea_factory.evaluation import apply_policy, evaluate
        roster = load_roster()
        result = apply_policy(store, roster, actor="cli") if args.apply else evaluate(store, roster)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    from dbos import DBOS
    from all_tomorrow.idea_factory import pipeline
    pipeline.launch(store)
    try:
        if args.command == "run":
            topic_id = pipeline.start_topic(args.topic, actor="cli")
            print(f"topic {topic_id}", flush=True)
            _wait(store, [topic_id])
        else:  # resume: DBOS.launch() already recovered pending workflows
            running = [t["id"] for t in store.topics(1000) if t["status"] == "RUNNING"]
            print(f"resuming {running}", flush=True)
            _wait(store, running)
        for proposal in store.proposals():
            print(f"[기획안 {proposal['status']}] {proposal['body']['title']}")
    finally:
        DBOS.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
