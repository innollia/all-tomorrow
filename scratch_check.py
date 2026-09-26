import os
import psycopg

url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")
with psycopg.connect(url) as conn:
    cur = conn.cursor()
    cur.execute("SELECT workflow_uuid, status, name, created_at FROM dbos.workflow_status WHERE status = 'PENDING' OR status = 'ENQUEUED'")
    rows = cur.fetchall()
    print("Found pending/enqueued workflows:", len(rows))
    for r in rows:
        print("  ", r)
