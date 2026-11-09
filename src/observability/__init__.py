"""Observability helpers: Prometheus metrics emission for Role 5 / Role 6."""

from src.observability.metrics import (
    metrics_response,
    observe_duration,
    record_conversation,
    record_evaluation,
    record_masked_id_hits,
    record_question,
    record_verdict,
)

__all__ = [
    "metrics_response",
    "observe_duration",
    "record_conversation",
    "record_evaluation",
    "record_masked_id_hits",
    "record_question",
    "record_verdict",
]
