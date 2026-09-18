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

