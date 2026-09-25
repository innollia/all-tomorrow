"""OpenTelemetry tracing verification fixture for 00A-1 Common Harness.

Integrates real OpenTelemetry SDK with InMemorySpanExporter to verify that
correlation tokens survive crash/recovery cycles at the telemetry layer.
"""

from __future__ import annotations

from typing import List, Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class HarnessTelemetry:
    """Manages OpenTelemetry tracing and span capture for walking skeleton experiments."""

    def __init__(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("all_tomorrow.harness")

    def record_span(self, name: str, correlation_id: str, attributes: Optional[dict] = None) -> None:
        """Create a finished span with the given correlation_id attribute."""
        attrs = attributes or {}
        attrs["all_tomorrow.correlation_id"] = correlation_id
        with self.tracer.start_as_current_span(name, attributes=attrs) as span:
            span.set_attribute("all_tomorrow.correlation_id", correlation_id)

    def get_correlation_ids_from_spans(self) -> List[str]:
        """Inspect all exported spans and extract their correlation ID attributes."""
        spans = self.exporter.get_finished_spans()
        corrs = []
        for s in spans:
            corr = s.attributes.get("all_tomorrow.correlation_id") if s.attributes else None
            if corr:
                corrs.append(str(corr))
        return corrs

    def reset(self) -> None:
        """Clear captured spans."""
        self.exporter.clear()
