import os
from dbos import DBOS, SetWorkflowID
DBOS(config={"name": "test-app", "system_database_url": "postgresql:///at_dbos_probe"})
DBOS.launch()
@DBOS.workflow(name="w_test")
def w_test():
    return 123
h = DBOS.retrieve_workflow("test-dummy-1")
print("dir(h):", [m for m in dir(h) if not m.startswith("_")])
status = DBOS.get_workflow_status("test-dummy-1")
print("dir(status):", [m for m in dir(status) if not m.startswith("_")])
print("status.status:", status.status if status else None)
print("status attributes:", {k: getattr(status, k) for k in ["status", "workflow_id", "workflow_uuid", "error", "output"] if hasattr(status, k)})
print("cancel_workflow on non-existent:")
try:
    DBOS.cancel_workflow("non-existent")
    print("cancelled!")
except Exception as e:
    print("cancel error:", type(e), e)
DBOS.destroy()
