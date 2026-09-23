"""Additive V2 finalization, deliberately absent from the V1 workflow history."""
import psycopg


def finalize(fixture_url, key):
    with psycopg.connect(fixture_url) as conn:
        conn.execute("INSERT INTO common_upgrade_probe (idempotency_key, schema_version) VALUES (%s, 2) ON CONFLICT DO NOTHING", (key,))
    return 2
