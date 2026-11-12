import uuid

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


def test_repeated_verdict_in_same_conversation_counts_once(reader) -> None:
    conversation = str(uuid.uuid4())
    metrics.record_new_verdicts(conversation, {"IGNWPS-MH": "eligible"})
    metrics.record_new_verdicts(conversation, {"IGNWPS-MH": "eligible"})

    (point,) = _points(reader, "scheme_saathi.verdicts")
    assert point.value == 1


def test_changed_verdict_counts_again(reader) -> None:
    conversation = str(uuid.uuid4())
    metrics.record_new_verdicts(conversation, {"IGNWPS-MH": "eligible"})
    metrics.record_new_verdicts(conversation, {"IGNWPS-MH": "not_eligible"})

    points = {
        dict(point.attributes)["result"]: point.value
        for point in _points(reader, "scheme_saathi.verdicts")
    }
    assert points == {"eligible": 1, "not_eligible": 1}


def test_same_verdict_in_different_conversations_counts_each(reader) -> None:
    metrics.record_new_verdicts(str(uuid.uuid4()), {"PM-KISAN-IN": "eligible"})
    metrics.record_new_verdicts(str(uuid.uuid4()), {"PM-KISAN-IN": "eligible"})

    (point,) = _points(reader, "scheme_saathi.verdicts")
    assert point.value == 2


def _pending(**fields) -> dict:
    return {"approved": False, "rejected": False, "receipt_id": None, **fields}


def test_waiting_approvals_follow_draft_transitions(reader) -> None:
    from src.api.app import _track_waiting_approval

    draft = _pending()
    _track_waiting_approval(None, draft)
    assert sum(p.value for p in _points(reader, "scheme_saathi.waiting_approvals")) == 1

    approved = {**draft, "approved": True}
    _track_waiting_approval(draft, approved)
    assert sum(p.value for p in _points(reader, "scheme_saathi.waiting_approvals")) == 0

    _track_waiting_approval(approved, {**approved, "receipt_id": "R-1"})
    assert sum(p.value for p in _points(reader, "scheme_saathi.waiting_approvals")) == 0

    _track_waiting_approval(approved, {**approved, "approved": False})
    assert sum(p.value for p in _points(reader, "scheme_saathi.waiting_approvals")) == 1


def test_reject_removes_a_waiting_draft(reader) -> None:
    from src.api.app import _track_waiting_approval

    draft = _pending()
    _track_waiting_approval(None, draft)
    _track_waiting_approval(draft, {**draft, "rejected": True})

    assert sum(p.value for p in _points(reader, "scheme_saathi.waiting_approvals")) == 0
