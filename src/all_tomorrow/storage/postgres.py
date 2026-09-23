from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from all_tomorrow.contracts import ContractError, Event, PipelineSpec, Project, UserQuestion, new_id, utc_now
from all_tomorrow.delivery import (
    DeliveryId,
    DeliveryKind,
    DeliveryRecord,
    DeliveryStatus,
)
from all_tomorrow.storage.run_store import (
    QuestionRecord,
    RunConflictError,
    RunRecord,
    RunStatus,
    execution_context_from_dict,
    execution_context_to_dict,
    hash_resume_token,
    pipeline_spec_from_dict,
    pipeline_spec_to_dict,
    run_record_to_dict,
    specs_equal,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default))


class PostgresStore:
    """Durable orchestration store. Domain state remains behind its source adapter."""

    def __init__(self, database_url: str, *, pool: AsyncConnectionPool | None = None) -> None:
        self.pool = pool or AsyncConnectionPool(database_url, open=False)

    async def open(self) -> None:
        await self.pool.open()

    async def close(self) -> None:
        await self.pool.close()

    async def migrate(self, migration_dir: str | Path) -> None:
        paths = sorted(Path(migration_dir).glob("*.sql"))
        async with self.pool.connection() as connection:
            for path in paths:
                await connection.execute(path.read_text(encoding="utf-8"))

    async def register_project(self, project: Project) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO projects (project_id, name, owner, source_refs)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (project_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    owner = EXCLUDED.owner,
                    source_refs = EXCLUDED.source_refs,
                    updated_at = now()
                """,
                (project.project_id, project.name, project.owner, Jsonb(list(project.source_refs))),
            )

    async def publish_pipeline(self, spec: PipelineSpec, raw_spec: dict[str, Any] | None = None) -> None:
        payload = raw_spec if raw_spec is not None else pipeline_spec_to_dict(spec)
        async with self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    "SELECT spec, status FROM pipeline_versions WHERE pipeline_id = %s AND version = %s",
                    (spec.pipeline_id, spec.version),
                )
                row = await cursor.fetchone()
                if row is not None:
                    existing_spec = row[0]
                    if not specs_equal(existing_spec, payload):
                        raise RunConflictError(
                            f"pipeline spec {spec.identity} already exists with different definition"
                        )
                    if spec.status == "active":
                        await connection.execute(
                            "UPDATE pipeline_versions SET status = 'retired' WHERE pipeline_id = %s AND status = 'active' AND version != %s",
                            (spec.pipeline_id, spec.version),
                        )
                        await connection.execute(
                            "UPDATE pipeline_versions SET status = 'active' WHERE pipeline_id = %s AND version = %s",
                            (spec.pipeline_id, spec.version),
                        )
                    return

                if spec.status == "active":
                    await connection.execute(
                        "UPDATE pipeline_versions SET status = 'retired' WHERE pipeline_id = %s AND status = 'active'",
                        (spec.pipeline_id,),
                    )
                await connection.execute(
                    """
                    INSERT INTO pipeline_versions
                        (pipeline_id, version, status, parent_version, change_reason, spec)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        spec.pipeline_id,
                        spec.version,
                        spec.status,
                        spec.parent_version,
                        spec.change_reason,
                        Jsonb(payload),
                    ),
                )

    async def _save_pipeline_conn(
        self, connection: Any, spec: PipelineSpec, raw_spec: dict[str, Any] | None = None
    ) -> None:
        payload = raw_spec if raw_spec is not None else pipeline_spec_to_dict(spec)
        cursor = await connection.execute(
            "SELECT spec FROM pipeline_versions WHERE pipeline_id = %s AND version = %s",
            (spec.pipeline_id, spec.version),
        )
        row = await cursor.fetchone()
        if row is not None:
            existing_spec = row[0]
            if not specs_equal(existing_spec, payload):
                raise RunConflictError(
                    f"pipeline spec {spec.identity} already exists with different definition"
                )
            return

        await connection.execute(
            """
            INSERT INTO pipeline_versions
                (pipeline_id, version, status, parent_version, change_reason, spec)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                spec.pipeline_id,
                spec.version,
                spec.status,
                spec.parent_version,
                spec.change_reason,
                Jsonb(payload),
            ),
        )

    async def save_pipeline(self, spec: PipelineSpec, raw_spec: dict[str, Any] | None = None) -> None:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                await self._save_pipeline_conn(connection, spec, raw_spec)

    async def get_pipeline(self, pipeline_id: str, version: int) -> PipelineSpec | None:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT spec FROM pipeline_versions WHERE pipeline_id = %s AND version = %s",
                (pipeline_id, version),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return pipeline_spec_from_dict(row[0])

    async def create_run(self, run: RunRecord | dict[str, Any]) -> None:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                if isinstance(run, RunRecord):
                    await self._save_pipeline_conn(connection, run.spec)
                    snapshot = run_record_to_dict(run)
                else:
                    snapshot = run
                await connection.execute(
                    """
                    INSERT INTO runs
                        (run_id, request_id, trace_id, user_id, project_id, session_id,
                         pipeline_id, pipeline_version, status, current_step_id,
                         context, outputs, attempts, error, revision)
                    VALUES
                        (%(run_id)s, %(request_id)s, %(trace_id)s, %(user_id)s, %(project_id)s,
                         %(session_id)s, %(pipeline_id)s, %(pipeline_version)s, %(status)s,
                         %(current_step_id)s, %(context)s, %(outputs)s, %(attempts)s, %(error)s,
                         %(revision)s)
                    """,
                    {
                        **snapshot,
                        "context": Jsonb(snapshot["context"]),
                        "outputs": Jsonb(snapshot.get("outputs", {})),
                        "attempts": Jsonb(snapshot.get("attempts", {})),
                        "revision": snapshot.get("revision", 0),
                    },
                )

    async def update_run(
        self,
        run_or_id: RunRecord | str,
        expected_revision: int,
        changes: dict[str, Any] | None = None,
    ) -> int:
        if isinstance(run_or_id, RunRecord):
            run = run_or_id
            run_id = run.run_id
            field_changes = {
                "status": run.status.value,
                "current_step_id": run.current_step_id,
                "context": execution_context_to_dict(run.context),
                "outputs": dict(run.outputs),
                "attempts": dict(run.attempts),
                "error": run.error,
            }
        else:
            run_id = run_or_id
            if changes is None:
                return expected_revision
            field_changes = changes

        allowed = {"status", "current_step_id", "context", "outputs", "attempts", "error"}
        unknown = set(field_changes) - allowed
        if unknown:
            raise ValueError(f"unsupported run fields: {', '.join(sorted(unknown))}")
        if not field_changes:
            return expected_revision

        assignments: list[str] = []
        params: list[Any] = []
        for name, value in field_changes.items():
            assignments.append(f"{name} = %s")
            params.append(Jsonb(value) if name in {"context", "outputs", "attempts"} else value)
        params.extend([run_id, expected_revision])
        query = f"""
            UPDATE runs
            SET {', '.join(assignments)}, revision = revision + 1, updated_at = now()
            WHERE run_id = %s AND revision = %s
            RETURNING revision
        """
        async with self.pool.connection() as connection:
            cursor = await connection.execute(query, params)
            row = await cursor.fetchone()
        if row is None:
            raise RunConflictError(
                f"run {run_id} revision conflict or missing run (expected revision {expected_revision})"
            )
        new_rev = int(row[0])
        if isinstance(run_or_id, RunRecord):
            run_or_id.revision = new_rev
        return new_rev

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT r.run_id, r.request_id, r.trace_id, r.user_id, r.project_id, r.session_id,
                       r.pipeline_id, r.pipeline_version, r.status, r.current_step_id,
                       r.context, r.outputs, r.attempts, r.error, r.revision,
                       pv.spec,
                       q.question, q.reason, q.blocked_step, q.required_fields
                FROM runs r
                JOIN pipeline_versions pv
                  ON pv.pipeline_id = r.pipeline_id AND pv.version = r.pipeline_version
                LEFT JOIN user_questions q
                  ON q.run_id = r.run_id AND q.status = 'pending'
                WHERE r.run_id = %s
                """,
                (run_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None

        spec = pipeline_spec_from_dict(row[15])
        context = execution_context_from_dict(row[10])
        question = None
        if row[16] is not None:
            question = UserQuestion(
                question=row[16],
                reason=row[17],
                blocked_step=row[18],
                required_fields=tuple(row[19]),
                resume_token=None,
            )
        return RunRecord(
            run_id=row[0],
            spec=spec,
            context=context,
            current_step_id=row[9],
            outputs=dict(row[11] or {}),
            attempts=dict(row[12] or {}),
            status=RunStatus(row[8]),
            question=question,
            error=row[13],
            revision=int(row[14]),
        )

    async def create_question(
        self,
        question: QuestionRecord | str,
        user_question: UserQuestion | None = None,
    ) -> str:
        if isinstance(question, QuestionRecord):
            q_id = question.question_id
            run_id = question.run_id
            blocked_step = question.blocked_step
            q_text = question.question
            reason = question.reason
            required_fields = list(question.required_fields)
            token_hash = question.resume_token_hash
        else:
            run_id = question
            if user_question is None or user_question.resume_token is None:
                raise ValueError("question requires a resume token before persistence")
            q_id = new_id("question")
            blocked_step = user_question.blocked_step
            q_text = user_question.question
            reason = user_question.reason
            required_fields = list(user_question.required_fields)
            token_hash = hash_resume_token(user_question.resume_token)

        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO user_questions
                    (question_id, run_id, blocked_step, question, reason,
                     required_fields, resume_token_hash, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    q_id,
                    run_id,
                    blocked_step,
                    q_text,
                    reason,
                    Jsonb(required_fields),
                    token_hash,
                ),
            )
        return q_id

    async def get_pending_question(self, token_hash: str) -> QuestionRecord | None:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT question_id, run_id, blocked_step, question, reason,
                       required_fields, resume_token_hash, status, answer,
                       created_at, answered_at, expires_at
                FROM user_questions
                WHERE resume_token_hash = %s
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > now())
                """,
                (token_hash,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return QuestionRecord(
            question_id=row[0],
            run_id=row[1],
            blocked_step=row[2],
            question=row[3],
            reason=row[4],
            required_fields=tuple(row[5]),
            resume_token_hash=row[6],
            status=row[7],
            answer=row[8],
            created_at=row[9],
            answered_at=row[10],
            expires_at=row[11],
        )

    async def consume_question(self, token_hash: str, answer: dict[str, Any]) -> QuestionRecord | None:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE user_questions
                SET status = 'answered', answer = %s, answered_at = now()
                WHERE resume_token_hash = %s
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > now())
                RETURNING question_id, run_id, blocked_step, question, reason,
                          required_fields, resume_token_hash, status, answer,
                          created_at, answered_at, expires_at
                """,
                (Jsonb(answer), token_hash),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return QuestionRecord(
            question_id=row[0],
            run_id=row[1],
            blocked_step=row[2],
            question=row[3],
            reason=row[4],
            required_fields=tuple(row[5]),
            resume_token_hash=row[6],
            status=row[7],
            answer=row[8],
            created_at=row[9],
            answered_at=row[10],
            expires_at=row[11],
        )

    async def cancel_pending_questions(self, run_id: str) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                UPDATE user_questions
                SET status = 'cancelled'
                WHERE run_id = %s AND status = 'pending'
                """,
                (run_id,),
            )

    async def answer_question(self, resume_token: str, answer: dict[str, Any]) -> dict[str, Any] | None:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE user_questions
                SET status = 'answered', answer = %s, answered_at = now()
                WHERE resume_token_hash = %s
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > now())
                RETURNING question_id, run_id, blocked_step, required_fields
                """,
                (Jsonb(answer), hash_resume_token(resume_token)),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "question_id": row[0],
            "run_id": row[1],
            "blocked_step": row[2],
            "required_fields": row[3],
        }

    async def list_pending_questions(self, user_id: str) -> list[dict[str, Any]]:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT q.question_id, q.run_id, q.blocked_step, q.question, q.reason,
                       q.required_fields, q.created_at
                FROM user_questions q
                JOIN runs r ON r.run_id = q.run_id
                WHERE r.user_id = %s AND q.status = 'pending'
                  AND (q.expires_at IS NULL OR q.expires_at > now())
                ORDER BY q.created_at
                """,
                (user_id,),
            )
            rows = await cursor.fetchall()
        return [
            {
                "question_id": row[0],
                "run_id": row[1],
                "blocked_step": row[2],
                "question": row[3],
                "reason": row[4],
                "required_fields": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]

    async def resume_run(self, token_hash: str, answer: dict[str, Any]) -> RunRecord:
        if not isinstance(answer, dict):
            raise ContractError("answer must be a dictionary")

        async with self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    """
                    SELECT question_id, run_id, blocked_step, question, reason,
                           required_fields, resume_token_hash, status, answer,
                           created_at, answered_at, expires_at
                    FROM user_questions
                    WHERE resume_token_hash = %s
                    FOR UPDATE
                    """,
                    (token_hash,),
                )
                q_row = await cursor.fetchone()
                if q_row is None:
                    raise ContractError("invalid or already-used resume token")

                status = q_row[7]
                expires_at = q_row[11]
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at)
                if status != "pending":
                    raise ContractError("invalid or already-used resume token")
                if expires_at is not None and expires_at <= utc_now():
                    raise ContractError("invalid or already-used resume token")

                required_fields = tuple(q_row[5])
                missing = [f for f in required_fields if f not in answer]
                if missing:
                    raise ContractError(f"missing required answer fields: {', '.join(missing)}")

                run_id = q_row[1]
                blocked_step = q_row[2]

                cursor = await connection.execute(
                    """
                    SELECT r.run_id, r.request_id, r.trace_id, r.user_id, r.project_id, r.session_id,
                           r.pipeline_id, r.pipeline_version, r.status, r.current_step_id,
                           r.context, r.outputs, r.attempts, r.error, r.revision,
                           pv.spec
                    FROM runs r
                    JOIN pipeline_versions pv
                      ON pv.pipeline_id = r.pipeline_id AND pv.version = r.pipeline_version
                    WHERE r.run_id = %s
                    FOR UPDATE OF r
                    """,
                    (run_id,),
                )
                run_row = await cursor.fetchone()
                if run_row is None:
                    raise ContractError(f"run not found for question: {run_id}")

                run_status = run_row[8]
                current_step_id = run_row[9]
                if run_status != RunStatus.NEED_USER.value:
                    raise ContractError(f"run is not waiting for user input: {run_status}")
                if current_step_id != blocked_step:
                    raise ContractError(
                        f"resume step mismatch: run is at {current_step_id}, question blocked {blocked_step}"
                    )

                spec = pipeline_spec_from_dict(run_row[15])
                if spec.version <= 0:
                    raise ContractError("invalid pipeline spec version")

                context = execution_context_from_dict(run_row[10])
                answers = context.variables.setdefault("user_answers", {})
                answers[current_step_id] = dict(answer)
                expected_revision = int(run_row[14])
                new_revision = expected_revision + 1

                update_run_cursor = await connection.execute(
                    """
                    UPDATE runs
                    SET status = 'RUNNING',
                        context = %s,
                        revision = %s,
                        updated_at = now()
                    WHERE run_id = %s AND revision = %s
                    RETURNING revision
                    """,
                    (
                        Jsonb(execution_context_to_dict(context)),
                        new_revision,
                        run_id,
                        expected_revision,
                    ),
                )
                updated_row = await update_run_cursor.fetchone()
                if updated_row is None:
                    raise RunConflictError(
                        f"run {run_id} revision conflict during atomic resume (expected {expected_revision})"
                    )

                await connection.execute(
                    """
                    UPDATE user_questions
                    SET status = 'answered',
                        answer = %s,
                        answered_at = now()
                    WHERE resume_token_hash = %s
                    """,
                    (Jsonb(dict(answer)), token_hash),
                )

                return RunRecord(
                    run_id=run_row[0],
                    spec=spec,
                    context=context,
                    current_step_id=current_step_id,
                    outputs=dict(run_row[11] or {}),
                    attempts=dict(run_row[12] or {}),
                    status=RunStatus.RUNNING,
                    question=None,
                    error=run_row[13],
                    revision=new_revision,
                )

    atomic_resume = resume_run

    async def atomic_outbox_transaction(
        self,
        intent: DeliveryRecord,
        domain_action: Any,
    ) -> tuple[Any, DeliveryRecord]:
        """S0-00B3-01: True atomic PostgreSQL application transaction + delivery outbox intent."""
        async with self.pool.connection() as connection:
            async with connection.transaction():
                domain_result = await domain_action(connection)
                await connection.execute(
                    """
                    INSERT INTO delivery_records
                        (delivery_id, kind, subject_refs, destination_adapter,
                         idempotency_key, idempotency_scope, retention_class, valid_until,
                         payload, status, attempts, max_attempts, revision,
                         last_error, next_attempt_at, delivered_at, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_key) DO UPDATE SET
                        updated_at = now()
                    """,
                    (
                        str(intent.delivery_id),
                        intent.kind.value,
                        Jsonb(intent.subject_refs),
                        intent.destination_adapter,
                        intent.idempotency_key,
                        intent.idempotency_scope,
                        intent.retention_class,
                        intent.valid_until,
                        Jsonb(intent.payload),
                        intent.status.value,
                        intent.attempts,
                        intent.max_attempts,
                        intent.revision,
                        Jsonb(_jsonable(intent.last_error)) if intent.last_error else None,
                        intent.next_attempt_at,
                        intent.delivered_at,
                        intent.created_at,
                        intent.updated_at,
                    ),
                )
                return domain_result, intent

    async def get_delivery(self, delivery_id: str) -> DeliveryRecord | None:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT delivery_id, kind, subject_refs, destination_adapter,
                       idempotency_key, idempotency_scope, retention_class, valid_until,
                       payload, status, attempts, max_attempts, revision,
                       last_error, next_attempt_at, delivered_at, created_at, updated_at
                FROM delivery_records
                WHERE delivery_id = %s
                """,
                (delivery_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return DeliveryRecord(
                delivery_id=DeliveryId(row[0]),
                kind=DeliveryKind(row[1]),
                subject_refs=dict(row[2] or {}),
                destination_adapter=row[3],
                idempotency_key=row[4],
                idempotency_scope=row[5],
                retention_class=row[6],
                valid_until=row[7],
                payload=dict(row[8] or {}),
                status=DeliveryStatus(row[9]),
                attempts=row[10],
                max_attempts=row[11],
                revision=row[12],
                last_error=None,
                next_attempt_at=row[14],
                delivered_at=row[15],
                created_at=row[16],
                updated_at=row[17],
            )



class PostgresEventSink:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    async def append(self, event: Event) -> None:
        async with self.store.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO events
                    (event_id, occurred_at, user_id, project_id, session_id, trace_id,
                     run_id, actor, type, parent_event_id, input_ref, output_ref,
                     artifact_refs, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.event_id,
                    event.occurred_at,
                    event.user_id,
                    event.project_id,
                    event.session_id,
                    event.trace_id,
                    event.run_id,
                    event.actor.value,
                    event.type,
                    event.parent_event_id,
                    event.input_ref,
                    event.output_ref,
                    Jsonb(list(event.artifact_refs)),
                    Jsonb(_jsonable(event.metadata)),
                ),
            )
