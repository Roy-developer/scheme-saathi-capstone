"""M4b: the waiting-approvals counter must track real drafts through each step."""

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from src.observability import metrics
from src.api.app import _track_waiting_approval


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> InMemoryMetricReader:
    test_reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[test_reader])
    monkeypatch.setattr(
        metrics, "_instruments",
        metrics.create_instruments(provider.get_meter("test")),
    )
    return test_reader


def _waiting(reader: InMemoryMetricReader) -> int:
    data = reader.get_metrics_data()
    if data is None:
        return 0
    return sum(
        point.value
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "scheme_saathi.waiting_approvals"
        for point in metric.data.data_points
    )


def _draft(**fields) -> dict:
    return {"approved": False, "rejected": False, "receipt_id": None, **fields}


def test_create_then_edit_keeps_one_waiting(reader) -> None:
    draft = _draft()
    _track_waiting_approval(None, draft)
    edited = {**draft, "district": "Synthetic district 2"}
    _track_waiting_approval(draft, edited)

    assert _waiting(reader) == 1


def test_edit_of_approved_draft_puts_it_back_in_queue(reader) -> None:
    draft = _draft()
    _track_waiting_approval(None, draft)
    approved = {**draft, "approved": True}
    _track_waiting_approval(draft, approved)
    assert _waiting(reader) == 0

    invalidated = {**approved, "approved": False}
    _track_waiting_approval(approved, invalidated)

    assert _waiting(reader) == 1


def test_two_drafts_count_two_and_each_decision_removes_one(reader) -> None:
    first = _draft()
    second = _draft()
    _track_waiting_approval(None, first)
    _track_waiting_approval(None, second)
    assert _waiting(reader) == 2

    _track_waiting_approval(first, {**first, "approved": True})
    assert _waiting(reader) == 1

    _track_waiting_approval(second, {**second, "rejected": True})
    assert _waiting(reader) == 0
