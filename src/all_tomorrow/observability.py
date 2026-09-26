"""OpenTelemetry observability and privacy seam for All Tomorrow (Stage 00D).

Guarantees:
- Single TracerProvider per process.
- End-to-end trace correlation: goal_id, work_id, run_id, trace_id, execution_id.
- Privacy defaults: raw prompt/tool payload/secret capture strictly OFF by default.
- Redaction of sensitive values and secret patterns in span attributes and error logs.
- Clean span topology without duplicated trace trees for MCP/tool calls.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Span, SpanContext, TraceFlags, set_span_in_context, NonRecordingSpan


SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{10,}", re.IGNORECASE),
    re.compile(r"(secret|canary|token|key|password|bearer)[a-zA-Z0-9_\-\:]{6,}", re.IGNORECASE),
]

FORBIDDEN_CONTENT_KEYS = {
    "raw_prompt",
    "prompt",
    "tool_payload",
    "raw_payload",
    "raw_content",
    "raw_result",
    "tool_args",
    "secret",
}


def redact_secret_string(value: str) -> str:
    """Scrub secret-like substrings from error logs and attributes."""
    scrubbed = value
    for pattern in SECRET_PATTERNS:
        scrubbed = pattern.sub("[REDACTED_SECRET]", scrubbed)
    return scrubbed


def sanitize_attributes(
    attrs: dict[str, Any],
    *,
    capture_content: bool = False,
) -> dict[str, Any]:
    """Apply production privacy defaults: strip forbidden keys and scrub secrets."""
    sanitized: dict[str, Any] = {}
    for k, v in attrs.items():
        k_lower = k.lower()
        if not capture_content and any(forbidden in k_lower for forbidden in FORBIDDEN_CONTENT_KEYS):
            # OTel attribute raw content is forbidden by default
            continue

        if isinstance(v, str):
            v_clean = redact_secret_string(v)
            sanitized[k] = v_clean
        elif isinstance(v, (int, float, bool)):
            sanitized[k] = v
        elif isinstance(v, (list, tuple)):
            sanitized[k] = [
                redact_secret_string(str(item)) if isinstance(item, str) else item
                for item in v
            ]
        elif isinstance(v, dict):
            # serialize simple dict without secrets
            s_dict = {
                dk: redact_secret_string(str(dv)) if isinstance(dv, str) else dv
                for dk, dv in v.items()
                if not (not capture_content and any(f in dk.lower() for f in FORBIDDEN_CONTENT_KEYS))
            }
            sanitized[k] = json.dumps(s_dict, default=str)
        else:
            sanitized[k] = redact_secret_string(str(v))
    return sanitized


class JsonLineSpanExporter(SpanExporter):
    """Exports finished spans as newline-delimited JSON for multi-process inspection."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
                            "attributes": dict(span.attributes or {}),
                        }
                    )
                    + "\n"
                )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


@dataclass
class CorrelationContext:
    goal_id: str
    work_id: str
    run_id: str
    trace_id: str
    execution_id: Optional[str] = None
    tool_ref: Optional[str] = None
    artifact_ref: Optional[str] = None

    def as_attributes(self) -> dict[str, Any]:
        attrs = {
            "all_tomorrow.goal_id": self.goal_id,
            "all_tomorrow.work_id": self.work_id,
            "all_tomorrow.run_id": self.run_id,
            "all_tomorrow.trace_id": self.trace_id,
        }
        if self.execution_id:
            attrs["all_tomorrow.execution_id"] = self.execution_id
        if self.tool_ref:
            attrs["all_tomorrow.tool_ref"] = self.tool_ref
        if self.artifact_ref:
            attrs["all_tomorrow.artifact_ref"] = self.artifact_ref
        return attrs


class TelemetryManager:
    """Manages process-wide TracerProvider and provides high-level domain tracing."""

    _instance: Optional[TelemetryManager] = None

    def __init__(self, span_file: Optional[Path | str] = None, *, in_memory: bool = True):
        self.provider = TracerProvider()
        self.in_memory_exporter = InMemorySpanExporter() if in_memory else None
        if self.in_memory_exporter:
            self.provider.add_span_processor(SimpleSpanProcessor(self.in_memory_exporter))

        self.file_exporter = JsonLineSpanExporter(span_file) if span_file else None
        if self.file_exporter:
            self.provider.add_span_processor(SimpleSpanProcessor(self.file_exporter))

        self.tracer = self.provider.get_tracer("all_tomorrow.observability")
        self.capture_content = False

    @classmethod
    def get_or_create(cls, span_file: Optional[Path | str] = None) -> TelemetryManager:
        if cls._instance is None:
            cls._instance = cls(span_file=span_file)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def start_root_span(
        self,
        name: str,
        context: CorrelationContext,
        extra_attributes: Optional[dict[str, Any]] = None,
    ) -> Span:
        attrs = context.as_attributes()
        if extra_attributes:
            attrs.update(extra_attributes)
        clean_attrs = sanitize_attributes(attrs, capture_content=self.capture_content)
        span = self.tracer.start_span(name, attributes=clean_attrs)
        return span

    def start_child_span(
        self,
        name: str,
        parent_span: Optional[Span] = None,
        context: Optional[CorrelationContext] = None,
        extra_attributes: Optional[dict[str, Any]] = None,
    ) -> Span:
        attrs = context.as_attributes() if context else {}
        if extra_attributes:
            attrs.update(extra_attributes)
        clean_attrs = sanitize_attributes(attrs, capture_content=self.capture_content)

        trace_ctx = None
        if parent_span:
            trace_ctx = set_span_in_context(parent_span)

        span = self.tracer.start_span(name, context=trace_ctx, attributes=clean_attrs)
        return span

    def get_finished_spans(self) -> list[ReadableSpan]:
        if self.in_memory_exporter:
            return self.in_memory_exporter.get_finished_spans()
        return []

    def clear(self) -> None:
        if self.in_memory_exporter:
            self.in_memory_exporter.clear()
