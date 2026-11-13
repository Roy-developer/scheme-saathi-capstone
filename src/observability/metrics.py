"""OpenTelemetry metrics for Scheme Saathi (L13/L16 monitoring).

Maps to the Monitoring & Evaluation guide panels: questions, can't-tell /
need_more_information rate, pending approvals, masked-ID hits, cost, plus
latency and guardrail blocks. Instruments are exported through the OTel
meter provider (Azure Monitor / Application Insights, see telemetry.py) and
are visualised in Managed Grafana from there.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from opentelemetry import metrics as otel_metrics
import hashlib
from collections import OrderedDict
from opentelemetry import trace as otel_trace
from opentelemetry.trace import Span


METER_NAME = "scheme_saathi"

# Pending approvals are an up/down counter in OTel, which cannot be read back.
# Track the open count in-process so resolves never push the value below zero
# (for example after a restart, when the count starts again at 0).
_pending_approvals_open = 0


@dataclass(frozen=True)
class OTelInstruments:
    conversations: otel_metrics.Counter
    evaluations: otel_metrics.Counter
    verdicts: otel_metrics.Counter
    questions: otel_metrics.Counter
    masked_id_hits: otel_metrics.Counter
    pending_approvals: otel_metrics.UpDownCounter
    cost_usd: otel_metrics.Histogram
    tokens: otel_metrics.Counter
    llm_call_seconds: otel_metrics.Histogram
    request_latency: otel_metrics.Histogram
    guardrail_blocks: otel_metrics.Counter


def create_otel_instruments(meter: otel_metrics.Meter) -> OTelInstruments:
    return OTelInstruments(
        conversations=meter.create_counter(
            "scheme_saathi.conversations",
            description="Journey conversations started or resumed",
        ),
        evaluations=meter.create_counter(
            "scheme_saathi.evaluations",
            description="Eligibility evaluations completed",
        ),
        verdicts=meter.create_counter(
            "scheme_saathi.verdicts",
            description="Eligibility verdict results",
        ),
        questions=meter.create_counter(
            "scheme_saathi.questions",
            description="Interview questions returned to the user",
        ),
        masked_id_hits=meter.create_counter(
            "scheme_saathi.masked_id_hits",
            description="Identifier strings masked before model or trace use",
        ),
        pending_approvals=meter.create_up_down_counter(
            "scheme_saathi.pending_approvals",
            description="Mock application forms waiting for citizen approval",
        ),
        cost_usd=meter.create_histogram(
            "scheme_saathi.cost_usd",
            unit="USD",
            description="Estimated USD cost attributed to LLM usage",
        ),
        tokens=meter.create_counter(
            "scheme_saathi.tokens",
            description="Tokens consumed across LLM calls",
        ),
        llm_call_seconds=meter.create_histogram(
            "scheme_saathi.llm_call_duration",
            unit="s",
            description="Wall-clock seconds per LLM call",
        ),
        request_latency=meter.create_histogram(
            "scheme_saathi.request_latency",
            unit="s",
            description="Latency for evaluate and journey HTTP handlers",
        ),
        guardrail_blocks=meter.create_counter(
            "scheme_saathi.guardrail_blocks",
            description="Inputs flagged or blocked by an input guardrail",
        ),
    )


_otel_instruments = create_otel_instruments(otel_metrics.get_meter(METER_NAME))

# Rough OpenRouter-ish defaults; override with env for demos.
_INPUT_USD_PER_1K = float(os.getenv("SCHEME_SAATHI_COST_INPUT_USD_PER_1K", "0.00015"))
_OUTPUT_USD_PER_1K = float(os.getenv("SCHEME_SAATHI_COST_OUTPUT_USD_PER_1K", "0.0006"))


def record_conversation(endpoint: str) -> None:
    _otel_instruments.conversations.add(1, {"endpoint": endpoint})


def record_evaluation(scheme_id: str, source: str = "api") -> None:
    _otel_instruments.evaluations.add(
        1, {"scheme_id": scheme_id, "source": source}
    )


def record_verdict(scheme_id: str, result: str) -> None:
    # Keep UI alias aligned with engine / alert labels.
    if result == "cant_tell":
        result = "need_more_information"
    _otel_instruments.verdicts.add(
        1, {"scheme_id": scheme_id, "result": result}
    )


def record_question(scheme_id: str | None) -> None:
    _otel_instruments.questions.add(
        1, {"scheme_id": scheme_id or "unknown"}
    )


def record_masked_id_hits(count: int = 1, *, field_type: str = "unknown") -> None:
    if count > 0:
        _otel_instruments.masked_id_hits.add(count, {"field_type": field_type})


def record_pending_approval_created() -> None:
    global _pending_approvals_open
    _pending_approvals_open += 1
    _otel_instruments.pending_approvals.add(1)


def record_pending_approval_resolved() -> None:
    global _pending_approvals_open
    if _pending_approvals_open > 0:
        _pending_approvals_open -= 1
        _otel_instruments.pending_approvals.add(-1)


def record_tokens(model: str, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
    if input_tokens > 0:
        _otel_instruments.tokens.add(
            input_tokens, {"model": model or "unknown", "direction": "input"}
        )
    if output_tokens > 0:
        _otel_instruments.tokens.add(
            output_tokens, {"model": model or "unknown", "direction": "output"}
        )
    cost = (input_tokens / 1000.0) * _INPUT_USD_PER_1K + (
        output_tokens / 1000.0
    ) * _OUTPUT_USD_PER_1K
    if cost > 0:
        _otel_instruments.cost_usd.record(cost)


def record_llm_call(model: str, duration_seconds: float) -> None:
    if duration_seconds >= 0:
        _otel_instruments.llm_call_seconds.record(
            duration_seconds, {"model": model or "unknown"}
        )


def record_guardrail_block(guardrail: str, reason: str = "flagged") -> None:
    _otel_instruments.guardrail_blocks.add(
        1, {"guardrail": guardrail, "reason": reason}
    )


@contextmanager
def observe_duration(endpoint: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - started
        _otel_instruments.request_latency.record(elapsed, {"endpoint": endpoint})


# --- Phase 6: once-per-conversation verdicts and privacy-safe spans ----------

_MAX_COUNTED_VERDICTS = 10_000
_counted_verdicts: "OrderedDict[tuple[str, str], str]" = OrderedDict()
_tracer = otel_trace.get_tracer(METER_NAME)


def correlation_id(raw: str) -> str:
    """Hash an identifier so traces can be joined without the raw value."""

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def record_journey_verdict(conversation_id: str, scheme_id: str, result: str) -> None:
    """Count a journey verdict once per conversation, scheme and verdict value.

    Journey turns re-evaluate every scheme, so counting each turn would inflate
    the can't-tell rate. A verdict is counted again only when it changes.
    """

    normalized = "need_more_information" if result == "cant_tell" else result
    key = (correlation_id(conversation_id), scheme_id)
    if _counted_verdicts.get(key) == normalized:
        return
    _counted_verdicts[key] = normalized
    _counted_verdicts.move_to_end(key)
    while len(_counted_verdicts) > _MAX_COUNTED_VERDICTS:
        _counted_verdicts.popitem(last=False)
    record_verdict(scheme_id, normalized)


@contextmanager
def model_span(agent: str, model: str, step: int) -> Iterator[Span]:
    """Trace one model call. Prompts and responses are never attached."""

    with _tracer.start_as_current_span(
        "model_call", attributes={"agent": agent, "model": model, "step": step},
    ) as span:
        yield span


@contextmanager
def tool_span(actor: str, tool: str, journey_id: str) -> Iterator[Span]:
    """Trace one tool call. Arguments are never attached; the journey is hashed."""

    with _tracer.start_as_current_span(
        "tool_call",
        attributes={"actor": actor, "tool": tool, "journey": correlation_id(journey_id)},
    ) as span:
        yield span
