"""The agent-side identifier counter counts hits once and never changes text."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from src.observability import metrics
from src.workflow.agent_runtime import IdentifierHitCounter


def test_identifier_counted_once_and_text_untouched(monkeypatch) -> None:
    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(
        metrics, "record_masked_id_hits",
        lambda count=1, *, field_type="unknown": calls.append((count, field_type)),
    )
    message = HumanMessage(content="My Aadhaar is 2345 6789 0123 for the form.", id="m1")
    state = {"messages": [message]}
    counter = IdentifierHitCounter()

    counter.before_model(state, None)
    counter.before_model(state, None)  # same message revisited on a later model call

    assert message.content == "My Aadhaar is 2345 6789 0123 for the form."
    assert [c for c in calls if c[1] == "aadhaar"] == [(1, "aadhaar")]


def test_plain_text_records_nothing(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(metrics, "record_masked_id_hits", lambda *a, **k: calls.append(a))
    IdentifierHitCounter().before_model(
        {"messages": [HumanMessage(content="I am a farmer in Maharashtra.", id="m2")]}, None
    )
    assert calls == []
