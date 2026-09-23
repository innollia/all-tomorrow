"""New DBOS application binary: old model schema accepted, new finalization added."""

import os
import sys

import psycopg
from dbos import DBOS
from otel_file_exporter import tracer_for


WORKFLOW_ID = os.environ["AT_TEST_WORKFLOW_ID"]
TRACER = tracer_for(os.environ["AT_TEST_OTEL_SPANS"])


@DBOS.step(name="upgrade_model_step")
def model() -> dict:
    # Existing in-flight workflows replay the V1 result. This implementation
    # would be used only for newly started V2 workflows.
    return {"stock": 42, "source": "v2"}


@DBOS.step(name="upgrade_v2_finalize")
def finalize() -> None:
    with psycopg.connect(os.environ["AT_TEST_FIXTURE_URL"]) as conn:
        conn.execute("UPDATE upgrade_probe SET finalized=TRUE WHERE workflow_id=%s", (WORKFLOW_ID,))
        conn.commit()


@DBOS.workflow(name="upgrade_workflow")
def workflow(correlation_id: str) -> dict:
    decision = model()
    DBOS.set_event("waiting", True)
    approval = DBOS.recv(topic="approval", timeout_seconds=45)
    with TRACER.start_as_current_span("v2_recovered") as span:
        span.set_attribute("all_tomorrow.correlation_id", correlation_id)
        span.set_attribute("all_tomorrow.transient_caller_id", os.environ["AT_TEST_TRANSIENT_CORR"])
    finalize()
    return {
        "stock": decision["stock"],
        "approved": approval["approved"],
        "schema": 2,
        "source": decision.get("source", "v1-replayed"),
    }


def main() -> int:
    DBOS(config={"name": "all-tomorrow-upgrade-probe", "system_database_url": os.environ["AT_TEST_POSTGRES_URL"], "application_version": "compat-v1"})
    DBOS.launch()
    DBOS.send(WORKFLOW_ID, {"approved": True}, topic="approval")
    result = DBOS.retrieve_workflow(WORKFLOW_ID).get_result()
    print(f"v2_pid={os.getpid()} result={result}", flush=True)
    DBOS.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
