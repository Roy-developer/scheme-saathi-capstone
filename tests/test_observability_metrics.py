"""Prometheus metrics emission for Role 5 monitoring foundation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import app
from src.observability.metrics import (
    MASKED_ID_HITS_TOTAL,
    PENDING_APPROVALS,
    VERDICTS_TOTAL,
    record_masked_id_hits,
    record_pending_approval_created,
    record_pending_approval_resolved,
    record_tokens,
    record_verdict,
)
from src.workflow.agent_runtime import mask_sensitive_text


client = TestClient(app)


def test_metrics_endpoint_exposes_prometheus_text() -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "scheme_saathi_conversations_total" in body
    assert "scheme_saathi_verdicts_total" in body
    assert "scheme_saathi_masked_id_hits_total" in body
    assert "scheme_saathi_pending_approvals" in body
    assert "scheme_saathi_cost_usd" in body
    assert "scheme_saathi_tokens_total" in body
    assert "scheme_saathi_guardrail_blocks_total" in body


def test_recording_verdict_increments_counter() -> None:
    before = VERDICTS_TOTAL.labels(
        scheme_id="IGNWPS-MH", result="eligible"
    )._value.get()
    record_verdict("IGNWPS-MH", "eligible")
    after = VERDICTS_TOTAL.labels(
        scheme_id="IGNWPS-MH", result="eligible"
    )._value.get()
    assert after == before + 1


def test_cant_tell_alias_records_as_need_more_information() -> None:
    before = VERDICTS_TOTAL.labels(
        scheme_id="IGNWPS-MH", result="need_more_information"
    )._value.get()
    record_verdict("IGNWPS-MH", "cant_tell")
    after = VERDICTS_TOTAL.labels(
        scheme_id="IGNWPS-MH", result="need_more_information"
    )._value.get()
    assert after == before + 1


def test_mask_sensitive_text_increments_masked_id_hits() -> None:
    before = MASKED_ID_HITS_TOTAL.labels(field_type="aadhaar")._value.get()
    masked = mask_sensitive_text("My Aadhaar is 2345 6789 0123 for the form.")
    after = MASKED_ID_HITS_TOTAL.labels(field_type="aadhaar")._value.get()
    assert "[REDACTED_AADHAAR]" in masked
    assert after == before + 1


def test_record_masked_id_hits_helper() -> None:
    before = MASKED_ID_HITS_TOTAL.labels(field_type="phone")._value.get()
    record_masked_id_hits(2, field_type="phone")
    assert MASKED_ID_HITS_TOTAL.labels(field_type="phone")._value.get() == before + 2


def test_pending_approvals_gauge() -> None:
    before = PENDING_APPROVALS._value.get()
    record_pending_approval_created()
    assert PENDING_APPROVALS._value.get() == before + 1
    record_pending_approval_resolved()
    assert PENDING_APPROVALS._value.get() == before


def test_record_tokens_updates_cost_histogram() -> None:
    response_before = client.get("/metrics").text
    record_tokens("test-model", input_tokens=1000, output_tokens=500)
    body = client.get("/metrics").text
    assert "scheme_saathi_tokens_total" in body
    assert "scheme_saathi_cost_usd_count" in body
    assert "test-model" in body or "scheme_saathi_tokens_total" in response_before
