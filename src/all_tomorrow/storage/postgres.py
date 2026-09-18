from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from all_tomorrow.contracts import Event, PipelineSpec, Project, UserQuestion, new_id


def hash_resume_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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

    async def publish_pipeline(self, spec: PipelineSpec, raw_spec: dict[str, Any]) -> None:
        async with self.pool.connection() as connection:
            async with connection.transaction():
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
                        Jsonb(raw_spec),
                    ),
                )

    async def create_run(self, snapshot: dict[str, Any]) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO runs
                    (run_id, request_id, trace_id, user_id, project_id, session_id,
                     pipeline_id, pipeline_version, status, current_step_id,
                     context, outputs, attempts, error)
                VALUES
                    (%(run_id)s, %(request_id)s, %(trace_id)s, %(user_id)s, %(project_id)s,
                     %(session_id)s, %(pipeline_id)s, %(pipeline_version)s, %(status)s,
                     %(current_step_id)s, %(context)s, %(outputs)s, %(attempts)s, %(error)s)
                """,
                {
                    **snapshot,
                    "context": Jsonb(snapshot["context"]),
                    "outputs": Jsonb(snapshot.get("outputs", {})),
                    "attempts": Jsonb(snapshot.get("attempts", {})),
                },
            )

    async def update_run(self, run_id: str, expected_revision: int, changes: dict[str, Any]) -> int:
        allowed = {"status", "current_step_id", "context", "outputs", "attempts", "error"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported run fields: {', '.join(sorted(unknown))}")
        if not changes:
            return expected_revision
        assignments: list[str] = []
        params: list[Any] = []
        for name, value in changes.items():
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
            raise RuntimeError("run update conflict or missing run")
        return int(row[0])

    async def create_question(self, run_id: str, question: UserQuestion) -> str:
        if question.resume_token is None:
            raise ValueError("question requires a resume token before persistence")
        question_id = new_id("question")
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO user_questions
                    (question_id, run_id, blocked_step, question, reason,
                     required_fields, resume_token_hash, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    question_id,
                    run_id,
                    question.blocked_step,
                    question.question,
                    question.reason,
                    Jsonb(list(question.required_fields)),
                    hash_resume_token(question.resume_token),
                ),
            )
        return question_id

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

