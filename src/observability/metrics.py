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
