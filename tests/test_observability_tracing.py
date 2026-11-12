import asyncio
import re
import uuid

import pytest
from langchain_core.tools import tool
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel, ConfigDict

from src.observability import metrics
from src.observability.tracing import (
    CORRELATION_ATTRIBUTE,
    SPAN_ATTRIBUTES,
    correlation_id,
)
from src.workflow.agent_runtime import run_agent
from src.workflow.agent_middleware import observation
from tests.fake_chat_model import FakeChatModel, ModelDecision

PLANTED_AADHAAR = "2345 6789 0123"
PLANTED_DIGITS = "234567890123"


class CheckArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme_id: str


@pytest.fixture
def exporter(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """Route the global tracer to an in-memory exporter for one test."""

    span_exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    monkeypatch.setattr(trace, "get_tracer", lambda name, *a, **k: provider.get_tracer(name))
    return span_exporter


@pytest.fixture
def metric_reader(monkeypatch: pytest.MonkeyPatch) -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(
        metrics, "_instruments", metrics.create_instruments(provider.get_meter("test"))
    )
    return reader


def _one_model_call_run(correlation: str | None = None):
    """One fake model call that picks one action, with a planted secret in context."""

    class OneCallModel(FakeChatModel):
        model_name: str = "offline-tracing"

        async def choose(self, agent, locale, messages, actions):
            return ModelDecision(
                action="check_candidate",
                arguments={"scheme_id": "IGNWPS-MH"},
                input_tokens=111,
                output_tokens=22,
            )

    @tool(args_schema=CheckArguments, return_direct=True)
    async def check_candidate(scheme_id: str) -> str:
        """Check one scheme."""
        return observation(CheckArguments(scheme_id=scheme_id))

    context = {"scheme_id": "IGNWPS-MH", "applicant_note": f"Aadhaar {PLANTED_AADHAAR}"}
    return asyncio.run(run_agent(
        OneCallModel(), "eligibility", "mr", context, [check_candidate],
        correlation_id=correlation,
    ))


def _attribute_values(spans) -> list[object]:
    return [value for span in spans for value in span.attributes.values()]


def test_model_call_emits_span_with_only_allowed_attributes(exporter) -> None:
    _one_model_call_run()

    spans = exporter.get_finished_spans()
    model_spans = [span for span in spans if span.name == "saathi.model_call"]
    assert model_spans, "expected a span for the model call"
    for span in spans:
        assert set(span.attributes) <= SPAN_ATTRIBUTES | {CORRELATION_ATTRIBUTE}
    tool_spans = [span for span in spans if span.name == "saathi.tool_call"]
    assert tool_spans and dict(tool_spans[0].attributes)["action"] == "check_candidate"


def test_planted_secret_never_appears_in_any_span_attribute(exporter) -> None:
    _one_model_call_run(correlation=correlation_id(str(uuid.uuid4())))

    spans = exporter.get_finished_spans()
    assert spans
    for value in _attribute_values(spans):
        text = str(value)
        assert PLANTED_AADHAAR not in text
        assert PLANTED_DIGITS not in re.sub(r"\D", "", text)


def test_span_attributes_carry_usage_and_correlation(exporter) -> None:
    conversation = str(uuid.uuid4())
    _one_model_call_run(correlation=correlation_id(conversation))

    model = next(s for s in exporter.get_finished_spans() if s.name == "saathi.model_call")
    attributes = dict(model.attributes)
    assert attributes["input_tokens"] == 111
    assert attributes["output_tokens"] == 22
    assert attributes["model"] == "offline-tracing"
    assert attributes[CORRELATION_ATTRIBUTE] == correlation_id(conversation)


def test_correlation_is_sha256_prefix_and_stable() -> None:
    conversation = str(uuid.uuid4())
    first = correlation_id(conversation)
    assert first == correlation_id(conversation)
    assert len(first) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", first)
    assert correlation_id(str(uuid.uuid4())) != first


def test_raw_conversation_id_never_appears_in_span_attributes(exporter) -> None:
    conversation = str(uuid.uuid4())
    _one_model_call_run(correlation=correlation_id(conversation))

    for value in _attribute_values(exporter.get_finished_spans()):
        assert conversation not in str(value)


def test_metrics_carry_hashed_correlation_not_raw_id(metric_reader) -> None:
    conversation = str(uuid.uuid4())
    metrics.record_conversation("journey", conversation)
    metrics.record_question("IGNWPS-MH", conversation)

    data = metric_reader.get_metrics_data()
    points = [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
    ]
    expected = correlation_id(conversation)
    labelled = [p for p in points if CORRELATION_ATTRIBUTE in dict(p.attributes)]
    assert len(labelled) == 2  # conversation and question
    for point in labelled:
        assert dict(point.attributes)[CORRELATION_ATTRIBUTE] == expected
        assert conversation not in str(dict(point.attributes))
