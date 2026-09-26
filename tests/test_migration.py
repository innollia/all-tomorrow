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


def test_semantic_kernel_migration_0006_schema() -> None:
    """01A — Goal/Work/Run semantic schema present and invariant-safe."""
    sql = Path("migrations/0006_semantic_kernel.sql").read_text(encoding="utf-8").lower()

    # Core semantic tables exist (01A goals/work_items/runs/outcomes/questions/events)
    for table in (
        "goals",
        "work_items",
        "runs_semantic",
        "outcomes",
        "questions_semantic",
        "semantic_events",
    ):
        assert f"create table if not exists {table}" in sql, f"missing table {table}"

    def _body(name: str) -> str:
        marker = f"create table if not exists {name} ("
        assert marker in sql
        return sql.split(marker, 1)[1].split(");", 1)[0]

    work_body = _body("work_items")
    runs_body = _body("runs_semantic")

    # 01A-03: ExecutionRef fields live ONLY on the Run, never on Work
    for col in ("execution_backend", "execution_id", "execution_version"):
        assert col not in work_body, f"work_items must not own {col}"
        assert col in runs_body, f"runs_semantic must own {col}"

    # 01A-04: no queue/lease mechanics on either semantic table
    for col in ("claimed_by", "lease_expires_at"):
        assert col not in work_body, f"work_items must not own {col}"
        assert col not in runs_body, f"runs_semantic must not own {col}"

    # 01A-02: Work 1:N Run — FK from run to work + single active-run guard
    assert "references work_items(work_id)" in runs_body
    assert "one_active_run_per_work" in sql

    # runs.trace_id UNIQUE 금지 (per 01A runs constraints)
    assert "unique" not in runs_body.split("trace_id", 1)[1].split(",", 1)[0]

    # 01A-07: SATISFIED outcome requires criterion + evaluator linkage
    assert "outcomes_satisfied_requires_evidence" in sql

    # 01A-08: canonical Question lifecycle statuses
    for status in ("pending", "answered", "superseded", "cancelled", "expired"):
        assert status in _body("questions_semantic")


def test_semantic_kernel_migration_preserves_legacy_tables() -> None:
    """01A migration policy — legacy 0001 tables are not dropped/renamed away."""
    sql = Path("migrations/0006_semantic_kernel.sql").read_text(encoding="utf-8").lower()
    # forward-only: no destructive ops against legacy identity tables
    for legacy in ("tasks", "pipeline_versions"):
        assert f"drop table {legacy}" not in sql
        assert f"rename table {legacy}" not in sql
        assert f"alter table {legacy} rename" not in sql


