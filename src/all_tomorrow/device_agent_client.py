"""Device agent client — runs on a user's own machine, pulls Work from the
central server over Tailscale, executes it with a local worker CLI, and
reports the result back.

Outbound-only (S: "기기 -> 중앙" pull direction): this process only makes
outgoing HTTPS/HTTP requests to the server's tailnet address, so it needs no
inbound port and works behind NAT/firewalls without any router configuration.

State (device_id + token) is persisted to a local JSON file after the
one-time registration so subsequent runs (e.g. after a reboot, or the
Task Scheduler entry) don't need the registration code again. The raw token
is written to that file (it must be — the agent needs it to authenticate),
so the file is created with owner-only permissions where the OS supports it
and must never be committed to the repository (see .gitignore).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import stat
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from all_tomorrow.adapters.workers import _sanitize_error
from all_tomorrow.contracts import Worker, WorkerRequest, WorkerStatus
from all_tomorrow.local_workers import build_worker_service, discover_executable, load_config

logger = logging.getLogger("all_tomorrow.device_agent_client")

HEARTBEAT_INTERVAL_SECONDS = 30
CLAIM_POLL_INTERVAL_SECONDS = 5
LEASE_TTL_SECONDS = 120
LEASE_RENEW_MARGIN_SECONDS = 30
DEFAULT_STATE_FILE = "device_agent_state.json"


class DeviceAgentClientError(RuntimeError):
    pass


def _default_state_path() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "all-tomorrow" / DEFAULT_STATE_FILE
    return Path.home() / ".all-tomorrow" / DEFAULT_STATE_FILE


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # owner read/write only


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


async def _detect_capabilities(worker_config: dict[str, Any]) -> frozenset[str]:
    caps: set[str] = set()
    for worker_id in worker_config.get("workers", {}):
        if discover_executable(worker_id):
            caps.add(worker_id)
    return frozenset(caps) or frozenset({"coding"})


class DeviceAgentClient:
    def __init__(
        self, *, base_url: str, state_path: Path, worker_config_path: Path,
        device_name: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.state_path = state_path
        self.worker_config_path = worker_config_path
        self.device_name = device_name or platform.node() or "unnamed-device"
        self.device_id: str | None = None
        self.token: str | None = None
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)

    async def close(self) -> None:
        await self._http.aclose()

    def _load_state(self) -> bool:
        state = _read_state(self.state_path)
        if state and state.get("device_id") and state.get("token"):
            self.device_id = state["device_id"]
            self.token = state["token"]
            return True
        return False

    async def register(self, registration_code: str, *, capabilities: frozenset[str]) -> None:
        resp = await self._http.post(
            "/api/device/register",
            json={
                "registration_code": registration_code, "name": self.device_name,
                "capabilities": sorted(capabilities), "max_concurrent": 1,
            },
        )
        if resp.status_code != 200:
            raise DeviceAgentClientError(f"registration failed: HTTP {resp.status_code} {resp.text[:300]}")
        payload = resp.json()
        self.device_id = payload["device_id"]
        self.token = payload["token"]
        _write_state(self.state_path, {"device_id": self.device_id, "token": self.token,
                                        "base_url": self.base_url, "name": self.device_name})
        logger.info("device registered: %s", self.device_id)

    async def ensure_registered(self, registration_code: str | None, capabilities: frozenset[str]) -> None:
        if self._load_state():
            return
        if not registration_code:
            raise DeviceAgentClientError(
                "no saved device credentials and no --registration-code given; "
                "issue one from the web '기기' page first"
            )
        await self.register(registration_code, capabilities=capabilities)

    async def heartbeat(self) -> str:
        resp = await self._http.post(
            "/api/device/heartbeat", json={"device_id": self.device_id, "token": self.token},
        )
        if resp.status_code != 200:
            raise DeviceAgentClientError(f"heartbeat failed: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json()["status"]

    async def claim(self) -> dict[str, Any] | None:
        resp = await self._http.post(
            "/api/device/claim", json={"device_id": self.device_id, "token": self.token},
        )
        if resp.status_code != 200:
            raise DeviceAgentClientError(f"claim failed: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json().get("lease")

    async def renew(self, lease_id: str) -> None:
        resp = await self._http.post(
            "/api/device/lease/renew",
            json={"device_id": self.device_id, "token": self.token, "lease_id": lease_id},
        )
        if resp.status_code != 200:
            logger.warning("lease renew failed: HTTP %s %s", resp.status_code, resp.text[:200])

    async def complete(
        self, lease_id: str, *, succeeded: bool, output_text: str | None,
        error: str | None, duration_ms: int,
    ) -> None:
        resp = await self._http.post(
            "/api/device/complete",
            json={
                "device_id": self.device_id, "token": self.token, "lease_id": lease_id,
                "succeeded": succeeded, "output_text": output_text, "error": error,
                "duration_ms": duration_ms,
            },
        )
        if resp.status_code != 200:
            logger.error("complete report failed: HTTP %s %s", resp.status_code, resp.text[:300])

    async def _run_lease(self, lease: dict[str, Any]) -> None:
        lease_id = lease["lease_id"]
        title = lease.get("title") or ""
        start = time.perf_counter()
        stop_renew = asyncio.Event()

        async def renewer() -> None:
            while not stop_renew.is_set():
                try:
                    await asyncio.wait_for(stop_renew.wait(), timeout=LEASE_TTL_SECONDS - LEASE_RENEW_MARGIN_SECONDS)
                except asyncio.TimeoutError:
                    await self.renew(lease_id)

        renew_task = asyncio.create_task(renewer())
        try:
            config = load_config(self.worker_config_path)
            service = await build_worker_service(config)
            worker_id = next(iter(config["workers"]), None)
            if worker_id is None or not service.has_worker(worker_id):
                raise DeviceAgentClientError("no usable local worker is configured/installed")
            request = WorkerRequest(
                request_id=str(uuid4()), trace_id=str(uuid4()), project_id=None,
                capabilities=service.get_adapter(worker_id).capabilities,
                payload={"cwd": str(Path.cwd()), "task": title},
            )
            result = await service.execute(worker_id, request)
            duration_ms = int((time.perf_counter() - start) * 1000)
            if result.status is WorkerStatus.SUCCESS:
                output = None
                if result.payload:
                    output = result.payload.get("output") or json.dumps(result.payload, ensure_ascii=False)
                await self.complete(lease_id, succeeded=True, output_text=output,
                                    error=None, duration_ms=duration_ms)
            else:
                await self.complete(lease_id, succeeded=False, output_text=None,
                                    error=result.error or result.status.value, duration_ms=duration_ms)
        except Exception as error:  # noqa: BLE001 -- must always report, never crash the loop silently
            duration_ms = int((time.perf_counter() - start) * 1000)
            await self.complete(lease_id, succeeded=False, output_text=None,
                                error=_sanitize_error(error), duration_ms=duration_ms)
            logger.exception("lease %s failed", lease_id)
        finally:
            stop_renew.set()
            renew_task.cancel()
            try:
                await renew_task
            except asyncio.CancelledError:
                pass

    async def run_forever(self, *, stop_event: asyncio.Event | None = None) -> None:
        stop_event = stop_event or asyncio.Event()
        last_heartbeat = 0.0
        while not stop_event.is_set():
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                try:
                    status = await self.heartbeat()
                    logger.info("heartbeat ok, status=%s", status)
                except DeviceAgentClientError as error:
                    logger.warning("heartbeat failed: %s", error)
                last_heartbeat = now
            try:
                lease = await self.claim()
            except DeviceAgentClientError as error:
                logger.warning("claim failed: %s", error)
                lease = None
            if lease is not None:
                await self._run_lease(lease)
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=CLAIM_POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", required=True,
                        help="Central server tailnet address, e.g. http://100.97.113.3:8080")
    parser.add_argument("--registration-code", default=None,
                        help="One-time code from the web '기기' page (only needed on first run)")
    parser.add_argument("--name", default=None, help="Device display name (defaults to hostname)")
    parser.add_argument("--worker-config", type=Path, default=Path("config/workers.local.json"))
    parser.add_argument("--state-file", type=Path, default=None)
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    state_path = args.state_file or _default_state_path()
    client = DeviceAgentClient(
        base_url=args.server_url, state_path=state_path,
        worker_config_path=args.worker_config, device_name=args.name,
    )
    try:
        config = load_config(args.worker_config)
        capabilities = await _detect_capabilities(config)
        await client.ensure_registered(args.registration_code, capabilities)
        logger.info("device_id=%s starting main loop against %s", client.device_id, args.server_url)
        await client.run_forever()
        return 0
    finally:
        await client.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = _build_arg_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_main_async(args)))
    except DeviceAgentClientError as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False))
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
