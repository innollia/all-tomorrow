import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from all_tomorrow.contracts import (
    ContractError,
    ExecutionContext,
    PipelineSpec,
    PipelineStep,
    RequestEnvelope,
    UserQuestion,
)
from all_tomorrow.delivery import (
    DeliveryId,
    DeliveryKind,
    DeliveryRecord,
    DeliveryStatus,
    RetentionClass,
    calculate_valid_until,
    format_idempotency_key,
    utc_now,
)
from all_tomorrow.storage import (
    DeliveryCASConflictError,
    IdempotencyKeyExpiredError,
    PostgresStore,
    QuestionRecord,
    RunConflictError,
    RunRecord,
    RunStateStore,
    RunStatus,
    execution_context_from_dict,
    execution_context_to_dict,
    hash_resume_token,
    pipeline_spec_from_dict,
    pipeline_spec_to_dict,
    run_record_from_dict,
    run_record_to_dict,
)


def test_resume_tokens_are_stored_as_hashes() -> None:
    token = "resume_secret-value"
    digest = hash_resume_token(token)
    assert digest != token
    assert len(digest) == 64
    assert digest == hash_resume_token(token)


def test_hash_resume_token_rejects_empty_or_whitespace() -> None:
    with pytest.raises(ContractError, match="non-empty"):
        hash_resume_token("")
    with pytest.raises(ContractError, match="non-empty"):
        hash_resume_token("   ")


def test_postgres_store_satisfies_run_state_store_protocol() -> None:
    store = PostgresStore("postgresql://fake:5432/test")
    assert isinstance(store, RunStateStore)


def test_run_record_snapshot_never_contains_plaintext_resume_token() -> None:
    spec = PipelineSpec(
        pipeline_id="sec_test",
        version=1,
        status="active",
        steps=(PipelineStep(id="step1", type="test"),),
    )
    context = ExecutionContext(
        request=RequestEnvelope(message="msg", source="test"),
        user_ref="user:alice",
    )
    secret_token = "resume_secret_12345"
    question = UserQuestion(
        question="Approve?",
        reason="Check",
        blocked_step="step1",
        required_fields=("approved",),
        resume_token=secret_token,
    )

    # When stored in RunRecord, question should have token stripped or run_record_to_dict strips it
    run = RunRecord(
        run_id="run_sec",
        spec=spec,
        context=context,
        current_step_id="step1",
        question=question,
    )
    snapshot = run_record_to_dict(run)

    # Prove that the plaintext secret does NOT exist anywhere in the snapshot
    serialized = json.dumps(snapshot)
    assert secret_token not in serialized
    assert snapshot["question"]["resume_token"] is None if "resume_token" in snapshot["question"] else True


def test_execution_context_and_pipeline_spec_serialization_roundtrip() -> None:
    spec = PipelineSpec(
        pipeline_id="roundtrip",
        version=2,
        status="active",
        parent_version=1,
        change_reason="Add step",
        trigger={"cron": "0 0 * * *"},
        steps=(
            PipelineStep(id="s1", type="node.first", max_retries=2),
            PipelineStep(id="s2", type="node.second", when={"ref": "s1.output", "equals": "ok"}),
        ),
    )
    spec_dict = pipeline_spec_to_dict(spec)
    spec_restored = pipeline_spec_from_dict(spec_dict)
    assert spec_restored.pipeline_id == spec.pipeline_id
    assert spec_restored.version == spec.version
    assert len(spec_restored.steps) == 2
    assert spec_restored.steps[0].max_retries == 2
    assert spec_restored.steps[1].when == {"ref": "s1.output", "equals": "ok"}

    context = ExecutionContext(
        request=RequestEnvelope(
            message="Test message",
            source="discord",
            candidate_project_id="proj_1",
            central_reason="escalated",
        ),
        user_ref="user:tester",
        variables={"steps": {"s1": {"output": "ok"}}, "user_answers": {"s2": {"confirmed": True}}},
        permissions={"read", "write"},
    )
    ctx_dict = execution_context_to_dict(context)
    ctx_restored = execution_context_from_dict(ctx_dict)
    assert ctx_restored.user_ref == context.user_ref
    assert ctx_restored.request.message == "Test message"
    assert ctx_restored.request.candidate_project_id == "proj_1"
    assert ctx_restored.variables["steps"]["s1"]["output"] == "ok"
    assert ctx_restored.permissions == {"read", "write"}

    run = RunRecord(
        run_id="run_rt",
        spec=spec,
        context=context,
        current_step_id="s2",
        outputs={"s1": "ok"},
        attempts={"s1": 1},
        status=RunStatus.RUNNING,
        revision=3,
    )
    run_dict = run_record_to_dict(run)
    run_restored = run_record_from_dict(run_dict)
    assert run_restored.run_id == "run_rt"
    assert run_restored.revision == 3
    assert run_restored.outputs == {"s1": "ok"}
    assert run_restored.status is RunStatus.RUNNING


@pytest.mark.asyncio
async def test_postgres_store_update_run_conflict_raises_run_conflict_error() -> None:
    # Set up mock pool where execute returns cursor with fetchone() returning None (conflict)
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = None

    mock_connection = AsyncMock()
    mock_connection.execute.return_value = mock_cursor

    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__.return_value = mock_connection
    mock_conn_ctx.__aexit__.return_value = False

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn_ctx

    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    spec = PipelineSpec(
        pipeline_id="p1",
        version=1,
        status="active",
        steps=(PipelineStep(id="s1", type="node"),),
    )
    context = ExecutionContext(
        request=RequestEnvelope(message="m", source="s"),
        user_ref="u",
    )
    run = RunRecord(run_id="run_c1", spec=spec, context=context, current_step_id="s1", revision=2)

    with pytest.raises(RunConflictError, match="revision conflict"):
        await store.update_run(run, expected_revision=2)


@pytest.mark.asyncio
async def test_postgres_store_consume_question_atomic_query() -> None:
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (
        "q_1",
        "run_1",
        "step_confirm",
        "Confirm?",
        "Need auth",
        ["ok"],
        "token_hash_val",
        "answered",
        {"ok": True},
        "2026-09-18T12:00:00+00:00",
        "2026-09-18T12:05:00+00:00",
        None,
    )

    mock_connection = AsyncMock()
    mock_connection.execute.return_value = mock_cursor

    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__.return_value = mock_connection
    mock_conn_ctx.__aexit__.return_value = False

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn_ctx

    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)
    q = await store.consume_question("token_hash_val", {"ok": True})

    assert q is not None
    assert q.question_id == "q_1"
    assert q.status == "answered"
    assert q.answer == {"ok": True}

    # Verify SQL query used WHERE status = 'pending' and hash
    execute_calls = mock_connection.execute.call_args_list
    assert len(execute_calls) == 1
    sql = execute_calls[0][0][0]
    assert "status = 'pending'" in sql
    assert "resume_token_hash" in sql


def _create_mock_pool(cursor_or_fn):
    mock_connection = AsyncMock()
    if callable(cursor_or_fn) and not isinstance(cursor_or_fn, (AsyncMock, MagicMock)):
        mock_connection.execute.side_effect = cursor_or_fn
    else:
        mock_connection.execute.return_value = cursor_or_fn

    mock_tx = AsyncMock()
    mock_tx.__aenter__.return_value = mock_tx
    mock_tx.__aexit__.return_value = False
    mock_connection.transaction = MagicMock(return_value=mock_tx)

    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__.return_value = mock_connection
    mock_conn_ctx.__aexit__.return_value = False

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn_ctx
    return mock_pool, mock_connection


@pytest.mark.asyncio
async def test_postgres_store_save_pipeline_is_idempotent_for_identical_spec() -> None:
    spec = PipelineSpec(
        pipeline_id="p_idem",
        version=1,
        status="active",
        steps=(PipelineStep(id="s1", type="node"),),
    )
    payload = pipeline_spec_to_dict(spec)

    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (payload,)

    mock_pool, mock_connection = _create_mock_pool(mock_cursor)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)
    await store.save_pipeline(spec)

    # Invariant: idempotent when spec is identical — only queried, no INSERT or UPDATE
    assert mock_connection.execute.call_count == 1
    sql = mock_connection.execute.call_args_list[0][0][0]
    assert "SELECT spec FROM pipeline_versions" in sql
    assert "UPDATE pipeline_versions SET status = 'retired'" not in sql


@pytest.mark.asyncio
async def test_postgres_store_save_pipeline_conflicting_spec_raises_run_conflict_error() -> None:
    spec = PipelineSpec(
        pipeline_id="p_conflict",
        version=1,
        status="active",
        steps=(PipelineStep(id="s1", type="node"),),
    )
    conflicting_spec = PipelineSpec(
        pipeline_id="p_conflict",
        version=1,
        status="active",
        steps=(PipelineStep(id="s1", type="node", max_retries=99),),
    )
    stored_payload = pipeline_spec_to_dict(spec)

    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (stored_payload,)

    mock_pool, mock_connection = _create_mock_pool(mock_cursor)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    with pytest.raises(RunConflictError, match="already exists with different definition"):
        await store.save_pipeline(conflicting_spec)

    # Verify no INSERT or UPDATE queries were executed
    assert mock_connection.execute.call_count == 1
    sql = mock_connection.execute.call_args_list[0][0][0]
    assert "SELECT spec FROM pipeline_versions" in sql


@pytest.mark.asyncio
async def test_postgres_store_save_pipeline_does_not_retire_active_versions() -> None:
    spec = PipelineSpec(
        pipeline_id="p_noretire",
        version=2,
        status="active",
        steps=(PipelineStep(id="s1", type="node"),),
    )

    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = None  # does not exist yet

    mock_pool, mock_connection = _create_mock_pool(mock_cursor)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)
    await store.save_pipeline(spec)

    # Invariant: save_pipeline does NOT retire active versions
    queries = [call[0][0] for call in mock_connection.execute.call_args_list]
    for q in queries:
        assert "UPDATE pipeline_versions SET status = 'retired'" not in q
    assert any("INSERT INTO pipeline_versions" in q for q in queries)


@pytest.mark.asyncio
async def test_postgres_store_publish_pipeline_retires_active_and_enforces_immutability() -> None:
    spec_v1 = PipelineSpec(
        pipeline_id="p_pub",
        version=1,
        status="active",
        steps=(PipelineStep(id="s1", type="node"),),
    )
    conflicting_v1 = PipelineSpec(
        pipeline_id="p_pub",
        version=1,
        status="active",
        steps=(PipelineStep(id="s2", type="other"),),
    )

    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (pipeline_spec_to_dict(spec_v1), "active")

    mock_pool, mock_connection = _create_mock_pool(mock_cursor)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    # Conflicting spec cannot be published/overwritten
    with pytest.raises(RunConflictError, match="already exists with different definition"):
        await store.publish_pipeline(conflicting_v1)

    # Publishing a brand new active version DOES retire existing active versions
    mock_cursor.fetchone.return_value = None
    mock_connection.execute.reset_mock()

    spec_v2 = PipelineSpec(
        pipeline_id="p_pub",
        version=2,
        status="active",
        steps=(PipelineStep(id="s1", type="node"),),
    )
    await store.publish_pipeline(spec_v2)

    queries = [call[0][0] for call in mock_connection.execute.call_args_list]
    assert any("UPDATE pipeline_versions SET status = 'retired'" in q for q in queries)
    assert any("INSERT INTO pipeline_versions" in q for q in queries)


@pytest.mark.asyncio
async def test_postgres_store_create_run_transaction_boundary_and_immutability() -> None:
    spec = PipelineSpec(
        pipeline_id="p_run_tx",
        version=1,
        status="active",
        steps=(PipelineStep(id="s1", type="node"),),
    )
    context = ExecutionContext(
        request=RequestEnvelope(message="m", source="s"),
        user_ref="u",
    )
    run = RunRecord(
        run_id="run_tx_1",
        spec=spec,
        context=context,
        current_step_id="s1",
    )

    # When spec exists and conflicts, create_run raises RunConflictError before inserting run
    conflicting_stored = PipelineSpec(
        pipeline_id="p_run_tx",
        version=1,
        status="active",
        steps=(PipelineStep(id="s1", type="different_node"),),
    )
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (pipeline_spec_to_dict(conflicting_stored),)

    mock_pool, mock_connection = _create_mock_pool(mock_cursor)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    with pytest.raises(RunConflictError, match="already exists with different definition"):
        await store.create_run(run)

    # Invariant: run was NOT inserted due to transaction rollback on conflict
    queries = [call[0][0] for call in mock_connection.execute.call_args_list]
    assert not any("INSERT INTO runs" in q for q in queries)
    assert mock_connection.transaction.called


@pytest.mark.asyncio
async def test_postgres_store_resume_run_atomic_transaction_and_locks() -> None:
    spec = PipelineSpec(
        pipeline_id="p_atomic",
        version=1,
        status="active",
        steps=(PipelineStep(id="step_confirm", type="ask"),),
    )
    context = ExecutionContext(
        request=RequestEnvelope(message="m", source="s"),
        user_ref="u",
    )

    q_row = (
        "q_1",
        "run_1",
        "step_confirm",
        "Confirm?",
        "Need auth",
        ["confirmed"],
        "token_hash_val",
        "pending",
        None,
        "2026-09-18T12:00:00+00:00",
        None,
        None,
    )

    run_row = (
        "run_1",
        context.request.request_id,
        context.trace_id,
        context.user_ref,
        None,
        None,
        spec.pipeline_id,
        spec.version,
        "NEED_USER",
        "step_confirm",
        execution_context_to_dict(context),
        {},
        {},
        None,
        2,  # revision
        pipeline_spec_to_dict(spec),
    )

    async def execute_side_effect(query: str, params=None):
        cur = AsyncMock()
        if "FROM user_questions" in query and "FOR UPDATE" in query:
            cur.fetchone.return_value = q_row
        elif "FROM runs r" in query and "FOR UPDATE OF r" in query:
            cur.fetchone.return_value = run_row
        elif "UPDATE runs" in query:
            cur.fetchone.return_value = (3,)
        else:
            cur.fetchone.return_value = None
        return cur

    mock_pool, mock_connection = _create_mock_pool(execute_side_effect)

    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)
    resumed = await store.resume_run("token_hash_val", {"confirmed": True})

    assert resumed.run_id == "run_1"
    assert resumed.status is RunStatus.RUNNING
    assert resumed.revision == 3
    assert resumed.question is None
    assert resumed.context.variables["user_answers"]["step_confirm"] == {"confirmed": True}

    # Verify transaction and locking SQL
    assert mock_connection.transaction.called
    queries = [call[0][0] for call in mock_connection.execute.call_args_list]
    assert any("FOR UPDATE" in q and "user_questions" in q for q in queries)
    assert any("FOR UPDATE OF r" in q and "runs" in q for q in queries)
    assert any("UPDATE runs" in q and "SET status = 'RUNNING'" in q for q in queries)
    assert any("UPDATE user_questions" in q and "SET status = 'answered'" in q for q in queries)


@pytest.mark.asyncio
async def test_postgres_store_resume_run_validation_failure_leaves_records_untouched() -> None:
    q_row = (
        "q_1",
        "run_1",
        "step_confirm",
        "Confirm?",
        "Need auth",
        ["confirmed"],
        "token_hash_val",
        "pending",
        None,
        "2026-09-18T12:00:00+00:00",
        None,
        None,
    )

    async def execute_side_effect(query: str, params=None):
        cur = AsyncMock()
        if "FROM user_questions" in query and "FOR UPDATE" in query:
            cur.fetchone.return_value = q_row
        return cur

    mock_pool, mock_connection = _create_mock_pool(execute_side_effect)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    # Missing required field "confirmed" raises ContractError
    with pytest.raises(ContractError, match="missing required answer fields: confirmed"):
        await store.resume_run("token_hash_val", {})

    # Invariant: Neither runs nor user_questions UPDATE was executed
    queries = [call[0][0] for call in mock_connection.execute.call_args_list]
    assert not any("UPDATE runs" in q for q in queries)
    assert not any("UPDATE user_questions" in q for q in queries)


@pytest.mark.asyncio
async def test_postgres_store_atomic_outbox_commits_domain_and_outbox_in_transaction() -> None:
    """S0-00B3-01: PostgresStore.atomic_outbox_transaction commits domain and outbox intent together."""
    from datetime import timedelta

    intent = DeliveryRecord(
        delivery_id=DeliveryId("del_pg_1"),
        kind=DeliveryKind.RUN_START,
        subject_refs={"run_id": "run_pg_1"},
        destination_adapter="fake_durable",
        idempotency_key="idmp_pg_outbox_1",
        payload={"flow": "test"},
        retention_class="standard",
        valid_until=utc_now() + timedelta(hours=24),
    )

    db_row = (
        "del_pg_1",
        "RUN_START",
        {"run_id": "run_pg_1"},
        "fake_durable",
        "idmp_pg_outbox_1",
        "global",
        "standard",
        intent.valid_until,
        {"flow": "test"},
        "PENDING",
        0,
        3,
        1,
        None,
        None,
        None,
        intent.created_at,
        intent.updated_at,
    )

    async def execute_side_effect(query: str, params=None):
        cur = AsyncMock()
        if "SELECT delivery_id" in query and "FOR UPDATE" in query:
            cur.fetchone.return_value = None  # Key not yet in DB
        elif "INSERT INTO delivery_records" in query and "RETURNING" in query:
            cur.fetchone.return_value = db_row  # Inserted new row returned
        else:
            cur.fetchone.return_value = None
        return cur

    mock_pool, mock_connection = _create_mock_pool(execute_side_effect)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    domain_mutations = []

    async def domain_action(conn):
        domain_mutations.append("domain_work_done")
        return "domain_result_val"

    result, canonical = await store.atomic_outbox_transaction(intent, domain_action)

    assert result == "domain_result_val"
    assert domain_mutations == ["domain_work_done"]
    assert canonical.delivery_id == intent.delivery_id
    assert canonical.idempotency_key == intent.idempotency_key

    # Invariant: connection.transaction() was used
    assert mock_connection.transaction.called
    queries = [call[0][0] for call in mock_connection.execute.call_args_list]
    assert any("INSERT INTO delivery_records" in q and "RETURNING" in q for q in queries)


@pytest.mark.asyncio
async def test_postgres_store_atomic_outbox_rolls_back_domain_when_outbox_fails() -> None:
    """S0-00B3-01: When outbox insert fails, entire PostgreSQL transaction rolls back."""
    from datetime import timedelta

    intent = DeliveryRecord(
        delivery_id=DeliveryId("del_pg_fail"),
        kind=DeliveryKind.RUN_START,
        subject_refs={"run_id": "run_pg_fail"},
        destination_adapter="fake_durable",
        idempotency_key="idmp_pg_fail",
        payload={},
        retention_class="standard",
        valid_until=utc_now() + timedelta(hours=24),
    )

    # Simulate database error on insert
    mock_connection = AsyncMock()
    mock_connection.execute.side_effect = RuntimeError("Database constraint or disk failure")

    mock_tx = AsyncMock()
    mock_tx.__aenter__.return_value = mock_tx
    mock_tx.__aexit__.return_value = False  # Does not suppress exception -> triggers rollback
    mock_connection.transaction = MagicMock(return_value=mock_tx)

    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__.return_value = mock_connection
    mock_conn_ctx.__aexit__.return_value = False

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn_ctx

    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    domain_mutated = []

    async def domain_action(conn):
        domain_mutated.append("run_created")
        return "run_123"

    with pytest.raises(RuntimeError, match="Database constraint or disk failure"):
        await store.atomic_outbox_transaction(intent, domain_action)

    # Invariant: transaction context exited with error, propagating rollback
    assert mock_tx.__aexit__.called
    exc_type = mock_tx.__aexit__.call_args[0][0]
    assert exc_type is RuntimeError


@pytest.mark.asyncio
async def test_postgres_store_atomic_outbox_returns_db_canonical_row_on_conflict() -> None:
    """S0-00B3-01: When idempotency key already exists, RETURNING yields DB canonical row instead of caller input."""
    from datetime import timedelta

    existing_time = utc_now()
    existing_db_row = (
        "del_existing_999",
        "RUN_START",
        {"run_id": "run_original"},
        "fake_durable",
        "idmp_shared_key",
        "global",
        "standard",
        existing_time + timedelta(hours=24),
        {"workflow": "original_flow"},
        "DELIVERED",
        1,
        3,
        2,
        None,
        None,
        existing_time,
        existing_time,
        existing_time,
    )

    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = existing_db_row

    mock_pool, mock_connection = _create_mock_pool(mock_cursor)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    # Second caller tries with different delivery_id & status
    new_intent = DeliveryRecord(
        delivery_id=DeliveryId("del_new_attempt"),
        kind=DeliveryKind.RUN_START,
        subject_refs={"run_id": "run_original"},
        destination_adapter="fake_durable",
        idempotency_key="idmp_shared_key",
        payload={"workflow": "original_flow"},
        status=DeliveryStatus.PENDING,
        retention_class="standard",
        valid_until=existing_time + timedelta(hours=24),
    )

    async def noop_domain(conn):
        return None

    _, returned_record = await store.atomic_outbox_transaction(new_intent, noop_domain)

    # Invariant: Caller receives the DB canonical row (del_existing_999, DELIVERED), NOT new_intent (del_new_attempt, PENDING)
    assert returned_record.delivery_id == DeliveryId("del_existing_999")
    assert returned_record.status == DeliveryStatus.DELIVERED
    assert returned_record.revision == 2


@pytest.mark.asyncio
async def test_postgres_store_atomic_outbox_detects_conflict_on_divergent_payload() -> None:
    """S0-00B3-01: When same idempotency key is presented with different target/subject, fail closed with DeliveryCASConflictError."""
    from datetime import timedelta

    existing_db_row = (
        "del_orig",
        "RUN_START",
        {"run_id": "run_orig"},
        "destination_A",
        "idmp_shared_key",
        "global",
        "standard",
        utc_now() + timedelta(hours=24),
        {},
        "DELIVERED",
        1,
        3,
        1,
        None,
        None,
        None,
        utc_now(),
        utc_now(),
    )

    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = existing_db_row
    mock_pool, mock_connection = _create_mock_pool(mock_cursor)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    # Divergent caller with different destination_adapter
    divergent_intent = DeliveryRecord(
        delivery_id=DeliveryId("del_divergent"),
        kind=DeliveryKind.RUN_START,
        subject_refs={"run_id": "run_divergent"},
        destination_adapter="destination_B",
        idempotency_key="idmp_shared_key",
        payload={},
        valid_until=utc_now() + timedelta(hours=24),
    )

    async def noop_domain(conn):
        return None

    with pytest.raises(DeliveryCASConflictError, match="already exists with different destination or subjects"):
        await store.atomic_outbox_transaction(divergent_intent, noop_domain)


@pytest.mark.asyncio
async def test_postgres_store_atomic_outbox_rejects_expired_existing_idempotency_key() -> None:
    """S0-00B3-05: When existing idempotency key in DB has expired, reuse is rejected with IdempotencyKeyExpiredError."""
    from datetime import timedelta

    past = utc_now() - timedelta(hours=1)
    expired_db_row = (
        "del_expired_db",
        "RUN_START",
        {"run_id": "run_1"},
        "fake_durable",
        "idmp_expired_key",
        "global",
        "standard",
        past,  # Expired in DB!
        {},
        "DELIVERED",
        1,
        3,
        1,
        None,
        None,
        None,
        past,
        past,
    )

    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = expired_db_row
    mock_pool, mock_connection = _create_mock_pool(mock_cursor)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    intent = DeliveryRecord(
        delivery_id=DeliveryId("del_reuse_attempt"),
        kind=DeliveryKind.RUN_START,
        subject_refs={"run_id": "run_1"},
        destination_adapter="fake_durable",
        idempotency_key="idmp_expired_key",
        payload={},
        valid_until=utc_now() + timedelta(hours=24),
    )

    async def noop_domain(conn):
        return None

    with pytest.raises(IdempotencyKeyExpiredError, match="expired at"):
        await store.atomic_outbox_transaction(intent, noop_domain)


@pytest.mark.asyncio
async def test_postgres_store_preserves_last_error_on_retrieval() -> None:
    """S0-00B3: Stored last_error is properly deserialized into CanonicalError on get_delivery and outbox retrieval."""
    from all_tomorrow.domain.errors import CanonicalError, ErrorCategory

    raw_error = {
        "category": "UNAVAILABLE",
        "code": "network_down",
        "retryability": True,
        "ambiguity": False,
        "safe_message": "Network cut off",
    }

    db_row = (
        "del_err_1",
        "RUN_START",
        {"run_id": "run_err"},
        "fake_durable",
        "idmp_err_key",
        "global",
        "standard",
        None,
        {},
        "FAILED",
        1,
        3,
        1,
        raw_error,  # last_error
        None,
        None,
        utc_now(),
        utc_now(),
    )

    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = db_row
    mock_pool, mock_connection = _create_mock_pool(mock_cursor)
    store = PostgresStore("postgresql://fake:5432/test", pool=mock_pool)

    delivery = await store.get_delivery("del_err_1")
    assert delivery is not None
    assert delivery.last_error is not None
    assert isinstance(delivery.last_error, CanonicalError)
    assert delivery.last_error.category == ErrorCategory.UNAVAILABLE
    assert delivery.last_error.code == "network_down"
    assert delivery.last_error.safe_message == "Network cut off"


