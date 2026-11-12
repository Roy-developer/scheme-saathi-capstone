import json
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


def test_aadhaar_like_number_adds_one_masked_hit(reader) -> None:
    from src.workflow.agent_runtime import mask_sensitive_text

    masked = mask_sensitive_text("My Aadhaar is 1234 5678 9012 please.")

    assert "1234 5678 9012" not in masked
    (point,) = _points(reader, "scheme_saathi.masked_id_hits")
    assert point.value == 1


def test_plain_text_adds_no_masked_hit(reader) -> None:
    from src.workflow.agent_runtime import mask_sensitive_text

    mask_sensitive_text("I am a farmer in Maharashtra with a small plot.")

    assert _points(reader, "scheme_saathi.masked_id_hits") == []


def test_model_usage_records_tokens_by_direction(reader, monkeypatch) -> None:
    monkeypatch.setattr(metrics, "_price_table", lambda: {})

    metrics.record_model_usage("fake-model", 120, 30)

    points = {
        dict(point.attributes)["direction"]: point.value
        for point in _points(reader, "scheme_saathi.model_tokens")
    }
    assert points == {"input": 120, "output": 30}


def test_model_cost_total_equals_sum_of_two_calls(reader, monkeypatch) -> None:
    # Fake prices and usage only: USD per 1M tokens.
    monkeypatch.setattr(
        metrics, "_price_table", lambda: {"fake-model": (2.0, 8.0)}
    )

    metrics.record_model_usage("fake-model", 1_000_000, 500_000)  # 2.0 + 4.0
    metrics.record_model_usage("fake-model", 250_000, 100_000)  # 0.5 + 0.8

    (point,) = _points(reader, "scheme_saathi.model_cost_usd")
    assert point.value == pytest.approx(2.0 + 4.0 + 0.5 + 0.8)
    assert dict(point.attributes) == {"model": "fake-model"}


def test_unpriced_model_records_tokens_but_no_cost(reader, monkeypatch) -> None:
    monkeypatch.setattr(metrics, "_price_table", lambda: {"fake-model": (None, None)})

    metrics.record_model_usage("fake-model", 100, 100)

    assert _points(reader, "scheme_saathi.model_cost_usd") == []
    assert len(_points(reader, "scheme_saathi.model_tokens")) == 2


def test_price_file_is_marked_as_needing_confirmation() -> None:
    data = json.loads(metrics.PRICES_PATH.read_text(encoding="utf-8"))

    assert data["needs_confirmation"] is True
    assert all(
        entry["needs_confirmation"] is True for entry in data["models"].values()
    )
