"""OpenTelemetry metrics emission for Role 5 monitoring foundation."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from src.api.app import app
from src.observability import metrics
from src.observability import telemetry
from src.observability.metrics import (
    record_masked_id_hits,
    record_pending_approval_created,
    record_pending_approval_resolved,
    record_tokens,
    record_verdict,
)
from src.workflow.agent_runtime import mask_sensitive_text


client = TestClient(app)


@pytest.fixture
def otel_reader(monkeypatch: pytest.MonkeyPatch) -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(
        metrics,
        "_otel_instruments",
        metrics.create_otel_instruments(provider.get_meter("test")),
    )
    return reader


def _otel_points(reader: InMemoryMetricReader, name: str) -> list:
    data = reader.get_metrics_data()
    if data is None:
        return []
    return [
        point
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def test_metrics_route_is_not_exposed() -> None:
    response = client.get("/metrics")

    assert response.status_code == 404


def test_recording_verdict_emits_otel_point(otel_reader) -> None:
    record_verdict("IGNWPS-MH", "eligible")

    (verdict,) = _otel_points(otel_reader, "scheme_saathi.verdicts")
    assert dict(verdict.attributes) == {
        "scheme_id": "IGNWPS-MH",
        "result": "eligible",
    }
    assert verdict.value == 1


def test_cant_tell_alias_records_as_need_more_information(otel_reader) -> None:
    record_verdict("IGNWPS-MH", "cant_tell")

    (verdict,) = _otel_points(otel_reader, "scheme_saathi.verdicts")
    assert dict(verdict.attributes) == {
        "scheme_id": "IGNWPS-MH",
        "result": "need_more_information",
    }


def test_mask_sensitive_text_emits_masked_id_hit(otel_reader) -> None:
    masked = mask_sensitive_text("My Aadhaar is 2345 6789 0123 for the form.")

    assert "[REDACTED_AADHAAR]" in masked
    (hits,) = _otel_points(otel_reader, "scheme_saathi.masked_id_hits")
    assert dict(hits.attributes) == {"field_type": "aadhaar"}
    assert hits.value == 1


def test_record_masked_id_hits_helper(otel_reader) -> None:
    record_masked_id_hits(2, field_type="phone")

    (hits,) = _otel_points(otel_reader, "scheme_saathi.masked_id_hits")
    assert dict(hits.attributes) == {"field_type": "phone"}
    assert hits.value == 2


def test_pending_approvals_never_go_below_zero(otel_reader, monkeypatch) -> None:
    # The open count is process-wide; start from zero so other tests' approvals
    # cannot leak into this check.
    monkeypatch.setattr(metrics, "_pending_approvals_open", 0)
    record_pending_approval_resolved()
    assert _otel_points(otel_reader, "scheme_saathi.pending_approvals") == []

    record_pending_approval_created()
    record_pending_approval_resolved()
    (approvals,) = _otel_points(otel_reader, "scheme_saathi.pending_approvals")
    assert approvals.value == 0


def test_opentelemetry_records_evaluation_and_normalized_verdict(otel_reader) -> None:
    metrics.record_evaluation("IGNWPS-MH", source="journey")
    metrics.record_verdict("IGNWPS-MH", "cant_tell")

    (evaluation,) = _otel_points(otel_reader, "scheme_saathi.evaluations")
    assert evaluation.value == 1
    assert dict(evaluation.attributes) == {
        "scheme_id": "IGNWPS-MH",
        "source": "journey",
    }
    (verdict,) = _otel_points(otel_reader, "scheme_saathi.verdicts")
    assert dict(verdict.attributes) == {
        "scheme_id": "IGNWPS-MH",
        "result": "need_more_information",
    }


def test_opentelemetry_preserves_cost_guardrail_and_approval_signals(
    otel_reader,
) -> None:
    record_tokens("test-model", input_tokens=1000, output_tokens=500)
    metrics.record_guardrail_block("scam_screen", "flagged")
    record_pending_approval_created()
    record_pending_approval_resolved()

    token_points = _otel_points(otel_reader, "scheme_saathi.tokens")
    assert {point.attributes["direction"]: point.value for point in token_points} == {
        "input": 1000,
        "output": 500,
    }
    (cost,) = _otel_points(otel_reader, "scheme_saathi.cost_usd")
    assert cost.count == 1
    (guardrail,) = _otel_points(otel_reader, "scheme_saathi.guardrail_blocks")
    assert guardrail.value == 1
    (approvals,) = _otel_points(otel_reader, "scheme_saathi.pending_approvals")
    assert approvals.value == 0


def test_azure_exporter_is_configured_only_with_connection_string(monkeypatch) -> None:
    from azure.monitor import opentelemetry as azure_monitor_opentelemetry

    calls: list[bool] = []
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(
        azure_monitor_opentelemetry,
        "configure_azure_monitor",
        lambda: calls.append(True),
    )
    monkeypatch.delenv(telemetry.CONNECTION_STRING_ENV, raising=False)
    telemetry.configure_telemetry()
    assert calls == []

    monkeypatch.setenv(telemetry.CONNECTION_STRING_ENV, "test-connection")
    telemetry.configure_telemetry()
    telemetry.configure_telemetry()
    assert calls == [True]


def _attributes_seen_by_exporter(monkeypatch, start: str) -> str:
    """Run configure_telemetry with a stub exporter and return the resource attributes."""

    from azure.monitor import opentelemetry as azure_monitor_opentelemetry

    seen: list[str] = []
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setenv(telemetry.CONNECTION_STRING_ENV, "test-connection")
    # Set first so the test restores the variable afterwards.
    monkeypatch.setenv(telemetry.RESOURCE_ATTRIBUTES_ENV, start)
    monkeypatch.setattr(
        azure_monitor_opentelemetry,
        "configure_azure_monitor",
        lambda: seen.append(os.environ[telemetry.RESOURCE_ATTRIBUTES_ENV]),
    )
    telemetry.configure_telemetry()
    return seen[0]


def test_telemetry_version_follows_app_version(monkeypatch) -> None:
    monkeypatch.setenv(telemetry.APP_VERSION_ENV, "git-0123456789ab")

    attributes = _attributes_seen_by_exporter(monkeypatch, "")

    assert "service.version=git-0123456789ab" in attributes.split(",")
    assert f"service.name={telemetry.DEFAULT_SERVICE_NAME}" in attributes.split(",")


def test_explicit_resource_attributes_are_never_overridden(monkeypatch) -> None:
    monkeypatch.setenv(telemetry.APP_VERSION_ENV, "git-from-deploy")

    attributes = _attributes_seen_by_exporter(
        monkeypatch, "service.version=manual,deployment.environment=dev"
    ).split(",")

    assert "service.version=manual" in attributes
    assert "deployment.environment=dev" in attributes
    assert "service.version=git-from-deploy" not in attributes


def test_no_version_label_without_app_version(monkeypatch) -> None:
    monkeypatch.delenv(telemetry.APP_VERSION_ENV, raising=False)

    attributes = _attributes_seen_by_exporter(monkeypatch, "").split(",")

    assert not any(item.startswith("service.version=") for item in attributes)
    assert f"service.name={telemetry.DEFAULT_SERVICE_NAME}" in attributes


def test_journey_verdict_counts_once_per_conversation(otel_reader) -> None:
    metrics._counted_verdicts.clear()
    for _ in range(3):
        metrics.record_journey_verdict("conv-once", "IGNWPS-MH", "eligible")

    (verdict,) = _otel_points(otel_reader, "scheme_saathi.verdicts")
    assert verdict.value == 1


def test_journey_verdict_counts_again_only_when_it_changes(otel_reader) -> None:
    metrics._counted_verdicts.clear()
    metrics.record_journey_verdict("conv-change", "IGNWPS-MH", "cant_tell")
    metrics.record_journey_verdict("conv-change", "IGNWPS-MH", "cant_tell")
    metrics.record_journey_verdict("conv-change", "IGNWPS-MH", "eligible")

    counts = sorted(
        (dict(point.attributes)["result"], point.value)
        for point in _otel_points(otel_reader, "scheme_saathi.verdicts")
    )
    assert counts == [("eligible", 1), ("need_more_information", 1)]


def test_tool_span_hashes_the_journey_and_omits_arguments(monkeypatch) -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(metrics, "_tracer", provider.get_tracer("test"))

    with metrics.tool_span("journey-agent", "mock_portal", "raw-journey-id"):
        pass

    (span,) = exporter.get_finished_spans()
    attributes = dict(span.attributes)
    assert attributes["tool"] == "mock_portal"
    assert attributes["journey"] == metrics.correlation_id("raw-journey-id")
    assert "raw-journey-id" not in str(attributes)
