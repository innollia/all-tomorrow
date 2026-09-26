"""Separate DBOS worker used to probe a durable message wait."""

import os
import sys
import time

from dbos import DBOS, SetWorkflowID


WORKFLOW_ID = os.environ["AT_TEST_WORKFLOW_ID"]


@DBOS.workflow(name="signal_probe_workflow")
def workflow() -> dict:
    DBOS.set_event("waiting", True)
    approval = DBOS.recv(topic="approval", timeout_seconds=30)
    DBOS.set_event("post_signal_mutation", True)
    return approval


def main() -> int:
    DBOS(config={"name": "all-tomorrow-signal-probe", "system_database_url": os.environ["AT_TEST_POSTGRES_URL"]})
    DBOS.launch()
    if os.environ["AT_TEST_PHASE"] == "wait":
        with SetWorkflowID(WORKFLOW_ID):
            DBOS.start_workflow(workflow)
        for _ in range(100):
            if DBOS.get_event(WORKFLOW_ID, "waiting", timeout_seconds=0.1):
                print(f"waiting_pid={os.getpid()}", flush=True)
                while True:
                    time.sleep(1)
            time.sleep(0.1)
        return 2
    if os.environ["AT_TEST_PHASE"] == "cancel":
        DBOS.cancel_workflow(WORKFLOW_ID)
        DBOS.send(WORKFLOW_ID, {"approved": True}, topic="approval")
        time.sleep(1)
        status = DBOS.get_workflow_status(WORKFLOW_ID)
        mutated = DBOS.get_event(WORKFLOW_ID, "post_signal_mutation", timeout_seconds=0.1)
        print(f"status={status.status if status else None} mutated={mutated}", flush=True)
        DBOS.destroy()
        return 0
    DBOS.send(WORKFLOW_ID, {"approved": True}, topic="approval")
    result = DBOS.retrieve_workflow(WORKFLOW_ID).get_result()
    print(f"resumed_pid={os.getpid()} approved={result['approved']}", flush=True)
    DBOS.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
