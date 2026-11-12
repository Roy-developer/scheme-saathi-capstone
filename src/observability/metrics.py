"""Prometheus metrics for Scheme Saathi (L13/L16 monitoring).

Maps to the Monitoring & Evaluation guide panels: questions, can't-tell /
need_more_information rate, pending approvals, masked-ID hits, cost, plus
latency and guardrail blocks. Role 6 scrapes GET /metrics.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from opentelemetry import metrics as otel_metrics
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)


REGISTRY = CollectorRegistry()

METER_NAME = "scheme_saathi"


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

# Panel / ops: conversations started
CONVERSATIONS_TOTAL = Counter(
    "scheme_saathi_conversations_total",
    "Journey conversations started or resumed",
    ["endpoint"],
    registry=REGISTRY,
)

EVALUATIONS_TOTAL = Counter(
    "scheme_saathi_evaluations_total",
    "Eligibility evaluations completed",
    ["scheme_id", "source"],
    registry=REGISTRY,
)

# Panel 2 + HighCantTellRate alert (result includes need_more_information)
VERDICTS_TOTAL = Counter(
    "scheme_saathi_verdicts_total",
    "Eligibility verdict results",
    ["scheme_id", "result"],
    registry=REGISTRY,
)

# Panel 1: questions per conversation / scheme
QUESTIONS_TOTAL = Counter(
    "scheme_saathi_questions_total",
    "Interview questions returned to the user",
    ["scheme_id"],
    registry=REGISTRY,
)

# Panel 4: PII masking (by field type when known)
MASKED_ID_HITS_TOTAL = Counter(
    "scheme_saathi_masked_id_hits_total",
    "Identifier strings masked before model or trace use",
    ["field_type"],
    registry=REGISTRY,
)

# Panel 3: forms waiting for citizen approval
PENDING_APPROVALS = Gauge(
    "scheme_saathi_pending_approvals",
    "Mock application forms waiting for citizen approval",
    registry=REGISTRY,
)

# Panel 5: estimated USD cost per conversation turn / call batch
COST_USD = Histogram(
    "scheme_saathi_cost_usd",
    "Estimated USD cost attributed to LLM usage",
    buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.5, 1.0),
    registry=REGISTRY,
)

TOKENS_TOTAL = Counter(
    "scheme_saathi_tokens_total",
    "Tokens consumed across LLM calls",
    ["model", "direction"],
    registry=REGISTRY,
)

LLM_CALL_SECONDS = Histogram(
    "scheme_saathi_llm_call_seconds",
    "Wall-clock seconds per LLM call",
    ["model"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0),
    registry=REGISTRY,
)

REQUEST_LATENCY_SECONDS = Histogram(
    "scheme_saathi_request_latency_seconds",
    "Latency for evaluate and journey HTTP handlers",
    ["endpoint"],
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

GUARDRAIL_BLOCKS_TOTAL = Counter(
    "scheme_saathi_guardrail_blocks_total",
    "Inputs flagged or blocked by an input guardrail",
    ["guardrail", "reason"],
    registry=REGISTRY,
)

# Rough OpenRouter-ish defaults; override with env for demos.
_INPUT_USD_PER_1K = float(os.getenv("SCHEME_SAATHI_COST_INPUT_USD_PER_1K", "0.00015"))
_OUTPUT_USD_PER_1K = float(os.getenv("SCHEME_SAATHI_COST_OUTPUT_USD_PER_1K", "0.0006"))


def record_conversation(endpoint: str) -> None:
    CONVERSATIONS_TOTAL.labels(endpoint=endpoint).inc()
    _otel_instruments.conversations.add(1, {"endpoint": endpoint})


def record_evaluation(scheme_id: str, source: str = "api") -> None:
    EVALUATIONS_TOTAL.labels(scheme_id=scheme_id, source=source).inc()
    _otel_instruments.evaluations.add(
        1, {"scheme_id": scheme_id, "source": source}
    )


def record_verdict(scheme_id: str, result: str) -> None:
    # Keep UI alias aligned with engine / alert labels.
    if result == "cant_tell":
        result = "need_more_information"
    VERDICTS_TOTAL.labels(scheme_id=scheme_id, result=result).inc()
    _otel_instruments.verdicts.add(
        1, {"scheme_id": scheme_id, "result": result}
    )


def record_question(scheme_id: str | None) -> None:
    QUESTIONS_TOTAL.labels(scheme_id=scheme_id or "unknown").inc()
    _otel_instruments.questions.add(
        1, {"scheme_id": scheme_id or "unknown"}
    )


def record_masked_id_hits(count: int = 1, *, field_type: str = "unknown") -> None:
    if count > 0:
        MASKED_ID_HITS_TOTAL.labels(field_type=field_type).inc(count)
        _otel_instruments.masked_id_hits.add(count, {"field_type": field_type})


def record_pending_approval_created() -> None:
    PENDING_APPROVALS.inc()
    _otel_instruments.pending_approvals.add(1)


def record_pending_approval_resolved() -> None:
    # Never go below zero if scrapes race with restarts.
    try:
        current = PENDING_APPROVALS._value.get()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        current = 0
    if current > 0:
        PENDING_APPROVALS.dec()
        _otel_instruments.pending_approvals.add(-1)


def record_tokens(model: str, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
    if input_tokens > 0:
        TOKENS_TOTAL.labels(model=model or "unknown", direction="input").inc(input_tokens)
        _otel_instruments.tokens.add(
            input_tokens, {"model": model or "unknown", "direction": "input"}
        )
    if output_tokens > 0:
        TOKENS_TOTAL.labels(model=model or "unknown", direction="output").inc(output_tokens)
        _otel_instruments.tokens.add(
            output_tokens, {"model": model or "unknown", "direction": "output"}
        )
    cost = (input_tokens / 1000.0) * _INPUT_USD_PER_1K + (
        output_tokens / 1000.0
    ) * _OUTPUT_USD_PER_1K
    if cost > 0:
        COST_USD.observe(cost)
        _otel_instruments.cost_usd.record(cost)


def record_llm_call(model: str, duration_seconds: float) -> None:
    if duration_seconds >= 0:
        LLM_CALL_SECONDS.labels(model=model or "unknown").observe(duration_seconds)
        _otel_instruments.llm_call_seconds.record(
            duration_seconds, {"model": model or "unknown"}
        )


def record_guardrail_block(guardrail: str, reason: str = "flagged") -> None:
    GUARDRAIL_BLOCKS_TOTAL.labels(guardrail=guardrail, reason=reason).inc()
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
        REQUEST_LATENCY_SECONDS.labels(endpoint=endpoint).observe(elapsed)
        _otel_instruments.request_latency.record(elapsed, {"endpoint": endpoint})


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
