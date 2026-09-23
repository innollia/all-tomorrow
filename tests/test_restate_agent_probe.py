"""Live RestateAgent integration with the deterministic PydanticAI agent."""

import os
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest


def test_restate_wrapped_agent_returns_structured_decision() -> None:
    admin = os.environ.get("AT_TEST_RESTATE_ADMIN")
    ingress = os.environ.get("AT_TEST_RESTATE_INGRESS")
    if not admin or not ingress:
        pytest.skip("Set AT_TEST_RESTATE_ADMIN and AT_TEST_RESTATE_INGRESS")

    worker = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.support.restate_agent_service:app", "--host", "127.0.0.1", "--port", "9084"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(timeout=10) as client:
            for _ in range(100):
                try:
                    if client.get("http://127.0.0.1:9084/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("RestateAgent service did not start")

            registration = client.post(
                f"{admin.rstrip('/')}/deployments",
                json={"uri": "http://127.0.0.1:9084", "use_http_11": True},
            )
            assert registration.status_code in (200, 201), registration.text
            workflow_id = f"agent-{uuid4()}"
            response = client.post(
                f"{ingress.rstrip('/')}/AllTomorrowAgentProbe/{workflow_id}/run",
                json="Check item-01 and decide",
                timeout=30,
            )
        assert response.status_code == 200, response.text
        decision = response.json()
        assert decision["stock_confirmed"] == 42
        assert decision["should_commit_mutation"] is True
        assert decision["planned_mutation_value"] == "committed-by-pydanticai"
    finally:
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=2)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
