import asyncio
import json

import httpx
import pytest

from src.workflow import intake
from src.workflow.agent_config import MAX_COMPLETION_TOKENS, MODEL_TIMEOUT_SECONDS
from src.workflow.intake import IntakeAgentError


def test_query_rewriter_uses_chat_key_and_does_not_send_embedding_key(
    monkeypatch: pytest.MonkeyPatch, fake_openrouter,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", "embedding-test-key")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "test/chat-model")
    fake_openrouter.answer(
        content=json.dumps({"search_query": "widow pension monthly benefit"})
    )

    rewritten = asyncio.run(intake.rewrite_scheme_query("मासिक विधवा पेंशन"))

    assert rewritten == "widow pension monthly benefit"
    request = fake_openrouter.requests[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer chat-test-key"
    assert request.extensions["timeout"]["read"] == MODEL_TIMEOUT_SECONDS
    payload = fake_openrouter.sent_json()
    assert payload["model"] == "test/chat-model"
    assert payload["max_tokens"] == MAX_COMPLETION_TOKENS
    assert payload["messages"][-1]["content"] == "मासिक विधवा पेंशन"


def test_query_rewriter_requires_standard_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", "embedding-test-key")

    with pytest.raises(IntakeAgentError, match="OPENROUTER_API_KEY"):
        asyncio.run(intake.rewrite_scheme_query("widow pension"))


def test_query_rewriter_rejects_empty_model_output(
    monkeypatch: pytest.MonkeyPatch, fake_openrouter,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-test-key")
    fake_openrouter.answer(content='{"search_query":"  "}')

    with pytest.raises(IntakeAgentError, match="empty query"):
        asyncio.run(intake.rewrite_scheme_query("widow pension"))


def test_chat_failures_become_intake_errors_without_sdk_retries(
    monkeypatch: pytest.MonkeyPatch, fake_openrouter,
) -> None:
    """HTTP errors and timeouts are reported once; the SDK never retries."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-test-key")
    fake_openrouter.reply = httpx.Response(503, json={"error": {"message": "down"}})
    with pytest.raises(IntakeAgentError, match="HTTP 503"):
        asyncio.run(intake.rewrite_scheme_query("widow pension"))
    assert len(fake_openrouter.requests) == 1

    fake_openrouter.reply = httpx.ReadTimeout("synthetic timeout")
    with pytest.raises(IntakeAgentError, match="intake request failed"):
        asyncio.run(intake.rewrite_scheme_query("widow pension"))
    assert len(fake_openrouter.requests) == 2


def test_answer_reader_returns_typed_interpretation(
    monkeypatch: pytest.MonkeyPatch, fake_openrouter,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-test-key")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "test/chat-model")
    fake_openrouter.answer(content=json.dumps({
        "kind": "value",
        "value": True,
        "confidence": 0.96,
    }))

    result = asyncio.run(
        intake.interpret_free_text_answer(
            "is_widow", "Are you a widow?", "My husband passed away last year."
        )
    )

    assert result.kind == "value"
    assert result.value is True
    assert result.confidence == 0.96
    request = fake_openrouter.requests[0]
    assert request.headers["Authorization"] == "Bearer chat-test-key"
    assert request.extensions["timeout"]["read"] == MODEL_TIMEOUT_SECONDS
    payload = fake_openrouter.sent_json()
    assert payload["max_tokens"] == MAX_COMPLETION_TOKENS
    assert payload["messages"][-1]["content"] == json.dumps({
        "fact": "is_widow",
        "question": "Are you a widow?",
        "reply": "My husband passed away last year.",
    })


@pytest.mark.parametrize(
    "content",
    [
        '{"kind":"value","value":true,"confidence":2}',
        '{"kind":"unknown","value":false,"confidence":0.9}',
        '{"kind":"value","value":true,"confidence":0.9,"extra":"ignored"}',
    ],
)
def test_answer_reader_rejects_invalid_or_unexpected_model_output(
    monkeypatch: pytest.MonkeyPatch,
    fake_openrouter,
    content: str,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-test-key")
    fake_openrouter.answer(content=content)

    with pytest.raises(IntakeAgentError, match="invalid answer interpretation"):
        asyncio.run(
            intake.interpret_free_text_answer(
                "is_widow", "Are you a widow?", "free text"
            )
        )
