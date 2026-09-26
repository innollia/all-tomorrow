"""Separate worker process for the PostgreSQL DBOS crash/recovery probe."""

from __future__ import annotations

import os
import sys

import psycopg
from dbos import DBOS, SetWorkflowID


SYSTEM_URL = os.environ["AT_TEST_POSTGRES_URL"]
FIXTURE_URL = os.environ["AT_TEST_FIXTURE_URL"]
WORKFLOW_ID = os.environ["AT_TEST_WORKFLOW_ID"]
PHASE = os.environ["AT_TEST_PHASE"]


@DBOS.step(name="crash_probe_external_mutation")
def external_mutation() -> str:
    with psycopg.connect(FIXTURE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO crash_probe (idempotency_key, call_count, application_count, committed_value)
                   VALUES (%s, 1, 1, 'committed')
                   ON CONFLICT (idempotency_key) DO UPDATE
                   SET call_count = crash_probe.call_count + 1
                   RETURNING call_count, application_count""",
                (WORKFLOW_ID,),
            )
            call_count, application_count = cursor.fetchone()
        conn.commit()
    if PHASE == "crash" and call_count == 1:
        os._exit(77)
    assert application_count == 1
    return "committed"


@DBOS.workflow(name="crash_probe_workflow")
def workflow() -> str:
    return external_mutation()


def main() -> int:
    print(f"worker_pid={os.getpid()}", flush=True)
    DBOS(config={"name": "all-tomorrow-crash-probe", "system_database_url": SYSTEM_URL})
    DBOS.launch()
    with SetWorkflowID(WORKFLOW_ID):
        result = workflow()
    print(result, flush=True)
    DBOS.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
