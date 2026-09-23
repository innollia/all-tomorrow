"""Old DBOS application binary for an in-flight upgrade probe."""

import os
import sys
import time

import psycopg
from dbos import DBOS, SetWorkflowID

from all_tomorrow.harness.agent import create_deterministic_agent
from otel_file_exporter import tracer_for


WORKFLOW_ID = os.environ["AT_TEST_WORKFLOW_ID"]
TRACER = tracer_for(os.environ["AT_TEST_OTEL_SPANS"])


@DBOS.step(name="upgrade_model_step")
def model() -> dict:
    decision = create_deterministic_agent().run_sync("Check stock before approval").output
    with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
        conn.execute(
            """INSERT INTO upgrade_probe (workflow_id, model_calls, finalized)
               VALUES (%s, 1, FALSE)
               ON CONFLICT (workflow_id) DO UPDATE SET model_calls = upgrade_probe.model_calls + 1""",
            (WORKFLOW_ID,),
        )
        conn.commit()
    return {"stock": decision.stock_confirmed}


@DBOS.workflow(name="upgrade_workflow")
def workflow(correlation_id: str) -> dict:
    decision = model()
    DBOS.set_event("waiting", True)
    with TRACER.start_as_current_span("v1_wait_started") as span:
        span.set_attribute("all_tomorrow.correlation_id", correlation_id)
    approval = DBOS.recv(topic="approval", timeout_seconds=45)
    return {"stock": decision["stock"], "approved": approval["approved"], "schema": 1}


def main() -> int:
    DBOS(config={"name": "all-tomorrow-upgrade-probe", "system_database_url": os.environ["AT_TEST_POSTGRES_URL"], "application_version": "compat-v1"})
    DBOS.launch()
    with SetWorkflowID(WORKFLOW_ID):
        DBOS.start_workflow(workflow, os.environ["AT_TEST_ORIGINAL_CORR"])
    for _ in range(100):
        if DBOS.get_event(WORKFLOW_ID, "waiting", timeout_seconds=0.1):
            print(f"v1_waiting_pid={os.getpid()}", flush=True)
            while True:
                time.sleep(1)
        time.sleep(0.1)
    return 2


if __name__ == "__main__":
    sys.exit(main())
