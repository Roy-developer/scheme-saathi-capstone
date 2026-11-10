"""Prometheus metrics for Scheme Saathi (L13/L16 monitoring).

Maps to the Monitoring & Evaluation guide panels: questions, can't-tell /
need_more_information rate, pending approvals, masked-ID hits, cost, plus
latency and guardrail blocks. Role 6 scrapes GET /metrics.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)


REGISTRY = CollectorRegistry()

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


def record_evaluation(scheme_id: str, source: str = "api") -> None:
    EVALUATIONS_TOTAL.labels(scheme_id=scheme_id, source=source).inc()


def record_verdict(scheme_id: str, result: str) -> None:
    # Keep UI alias aligned with engine / alert labels.
    if result == "cant_tell":
        result = "need_more_information"
    VERDICTS_TOTAL.labels(scheme_id=scheme_id, result=result).inc()


def record_question(scheme_id: str | None) -> None:
    QUESTIONS_TOTAL.labels(scheme_id=scheme_id or "unknown").inc()


def record_masked_id_hits(count: int = 1, *, field_type: str = "unknown") -> None:
    if count > 0:
        MASKED_ID_HITS_TOTAL.labels(field_type=field_type).inc(count)


def record_pending_approval_created() -> None:
    PENDING_APPROVALS.inc()


def record_pending_approval_resolved() -> None:
    # Never go below zero if scrapes race with restarts.
    try:
        current = PENDING_APPROVALS._value.get()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        current = 0
    if current > 0:
        PENDING_APPROVALS.dec()


def record_tokens(model: str, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
    if input_tokens > 0:
        TOKENS_TOTAL.labels(model=model or "unknown", direction="input").inc(input_tokens)
    if output_tokens > 0:
        TOKENS_TOTAL.labels(model=model or "unknown", direction="output").inc(output_tokens)
    cost = (input_tokens / 1000.0) * _INPUT_USD_PER_1K + (
        output_tokens / 1000.0
    ) * _OUTPUT_USD_PER_1K
    if cost > 0:
        COST_USD.observe(cost)


def record_llm_call(model: str, duration_seconds: float) -> None:
    if duration_seconds >= 0:
        LLM_CALL_SECONDS.labels(model=model or "unknown").observe(duration_seconds)


def record_guardrail_block(guardrail: str, reason: str = "flagged") -> None:
    GUARDRAIL_BLOCKS_TOTAL.labels(guardrail=guardrail, reason=reason).inc()


@contextmanager
def observe_duration(endpoint: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        REQUEST_LATENCY_SECONDS.labels(endpoint=endpoint).observe(
            time.perf_counter() - started
        )


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
