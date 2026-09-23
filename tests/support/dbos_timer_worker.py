"""DBOS durable timer worker, intentionally interrupted mid-delay."""

import os
import sys
import time

from dbos import DBOS, SetWorkflowID


WORKFLOW_ID = os.environ["AT_TEST_WORKFLOW_ID"]


@DBOS.workflow(name="timer_probe_workflow")
def workflow() -> float:
    DBOS.set_event("started", time.time())
    DBOS.sleep(5)
    return time.time()


def main() -> int:
    DBOS(config={"name": "all-tomorrow-timer-probe", "system_database_url": os.environ["AT_TEST_POSTGRES_URL"]})
    DBOS.launch()
    if os.environ["AT_TEST_PHASE"] == "start":
        with SetWorkflowID(WORKFLOW_ID):
            DBOS.start_workflow(workflow)
        for _ in range(100):
            started = DBOS.get_event(WORKFLOW_ID, "started", timeout_seconds=0.1)
            if started is not None:
                print(f"started={started} pid={os.getpid()}", flush=True)
                while True:
                    time.sleep(1)
            time.sleep(0.1)
        return 2
    launched = time.time()
    result = DBOS.retrieve_workflow(WORKFLOW_ID).get_result()
    print(f"launched={launched} finished={result} pid={os.getpid()}", flush=True)
    DBOS.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
