"""OpenTelemetry metric definitions and recording helpers.

Instruments come from the process's global meter provider. Until a provider is
configured (see ``src.observability.telemetry``), recording is a no-op, so
offline runs and tests need no backend.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Mapping

from opentelemetry import metrics as otel_metrics

METER_NAME = "scheme_saathi"


@dataclass(frozen=True)
class Instruments:
    conversations: otel_metrics.Counter
    evaluations: otel_metrics.Counter
    verdicts: otel_metrics.Counter
    questions: otel_metrics.Counter
    masked_id_hits: otel_metrics.Counter
    request_latency: otel_metrics.Histogram


def create_instruments(meter: otel_metrics.Meter) -> Instruments:
    return Instruments(
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
        request_latency=meter.create_histogram(
            "scheme_saathi.request_latency",
            unit="s",
            description="Latency for evaluate and journey HTTP handlers",
        ),
    )


_instruments = create_instruments(otel_metrics.get_meter(METER_NAME))


def record_conversation(endpoint: str) -> None:
    """Count a journey start or resume."""

    _instruments.conversations.add(1, {"endpoint": endpoint})


def record_evaluation(scheme_id: str, source: str = "api") -> None:
    """Count one eligibility evaluation."""

    _instruments.evaluations.add(1, {"scheme_id": scheme_id, "source": source})


def record_verdict(scheme_id: str, result: str) -> None:
    """Count a rule-engine or journey verdict."""

    _instruments.verdicts.add(1, {"scheme_id": scheme_id, "result": result})


_MAX_TRACKED_CONVERSATIONS = 10_000
_last_counted_verdicts: OrderedDict[str, dict[str, str]] = OrderedDict()


def record_new_verdicts(
    conversation_id: str, verdicts: Mapping[str, str], source: str = "journey"
) -> None:
    """Count a scheme's verdict only when it differs from the last one counted.

    Journey replies repeat every verdict already reached in the conversation,
    so counting each reply would overcount.
    """

    counted = _last_counted_verdicts.setdefault(conversation_id, {})
    _last_counted_verdicts.move_to_end(conversation_id)
    while len(_last_counted_verdicts) > _MAX_TRACKED_CONVERSATIONS:
        _last_counted_verdicts.popitem(last=False)
    for scheme_id, result in verdicts.items():
        if counted.get(scheme_id) == result:
            continue
        counted[scheme_id] = result
        record_evaluation(scheme_id, source=source)
        record_verdict(scheme_id, result)


def record_question(scheme_id: str | None) -> None:
    """Count a pending interview question shown to the user."""

    _instruments.questions.add(1, {"scheme_id": scheme_id or "unknown"})


def record_masked_id_hits(count: int = 1) -> None:
    """Count masked identifier hits."""

    if count > 0:
        _instruments.masked_id_hits.add(count)


@contextmanager
def observe_duration(endpoint: str) -> Iterator[None]:
    """Time an HTTP handler and record latency."""

    started = time.perf_counter()
    try:
        yield
    finally:
        _instruments.request_latency.record(
            time.perf_counter() - started, {"endpoint": endpoint}
        )
