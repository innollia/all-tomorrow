"""Durable external mutation fixture backed by PostgreSQL or local state.

Records:
- idempotency_key
- invocation_count
- applied_effect_count
- committed_value
- first_request_id
- last_request_id
"""
from __future__ import annotations

import os
from typing import Any
import psycopg


class DurableExternalMutationFixture:
    def __init__(self, fixture_url: str | None = None) -> None:
        self.fixture_url = fixture_url or os.environ.get("AT_TEST_FIXTURE_URL")
        self._in_memory: dict[str, dict[str, Any]] = {}
        if self.fixture_url:
            self._init_db()

    def _init_db(self) -> None:
        with psycopg.connect(self.fixture_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.walking_skeleton_mutation_probe (
                        idempotency_key TEXT PRIMARY KEY,
                        invocation_count INTEGER NOT NULL DEFAULT 0,
                        applied_effect_count INTEGER NOT NULL DEFAULT 0,
                        committed_value TEXT NOT NULL,
                        first_request_id TEXT NOT NULL,
                        last_request_id TEXT NOT NULL
                    )
                    """
                )
            conn.commit()

    def apply_mutation(
        self,
        idempotency_key: str,
        value: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Applies mutation idempotently."""
        if not self.fixture_url:
            if idempotency_key not in self._in_memory:
                self._in_memory[idempotency_key] = {
                    "idempotency_key": idempotency_key,
                    "invocation_count": 1,
                    "applied_effect_count": 1,
                    "committed_value": value,
                    "first_request_id": request_id,
                    "last_request_id": request_id,
                }
            else:
                record = self._in_memory[idempotency_key]
                record["invocation_count"] += 1
                record["last_request_id"] = request_id
            return dict(self._in_memory[idempotency_key])

        with psycopg.connect(self.fixture_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.walking_skeleton_mutation_probe (
                        idempotency_key, invocation_count, applied_effect_count,
                        committed_value, first_request_id, last_request_id
                    )
                    VALUES (%s, 1, 1, %s, %s, %s)
                    ON CONFLICT (idempotency_key) DO UPDATE SET
                        invocation_count = walking_skeleton_mutation_probe.invocation_count + 1,
                        last_request_id = EXCLUDED.last_request_id
                    RETURNING idempotency_key, invocation_count, applied_effect_count,
                              committed_value, first_request_id, last_request_id
                    """,
                    (idempotency_key, value, request_id, request_id),
                )
                row = cur.fetchone()
            conn.commit()

        return {
            "idempotency_key": row[0],
            "invocation_count": row[1],
            "applied_effect_count": row[2],
            "committed_value": row[3],
            "first_request_id": row[4],
            "last_request_id": row[5],
        }

    def get_record(self, idempotency_key: str) -> dict[str, Any] | None:
        if not self.fixture_url:
            record = self._in_memory.get(idempotency_key)
            return dict(record) if record else None

        with psycopg.connect(self.fixture_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT idempotency_key, invocation_count, applied_effect_count,
                           committed_value, first_request_id, last_request_id
                    FROM public.walking_skeleton_mutation_probe
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "idempotency_key": row[0],
            "invocation_count": row[1],
            "applied_effect_count": row[2],
            "committed_value": row[3],
            "first_request_id": row[4],
            "last_request_id": row[5],
        }
