from pathlib import Path


def test_core_migration_has_required_authorities_and_guards() -> None:
    sql = Path("migrations/0001_core.sql").read_text(encoding="utf-8").lower()
    for table in (
        "projects",
        "tasks",
        "runs",
        "run_steps",
        "events",
        "pipeline_versions",
        "user_questions",
        "workers",
        "tools",
        "capabilities",
        "registry_bindings",
    ):
        assert f"create table if not exists {table}" in sql
    assert "one_active_pipeline_version" in sql
    assert "one_pending_question_per_run" in sql
    assert "unique (trace_id)" in sql
    assert "resume_token_hash" in sql


def test_delivery_migration_evolution_and_retention_backfill() -> None:
    sql_0003 = Path("migrations/0003_delivery.sql").read_text(encoding="utf-8").lower()
    assert "create table if not exists delivery_records" in sql_0003
    assert "idempotency_key" in sql_0003

    sql_0004 = Path("migrations/0004_delivery_retention.sql").read_text(encoding="utf-8").lower()
    # Verifies ALTER TABLE schema evolution for databases where 0003 was already executed
    assert "alter table delivery_records" in sql_0004
    assert "add column if not exists idempotency_scope" in sql_0004
    assert "add column if not exists retention_class" in sql_0004
    assert "add column if not exists valid_until" in sql_0004
    # Verifies backfill policy for existing standard retention rows
    assert "update delivery_records" in sql_0004
    assert "valid_until = created_at + interval '24 hours'" in sql_0004


