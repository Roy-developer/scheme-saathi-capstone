"""Observability helpers: OpenTelemetry metrics for Scheme Saathi (Role 5 / Role 6)."""

from src.observability.metrics import (
    observe_duration,
    record_conversation,
    record_evaluation,
    record_guardrail_block,
    record_llm_call,
    record_masked_id_hits,
    record_pending_approval_created,
    record_pending_approval_resolved,
    record_question,
    record_tokens,
    record_verdict,
)

__all__ = [
    "observe_duration",
    "record_conversation",
    "record_evaluation",
    "record_guardrail_block",
    "record_llm_call",
    "record_masked_id_hits",
    "record_pending_approval_created",
    "record_pending_approval_resolved",
    "record_question",
    "record_tokens",
    "record_verdict",
]
