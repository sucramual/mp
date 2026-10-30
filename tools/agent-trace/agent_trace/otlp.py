"""IDs, TRACEPARENT parsing, and OTLP JSON encoding and decoding.

The stored record shape (one JSON object per line) is the same for collect and for the fallback file:

  {"type": "span", "service", "traceId", "spanId", "parentSpanId" (or null), "name", "start", "end" (ns ints),
   "status": {"code", "message"}, "attrs": {flat key: value}, "events": [{"name", "time", "attrs"}]}
  {"type": "log", "service", "time", "traceId", "spanId", "attrs"}

OTLP AnyValue flattening: string, bool, and double values stay as they are; intValue becomes an int (OTLP JSON
sends it as a string); arrayValue becomes a list; kvlistValue becomes a dict.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from typing import Any

TRACEPARENT = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
STATUS_NAMES = {"STATUS_CODE_UNSET": 0, "STATUS_CODE_OK": 1, "STATUS_CODE_ERROR": 2}

Record = dict[str, Any]


def now_ns() -> int:
    return time.time_ns()


def span_id_for(scope: str, ident: str) -> str:
    """The span ID of agent span ``ident`` in ``scope``: the first 16 hex of sha256(scope NUL id)."""
    return hashlib.sha256(f"{scope}\0{ident}".encode()).hexdigest()[:16]


def trace_id_for(scope: str) -> str:
    """The trace ID of a scope when no TRACEPARENT is given."""
    return hashlib.sha256(f"agent-trace\0{scope}".encode()).hexdigest()[:32]


def random_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(value: str | None) -> tuple[str, str] | None:
    """Return (trace id, span id) from a W3C TRACEPARENT value, or None when it is absent or malformed."""
    match = TRACEPARENT.match((value or "").strip().lower())
    if not match or set(match.group(1)) == {"0"} or set(match.group(2)) == {"0"}:
        return None
    return match.group(1), match.group(2)


def flatten_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return value["boolValue"]
    if "intValue" in value:
        try:
            return int(value["intValue"])
        except (TypeError, ValueError):
            return value["intValue"]
    if "doubleValue" in value:
        return value["doubleValue"]
    if "arrayValue" in value:
        return [flatten_value(item) for item in (value["arrayValue"] or {}).get("values", []) or []]
    if "kvlistValue" in value:
        return flatten_attrs((value["kvlistValue"] or {}).get("values", []))
    if "bytesValue" in value:
        return value["bytesValue"]
    return None


def flatten_attrs(attributes: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in attributes or []:
        if isinstance(item, dict) and isinstance(item.get("key"), str):
            out[item["key"]] = flatten_value(item.get("value"))
    return out


def encode_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list | tuple):
        return {"arrayValue": {"values": [encode_value(item) for item in value]}}
    if isinstance(value, dict):
        return {"kvlistValue": {"values": encode_attrs(value)}}
    return {"stringValue": "" if value is None else str(value)}


def encode_attrs(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": key, "value": encode_value(value)} for key, value in attrs.items() if value is not None]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _status(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    code = value.get("code", 0)
    code = STATUS_NAMES.get(code, 0) if isinstance(code, str) and not code.isdigit() else _int(code)
    return {"code": code, "message": str(value.get("message") or "")}


def _service(block: dict[str, Any]) -> str:
    resource = block.get("resource") if isinstance(block.get("resource"), dict) else {}
    return str(flatten_attrs((resource or {}).get("attributes")).get("service.name") or "")


def _blocks(doc: Any, key: str) -> list[dict[str, Any]]:
    blocks = doc.get(key) if isinstance(doc, dict) else None
    return [block for block in blocks or [] if isinstance(block, dict)] if isinstance(blocks, list) else []


def decode_traces(doc: Any) -> list[Record]:
    """Flatten an OTLP JSON ExportTraceServiceRequest into span records."""
    records: list[Record] = []
    for block in _blocks(doc, "resourceSpans"):
        service = _service(block)
        for scope in block.get("scopeSpans") or []:
            for span in (scope or {}).get("spans") or []:
                if not isinstance(span, dict):
                    continue
                records.append(
                    {
                        "type": "span",
                        "service": service,
                        "traceId": str(span.get("traceId") or ""),
                        "spanId": str(span.get("spanId") or ""),
                        "parentSpanId": span.get("parentSpanId") or None,
                        "name": str(span.get("name") or ""),
                        "start": _int(span.get("startTimeUnixNano")),
                        "end": _int(span.get("endTimeUnixNano")),
                        "status": _status(span.get("status")),
                        "attrs": flatten_attrs(span.get("attributes")),
                        "events": [
                            {
                                "name": str(event.get("name") or ""),
                                "time": _int(event.get("timeUnixNano")),
                                "attrs": flatten_attrs(event.get("attributes")),
                            }
                            for event in span.get("events") or []
                            if isinstance(event, dict)
                        ],
                    }
                )
    return records


def decode_logs(doc: Any) -> list[Record]:
    """Flatten an OTLP JSON ExportLogsServiceRequest into log records. The body is dropped (it may hold prompts)."""
    records: list[Record] = []
    for block in _blocks(doc, "resourceLogs"):
        service = _service(block)
        for scope in block.get("scopeLogs") or []:
            for log in (scope or {}).get("logRecords") or []:
                if not isinstance(log, dict):
                    continue
                records.append(
                    {
                        "type": "log",
                        "service": service,
                        "time": _int(log.get("timeUnixNano")) or _int(log.get("observedTimeUnixNano")),
                        "traceId": str(log.get("traceId") or ""),
                        "spanId": str(log.get("spanId") or ""),
                        "attrs": flatten_attrs(log.get("attributes")),
                    }
                )
    return records


def _by_service(records: list[Record]) -> dict[str, list[Record]]:
    groups: dict[str, list[Record]] = {}
    for record in records:
        groups.setdefault(record.get("service") or "unknown", []).append(record)
    return groups


def _resource(service: str) -> dict[str, Any]:
    return {"attributes": encode_attrs({"service.name": service})}


def encode_span(record: Record) -> dict[str, Any]:
    span: dict[str, Any] = {
        "traceId": record["traceId"],
        "spanId": record["spanId"],
        "name": record["name"],
        "kind": 1,
        "startTimeUnixNano": str(record["start"]),
        "endTimeUnixNano": str(record["end"]),
        "attributes": encode_attrs(record.get("attrs") or {}),
        "status": dict(record.get("status") or {"code": 0}),
        "events": [
            {
                "name": event["name"],
                "timeUnixNano": str(event["time"]),
                "attributes": encode_attrs(event.get("attrs") or {}),
            }
            for event in record.get("events") or []
        ],
    }
    if record.get("parentSpanId"):
        span["parentSpanId"] = record["parentSpanId"]
    return span


def encode_traces(records: list[Record]) -> dict[str, Any]:
    """Encode span records as one OTLP JSON ExportTraceServiceRequest, one resource per service."""
    return {
        "resourceSpans": [
            {
                "resource": _resource(service),
                "scopeSpans": [{"scope": {"name": "agent-trace"}, "spans": [encode_span(r) for r in group]}],
            }
            for service, group in _by_service(records).items()
        ]
    }


def encode_logs(records: list[Record]) -> dict[str, Any]:
    return {
        "resourceLogs": [
            {
                "resource": _resource(service),
                "scopeLogs": [
                    {
                        "scope": {"name": "agent-trace"},
                        "logRecords": [
                            {
                                "timeUnixNano": str(r["time"]),
                                "traceId": r.get("traceId") or "",
                                "spanId": r.get("spanId") or "",
                                "attributes": encode_attrs(r.get("attrs") or {}),
                            }
                            for r in group
                        ],
                    }
                ],
            }
            for service, group in _by_service(records).items()
        ]
    }
