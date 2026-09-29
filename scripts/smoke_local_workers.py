"""Exercise configured real workers and verify their artifact, not just stdout."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from all_tomorrow.contracts import WorkerRequest, WorkerStatus
from all_tomorrow.local_workers import ADAPTERS, build_worker_service, load_config
from all_tomorrow.adapters.workers import _resolve_cwd


async def main(args) -> int:
    config = load_config(args.config)
    root = _resolve_cwd(str(args.workspace), tuple(config["allowed_roots"]))
    service = await build_worker_service(config)
    run_dir = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    run_dir.mkdir()
    rows = []
    for worker_id in args.workers:
        cwd = run_dir / worker_id
        cwd.mkdir()
        token = f"ALL_TOMORROW_{worker_id.upper()}_{uuid4().hex}"
        if not service.has_worker(worker_id):
            rows.append({"worker_id": worker_id, "passed": False, "error": "executable unavailable"})
            continue
        request = WorkerRequest(str(uuid4()), str(uuid4()), "local-worker-smoke",
            frozenset({"coding", "repo_edit"}), {
                "cwd": str(cwd),
                "task": f"Use your file editing tool to create proof.txt in the current directory "
                        f"containing exactly {token}. Do not read or modify other files or use "
                        "external services. After writing the file, respond with its filename.",
            })
        result = await service.execute(worker_id, request)
        proof = cwd / "proof.txt"
        contents = proof.read_bytes() if (
            proof.is_file() and not proof.is_symlink() and proof.stat().st_size < 1024
        ) else b""
        correct = contents.decode("utf-8", errors="replace").strip() == token
        row = {"worker_id": worker_id, "passed": result.status == WorkerStatus.SUCCESS and correct,
               "artifact_verified": correct,
               "artifact_sha256": hashlib.sha256(contents).hexdigest() if contents else None,
               "result": asdict(result)}
        rows.append(row)
        (run_dir / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"worker_id": worker_id, "passed": row["passed"],
                          "status": result.status.value, "evidence": str(run_dir)}, ensure_ascii=False), flush=True)
    (run_dir / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/workers.local.json"))
    parser.add_argument("--workspace", type=Path, default=Path(".artifacts/local-workers"))
    parser.add_argument("--workers", nargs="+", choices=tuple(ADAPTERS), default=list(ADAPTERS))
    raise SystemExit(asyncio.run(main(parser.parse_args())))
