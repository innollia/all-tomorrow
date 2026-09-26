"""Candidate-neutral input and external mutation seam for live D01 probes."""

import psycopg
import os

from all_tomorrow.harness.types import HarnessInput
from .otel_file_exporter import persisted_context
from contextlib import contextmanager
from opentelemetry.context import attach, detach


def model_agent():
    if os.environ.get("AT_TEST_MODEL_URL"):
        from .gateway_agent import create_gateway_agent
        return create_gateway_agent()
    from all_tomorrow.harness.agent import create_deterministic_agent
    return create_deterministic_agent()


@contextmanager
def model_context(trace):
    token = attach(persisted_context(trace))
    try:
        yield
    finally:
        detach(token)


def transient_model_error(error):
    from openai import APIConnectionError, APIStatusError
    from pydantic_ai.exceptions import ModelHTTPError
    if isinstance(error, APIConnectionError):
        return True
    if isinstance(error, (APIStatusError, ModelHTTPError)):
        return error.status_code in (429, 500, 502, 503, 504)
    return False


def observe_model(fixture_url: str, data: HarnessInput) -> None:
    with psycopg.connect(fixture_url) as conn:
        conn.execute(
            "INSERT INTO common_model_probe (idempotency_key, calls) VALUES (%s, 1) "
            "ON CONFLICT (idempotency_key) DO UPDATE SET calls=common_model_probe.calls+1",
            (data.mutation_key,),
        )


def emit_trace(tracer, trace, name: str) -> None:
    if tracer:
        with tracer.start_as_current_span(name, context=persisted_context(trace)) as span:
            import pydantic_ai
            span.set_attribute("all_tomorrow.correlation_id", trace.correlation_id)
            span.set_attribute("pydantic_ai.version", pydantic_ai.__version__)


def record_followup(fixture_url, key):
    with psycopg.connect(fixture_url) as conn:
        conn.execute("INSERT INTO common_followup_probe (idempotency_key) VALUES (%s) ON CONFLICT DO NOTHING", (key,))


def crash_at(data, point, code, tracer, trace):
    if data.injected_fail_point == point and os.environ.get("AT_TEST_COMMON_PHASE") == "crash":
        emit_trace(tracer, trace, f"injected_{point.value}")
        os._exit(code)


def apply_mutation(fixture_url: str, data: HarnessInput) -> str:
    with psycopg.connect(fixture_url) as conn:
        row = conn.execute(
            """INSERT INTO common_mutation_probe (idempotency_key, call_count, application_count, committed_value)
               VALUES (%s, 1, 1, %s)
               ON CONFLICT (idempotency_key) DO UPDATE
               SET call_count=common_mutation_probe.call_count+1
               RETURNING committed_value""",
            (data.mutation_key, data.mutation_value),
        ).fetchone()
        conn.commit()
    return row[0]
