"""Prometheus metric definitions and recording helpers.

Role 5 emits these counters for later Grafana scraping (Role 6). This module
does not start Prometheus or ship dashboards.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)


# Isolated registry so tests can reset without touching the global default.
REGISTRY = CollectorRegistry()

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

VERDICTS_TOTAL = Counter(
    "scheme_saathi_verdicts_total",
    "Eligibility verdict results",
    ["scheme_id", "result"],
    registry=REGISTRY,
)

QUESTIONS_TOTAL = Counter(
    "scheme_saathi_questions_total",
    "Interview questions returned to the user",
    ["scheme_id"],
    registry=REGISTRY,
)

MASKED_ID_HITS_TOTAL = Counter(
    "scheme_saathi_masked_id_hits_total",
    "Identifier strings masked before model or trace use",
    registry=REGISTRY,
)

REQUEST_LATENCY_SECONDS = Histogram(
    "scheme_saathi_request_latency_seconds",
    "Latency for evaluate and journey HTTP handlers",
    ["endpoint"],
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)


def record_conversation(endpoint: str) -> None:
    """Count a journey start or resume."""

    CONVERSATIONS_TOTAL.labels(endpoint=endpoint).inc()


def record_evaluation(scheme_id: str, source: str = "api") -> None:
    """Count one eligibility evaluation."""

    EVALUATIONS_TOTAL.labels(scheme_id=scheme_id, source=source).inc()


def record_verdict(scheme_id: str, result: str) -> None:
    """Count a rule-engine or journey verdict."""

    VERDICTS_TOTAL.labels(scheme_id=scheme_id, result=result).inc()


def record_question(scheme_id: str | None) -> None:
    """Count a pending interview question shown to the user."""

    QUESTIONS_TOTAL.labels(scheme_id=scheme_id or "unknown").inc()


def record_masked_id_hits(count: int = 1) -> None:
    """Count masked identifier hits."""

    if count > 0:
        MASKED_ID_HITS_TOTAL.inc(count)


@contextmanager
def observe_duration(endpoint: str) -> Iterator[None]:
    """Time an HTTP handler and record latency."""

    started = time.perf_counter()
    try:
        yield
    finally:
        REQUEST_LATENCY_SECONDS.labels(endpoint=endpoint).observe(
            time.perf_counter() - started
        )


def metrics_response() -> tuple[bytes, str]:
    """Return Prometheus text exposition and content type."""

    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
