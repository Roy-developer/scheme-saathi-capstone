import asyncio
import json
from io import BytesIO

import pytest

from src.workflow import intake
from src.workflow.agent_config import MAX_COMPLETION_TOKENS, MODEL_TIMEOUT_SECONDS
from src.workflow.intake import IntakeAgentError


def test_query_rewriter_uses_chat_key_and_does_not_send_embedding_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", "embedding-test-key")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "test/chat-model")

    def fake_urlopen(request, timeout):
        assert timeout == MODEL_TIMEOUT_SECONDS
        requests.append(request)
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"search_query": "widow pension monthly benefit"}
                        )
                    }
                }
            ]
        }
        return BytesIO(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(intake.urllib.request, "urlopen", fake_urlopen)

    rewritten = asyncio.run(intake.rewrite_scheme_query("मासिक विधवा पेंशन"))

    assert rewritten == "widow pension monthly benefit"
    assert requests[0].get_header("Authorization") == 'Bearer chat-test-key'
    payload = json.loads(requests[0].data)
    assert payload["model"] == "test/chat-model"
    assert payload["max_tokens"] == MAX_COMPLETION_TOKENS
    assert payload["messages"][-1]["content"] == "मासिक विधवा पेंशन"


def test_query_rewriter_requires_standard_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", "embedding-test-key")

    with pytest.raises(IntakeAgentError, match="OPENROUTER_API_KEY"):
        asyncio.run(intake.rewrite_scheme_query("widow pension"))


def test_query_rewriter_rejects_empty_model_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-test-key")

    def fake_urlopen(_request, timeout):
        body = {
            "choices": [
                {"message": {"content": '{"search_query":"  "}'}}
            ]
        }
        return BytesIO(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(intake.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(IntakeAgentError, match="empty query"):
        asyncio.run(intake.rewrite_scheme_query("widow pension"))


def test_answer_reader_returns_typed_interpretation(monkeypatch: pytest.MonkeyPatch):
    requests = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-test-key")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "test/chat-model")

    def fake_urlopen(request, timeout):
        assert timeout == MODEL_TIMEOUT_SECONDS
        requests.append(request)
        body = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "kind": "value",
                        "value": True,
                        "confidence": 0.96,
                    })
                }
            }]
        }
        return BytesIO(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(intake.urllib.request, "urlopen", fake_urlopen)

    result = asyncio.run(
        intake.interpret_free_text_answer(
            "is_widow", "Are you a widow?", "My husband passed away last year."
        )
    )

    assert result.kind == "value"
    assert result.value is True
    assert result.confidence == 0.96
    assert requests[0].get_header("Authorization") == 'Bearer chat-test-key'
    payload = json.loads(requests[0].data)
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
    content: str,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-test-key")

    def fake_urlopen(_request, timeout):
        return BytesIO(json.dumps({
            "choices": [{"message": {"content": content}}]
        }).encode("utf-8"))

    monkeypatch.setattr(intake.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(IntakeAgentError, match="invalid answer interpretation"):
        asyncio.run(
            intake.interpret_free_text_answer(
                "is_widow", "Are you a widow?", "free text"
            )
        )
