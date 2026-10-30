# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "opentelemetry-sdk==1.45.2",
#   "opentelemetry-exporter-otlp-proto-http==1.45.2",
# ]
# ///
"""Build and send agent-trace spans with the OpenTelemetry SDK. Run by launch.py as `uv run --script export.py`.

Reads one JSON send request on stdin:
  {"time": ns, "trace_id": hex (scope hash), "endpoint": base URL, "fallback": path,
   "spans": [{"name", "span_id": hex or null (null: random), "parent_span_id": hex or null, "attrs",
              "error": bool, "event": name or null}]}

A custom IdGenerator gives the SDK the deterministic ids. The parent comes from --parent (parent_span_id), else
from TRACEPARENT through the W3C trace-context propagator. Every span is zero length at `time`.

The spans go to <endpoint>/v1/traces through OTLPSpanExporter (timeout 1 s), called directly so the result is
known. They count as delivered only when the export succeeds and the answer carries `X-Agent-Trace` (collect, not
Jaeger). Otherwise they are flattened like collect does and appended to the fallback file.

Prints one JSON line: {"sent": true}, or {"sent": false, "fallback": path}. The SDK's own logging is silenced, and
every OTEL_* variable is ignored, so the agent's own telemetry settings cannot change or disable these spans.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

for _name in [name for name in os.environ if name.startswith("OTEL_")]:
    del os.environ[_name]

if __package__ in (None, ""):
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

import requests  # noqa: E402
from google.protobuf.json_format import MessageToDict  # noqa: E402
from opentelemetry import context as otel_context  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans  # noqa: E402
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # noqa: E402
from opentelemetry.sdk.resources import Resource  # noqa: E402
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402
from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator  # noqa: E402
from opentelemetry.sdk.trace.sampling import ALWAYS_ON  # noqa: E402
from opentelemetry.trace import NonRecordingSpan, SpanContext, Status, StatusCode, TraceFlags  # noqa: E402
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator  # noqa: E402

# ty checks a PEP 723 script against its own dependencies only, so it cannot see this package. Import the local
# standard-library modules by name instead.
otlp = importlib.import_module("agent_trace.otlp")
store = importlib.import_module("agent_trace.store")

HEADER = "X-Agent-Trace"


class FixedIds(IdGenerator):
    """Returns the ids that the next span must have; random span ids when none is set."""

    def __init__(self, trace_id: int) -> None:
        self.trace_id = trace_id
        self.span_id: int | None = None
        self.random = RandomIdGenerator()

    def generate_span_id(self) -> int:
        return self.span_id or self.random.generate_span_id()

    def generate_trace_id(self) -> int:
        return self.trace_id


def build_spans(request: dict[str, Any]) -> list[ReadableSpan]:
    ids = FixedIds(int(request["trace_id"], 16))
    memory = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource({"service.name": "agent-trace"}), sampler=ALWAYS_ON, id_generator=ids)
    provider.add_span_processor(SimpleSpanProcessor(memory))
    tracer = provider.get_tracer("agent-trace")
    traceparent = os.environ.get("TRACEPARENT")
    inherited = TraceContextTextMapPropagator().extract({"traceparent": traceparent}) if traceparent else None
    inherited_span = trace.get_current_span(inherited).get_span_context() if inherited else None
    when = int(request["time"])
    for spec in request["spans"]:
        if spec.get("parent_span_id"):
            trace_id = inherited_span.trace_id if inherited_span and inherited_span.is_valid else ids.trace_id
            parent = SpanContext(trace_id, int(spec["parent_span_id"], 16), True, TraceFlags(TraceFlags.SAMPLED))
            ctx = trace.set_span_in_context(NonRecordingSpan(parent))
        else:
            ctx = inherited or otel_context.Context()
        ids.span_id = int(spec["span_id"], 16) if spec.get("span_id") else None
        span = tracer.start_span(spec["name"], context=ctx, attributes=spec["attrs"], start_time=when)
        if spec.get("event"):
            span.add_event(spec["event"], timestamp=when)
        if spec.get("error"):
            span.set_status(Status(StatusCode.ERROR))
        span.end(end_time=when)
    return list(memory.get_finished_spans())


def export(spans: list[ReadableSpan], endpoint: str) -> bool:
    seen: list[bool] = []
    session = requests.Session()
    session.trust_env = False  # No proxies and no netrc for a local receiver.

    def remember(response: requests.Response, *args: Any, **kwargs: Any) -> None:
        seen.append(HEADER in response.headers)

    session.hooks["response"].append(remember)
    exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=1, session=session)
    try:
        result = exporter.export(spans)
    finally:
        exporter.shutdown()
    return result is SpanExportResult.SUCCESS and any(seen)


def flatten(spans: list[ReadableSpan]) -> list[dict[str, Any]]:
    """The same records that collect stores for these spans."""
    doc = otlp.ids_to_hex(MessageToDict(encode_spans(spans)))
    return otlp.decode_traces(doc)


def main() -> int:
    logging.getLogger("opentelemetry").disabled = True
    logging.getLogger("urllib3").disabled = True
    request = json.load(sys.stdin)
    spans = build_spans(request)
    if export(spans, request["endpoint"]):
        print(json.dumps({"sent": True}))
        return 0
    fallback = Path(request["fallback"])
    store.append_records(fallback, flatten(spans))
    print(json.dumps({"sent": False, "fallback": str(fallback)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
