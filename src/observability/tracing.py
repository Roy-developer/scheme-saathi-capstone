"""Privacy-safe OpenTelemetry spans for model and tool calls, and correlation IDs.

Spans come from the global tracer provider (see ``src.observability.telemetry``).
Without a provider they are no-ops, so offline runs need no backend.

Only the attributes in ``SPAN_ATTRIBUTES`` are ever set. Prompts, reply text,
household values and raw identifiers are never passed in, and any other key
offered to ``record_call_span`` is dropped.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from opentelemetry import trace

TRACER_NAME = "scheme_saathi"
CORRELATION_ATTRIBUTE = "scheme_saathi.correlation_id"
CORRELATION_DIGEST_LENGTH = 16

SPAN_ATTRIBUTES = frozenset({
    "agent",
    "action",
    "status",
    "model",
    "step",
    "duration_ms",
    "input_tokens",
    "output_tokens",
})


def correlation_id(conversation_id: str) -> str:
    """Return a stable, non-reversible ID for one conversation.

    The same conversation id always gives the same value; the raw id is never
    returned, so it cannot leak into spans or metric labels.
    """

    digest = hashlib.sha256(str(conversation_id).encode("utf-8")).hexdigest()
    return digest[:CORRELATION_DIGEST_LENGTH]


def record_call_span(
    kind: str,
    fields: Mapping[str, object],
    *,
    correlation: str | None = None,
) -> None:
    """Emit one finished span for a ``model`` or ``tool`` call.

    ``fields`` may hold any trace-event values; only the allowed attributes
    are copied, and ``None`` values are skipped.
    """

    tracer = trace.get_tracer(TRACER_NAME)
    attributes: dict[str, object] = {
        key: value
        for key, value in fields.items()
        if key in SPAN_ATTRIBUTES and value is not None
    }
    if correlation:
        attributes[CORRELATION_ATTRIBUTE] = correlation
    with tracer.start_as_current_span(f"saathi.{kind}_call", attributes=attributes):
        pass
