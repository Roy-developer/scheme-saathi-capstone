"""Token metering for LLM calls that bypass the metered agent middleware."""

from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from pydantic import BaseModel

from src.documents import extraction
from src.observability import metrics
from src.rule_extraction_reflexion import extractor
from src.workflow import intake, intake_agent


USAGE = {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    def fake_record_tokens(model, *, input_tokens=0, output_tokens=0):
        calls.append((model, {"input_tokens": input_tokens, "output_tokens": output_tokens}))

    monkeypatch.setattr(metrics, "record_tokens", fake_record_tokens)
    return calls


def _emit_usage(config, model_name: str, usage: dict) -> None:
    """Stand in for a provider reply by firing the usage callback handlers."""

    response = LLMResult(generations=[[ChatGeneration(message=AIMessage(
        content="{}", usage_metadata=usage, response_metadata={"model_name": model_name},
    ))]])
    for handler in (config or {}).get("callbacks", []):
        handler.on_llm_end(response, run_id=uuid4())


class _ReplyModel:
    """Chat-model stub with a reply-based ainvoke and invoke."""

    def __init__(self, model_name: str, content: str, usage: dict | None) -> None:
        self.model_name = model_name
        self._reply = AIMessage(content=content, usage_metadata=usage)

    async def ainvoke(self, messages, **kwargs):
        return self._reply

    def invoke(self, messages, **kwargs):
        return self._reply


class _StructuredRunnable:
    def __init__(self, model_name: str, result, usage: dict) -> None:
        self._model_name = model_name
        self._result = result
        self._usage = usage

    async def ainvoke(self, messages, config=None):
        _emit_usage(config, self._model_name, self._usage)
        return self._result


class _StructuredModel:
    def __init__(self, model_name: str, result, usage: dict) -> None:
        self.model_name = model_name
        self._runnable = _StructuredRunnable(model_name, result, usage)

    def with_structured_output(self, schema, **kwargs):
        return self._runnable


class _Out(BaseModel):
    value: int


def test_vision_extractor_records_usage_once(
    monkeypatch: pytest.MonkeyPatch, recorded: list,
) -> None:
    monkeypatch.setattr(
        "src.llm_client.openrouter_chat_model",
        lambda *args, **kwargs: _ReplyModel("vision/test", "Income: 1000", USAGE),
    )
    text = extraction.OpenRouterVisionExtractor("key", "vision/test").read_text(
        b"\x89PNG\r\n\x1a\nimage-bytes"
    )
    assert text == "Income: 1000"
    assert recorded == [("vision/test", {"input_tokens": 120, "output_tokens": 30})]


def test_rule_extractor_records_usage_once(recorded: list) -> None:
    model = _StructuredModel("rules/test", _Out(value=7), USAGE)
    result = _run(extractor.invoke_structured_output(model, _Out, "system", "user"))
    assert result == _Out(value=7)
    assert recorded == [("rules/test", {"input_tokens": 120, "output_tokens": 30})]


def test_intake_reader_records_usage_once(recorded: list) -> None:
    provider = _ReplyModel("intake/test", '{"value": 3}', USAGE)
    result = _run(intake._ask_with_provider(provider, _Out, "system", "user"))
    assert result == _Out(value=3)
    assert recorded == [("intake/test", {"input_tokens": 120, "output_tokens": 30})]


def test_intake_structured_reader_records_usage_once(
    monkeypatch: pytest.MonkeyPatch, recorded: list,
) -> None:
    model = _StructuredModel("chat/test", _Out(value=5), USAGE)
    monkeypatch.setattr(intake, "openrouter_chat_settings", lambda default: ("key", "chat/test"))
    monkeypatch.setattr(intake, "openrouter_chat_model", lambda api_key, name: model)
    result = _run(intake._ask_structured(_Out, "system", "user", "intake", "invalid"))
    assert result == _Out(value=5)
    assert recorded == [("chat/test", {"input_tokens": 120, "output_tokens": 30})]


def test_intake_agent_description_reader_records_usage_once(recorded: list) -> None:
    provider = _ReplyModel("description/test", "not json", USAGE)
    _run(intake_agent.read_description_facts(provider, "a description", ["fact"]))
    assert recorded == [("description/test", {"input_tokens": 120, "output_tokens": 30})]


def test_metering_failure_never_breaks_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("metrics backend down")

    monkeypatch.setattr(metrics, "record_tokens", broken)
    provider = _ReplyModel("intake/test", '{"value": 9}', USAGE)
    result = _run(intake._ask_with_provider(provider, _Out, "system", "user"))
    assert result == _Out(value=9)


def _run(awaitable):
    import asyncio

    return asyncio.run(awaitable)
