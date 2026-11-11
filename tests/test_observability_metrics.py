import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from src.observability import metrics
from src.observability.telemetry import configure_telemetry


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> InMemoryMetricReader:
    test_reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[test_reader])
    monkeypatch.setattr(
        metrics,
        "_instruments",
        metrics.create_instruments(provider.get_meter("test")),
    )
    return test_reader


def _points(reader: InMemoryMetricReader, name: str) -> list:
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


def test_evaluation_counter_carries_scheme_and_source(reader) -> None:
    metrics.record_evaluation("IGNWPS-MH", source="api")
    metrics.record_evaluation("IGNWPS-MH", source="api")

    (point,) = _points(reader, "scheme_saathi.evaluations")
    assert point.value == 2
    assert dict(point.attributes) == {"scheme_id": "IGNWPS-MH", "source": "api"}


def test_verdict_counter_carries_result(reader) -> None:
    metrics.record_verdict("PM-KISAN-IN", "not_eligible")

    (point,) = _points(reader, "scheme_saathi.verdicts")
    assert point.value == 1
    assert dict(point.attributes) == {
        "scheme_id": "PM-KISAN-IN",
        "result": "not_eligible",
    }


def test_question_without_scheme_is_labelled_unknown(reader) -> None:
    metrics.record_question(None)

    (point,) = _points(reader, "scheme_saathi.questions")
    assert dict(point.attributes) == {"scheme_id": "unknown"}


def test_masked_id_hits_ignore_zero(reader) -> None:
    metrics.record_masked_id_hits(0)
    metrics.record_masked_id_hits(3)

    (point,) = _points(reader, "scheme_saathi.masked_id_hits")
    assert point.value == 3


def test_observe_duration_records_latency_per_endpoint(reader) -> None:
    with metrics.observe_duration("journey"):
        pass

    (point,) = _points(reader, "scheme_saathi.request_latency")
    assert point.count == 1
    assert dict(point.attributes) == {"endpoint": "journey"}


def test_telemetry_stays_off_without_connection_string(monkeypatch) -> None:
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)

    configure_telemetry()
