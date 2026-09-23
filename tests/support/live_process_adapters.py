"""Candidate process controls. Scenario code uses only this common interface."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psycopg


class ProcessAdapter:
    def __init__(self, payload, directory):
        self.payload = payload
        self.directory = Path(directory)
        self.span_file = self.directory / "spans.jsonl"
        self.process = None
        self.processes = []
        self.environment = {}
        self.workflow_id = f"{payload['identity']['work_id']}:{payload['identity']['run_id']}"
        self.fixture_url = os.environ["AT_TEST_FIXTURE_URL"]

    def launch(self, command, phase="normal"):
        env = os.environ.copy()
        env.update(self.environment)
        env.update(AT_TEST_COMMON_PAYLOAD=json.dumps(self.payload), AT_TEST_COMMON_PHASE=phase,
                   AT_TEST_OTEL_SPANS=str(self.span_file))
        self.result_file = self.directory / f"result-{len(self.processes)}.json"
        env["AT_TEST_COMMON_RESULT_PATH"] = str(self.result_file)
        log = self.directory / f"worker-{len(self.processes)}.log"
        with log.open("wb") as stream:
            self.process = subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT)
        self.processes.append((self.process, log))
        return self.process

    def kill(self):
        self.process.kill()
        self.process.wait(timeout=10)

    def close(self):
        for process, _ in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def wait_span(self, name, timeout=30):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if self.span_file.exists():
                for line in self.span_file.read_text().splitlines():
                    span = json.loads(line)
                    if span["name"] == name or span["name"].endswith(name):
                        return span
            assert self.process.poll() is None, self.processes[-1][1].read_text()
            time.sleep(.1)
        raise AssertionError(f"Missing span {name}")


class DBOSProcessAdapter(ProcessAdapter):
    candidate = "dbos"
    def start(self, phase="start"):
        return self.launch([sys.executable, "-m", "tests.support.dbos_common_worker"], phase)

    def finish(self):
        process = self.start("recover")
        assert process.wait(timeout=60) == 0, self.processes[-1][1].read_text()
        return json.loads(self.result_file.read_text(encoding="utf-8"))

    def cancel(self):
        process = self.start("cancel")
        assert process.wait(timeout=30) == 0, self.processes[-1][1].read_text()

    def signal(self):
        process = self.start("signal")
        assert process.wait(timeout=30) == 0, self.processes[-1][1].read_text()

    def state(self):
        with psycopg.connect(os.environ["AT_TEST_POSTGRES_URL"]) as conn:
            return conn.execute("SELECT status FROM dbos.workflow_status WHERE workflow_uuid=%s", (self.workflow_id,)).fetchone()[0]


class RestateProcessAdapter(ProcessAdapter):
    candidate = "restate"
    def start(self, phase="start"):
        process = self.launch([sys.executable, "-m", "uvicorn", "tests.support.restate_common_service:app", "--host", "127.0.0.1", "--port", "9093"], phase)
        self.admin = os.environ["AT_TEST_RESTATE_ADMIN"].rstrip("/")
        self.ingress = os.environ["AT_TEST_RESTATE_INGRESS"].rstrip("/")
        with httpx.Client(timeout=5) as client:
            for _ in range(150):
                assert process.poll() is None, self.processes[-1][1].read_text()
                try:
                    if client.get("http://127.0.0.1:9093/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError("Worker did not start")
            if not hasattr(self, "invocation_id"):
                response = client.post(f"{self.admin}/deployments", json={"uri":"http://127.0.0.1:9093","use_http_11":True})
                assert response.status_code in (200,201), response.text
                response = client.post(f"{self.ingress}/restate/send/AllTomorrowCommonD01/{self.workflow_id}/run", json=self.payload)
                assert response.status_code in (200,202), response.text
                self.invocation_id = response.json()["invocationId"]
        return process

    def finish(self):
        self.start("recover")
        response = httpx.get(f"{self.ingress}/restate/attach/{self.invocation_id}", timeout=60)
        assert response.status_code == 200, response.text
        return response.json()

    def cancel(self):
        response = httpx.patch(f"{self.admin}/invocations/{self.invocation_id}/cancel", timeout=10)
        assert response.status_code in (200,202), response.text

    def signal(self):
        if self.process.poll() is not None:
            self.start("recover")
        response = httpx.post(f"{self.ingress}/AllTomorrowCommonD01/{self.workflow_id}/approve", json={"approved": True}, timeout=20)
        assert response.status_code == 200, response.text

    def state(self):
        response = httpx.get(f"{self.ingress}/restate/output/{self.invocation_id}", timeout=10)
        if response.status_code == 409 and response.json().get("message") == "cancelled":
            return "CANCELLED"
        if response.status_code == 200:
            return "SUCCESS"
        return "PENDING"


CANDIDATES = (DBOSProcessAdapter, RestateProcessAdapter)
