"""Minimal real OpenTelemetry exporter for cross-process spike assertions."""

import json
import os
from pathlib import Path

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context


class JsonLineSpanExporter(SpanExporter):
    def __init__(self, path: str):
        self.path = Path(path)

    def export(self, spans):
        with self.path.open("a", encoding="utf-8") as stream:
            for span in spans:
                stream.write(
                    json.dumps(
                        {
                            "name": span.name,
                            "pid": os.getpid(),
                            "trace_id": format(span.context.trace_id, "032x"),
                            "span_id": format(span.context.span_id, "016x"),
                            "parent_id": format(span.parent.span_id, "016x") if span.parent else None,
                            "attributes": dict(span.attributes),
                        }
                    ) + "\n"
                )
        return SpanExportResult.SUCCESS


def provider_for(path: str):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(JsonLineSpanExporter(path)))
    return provider


def tracer_for(path: str):
    provider = provider_for(path)
    return provider.get_tracer("all-tomorrow-00a-upgrade-probe")


def persisted_context(trace):
    """Restore the parent carried in durable input, independent of the caller."""
    parent = SpanContext(
        trace_id=int(trace.trace_id, 16), span_id=int(trace.span_id, 16),
        is_remote=True, trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    assert parent.is_valid, "Durable trace context must contain valid W3C IDs"
    return set_span_in_context(NonRecordingSpan(parent))
