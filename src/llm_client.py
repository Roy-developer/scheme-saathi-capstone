"""The one place that builds Saathi's OpenRouter chat model.

OpenRouter accepts the OpenAI request format, so LangChain's ``ChatOpenAI``
is used with OpenRouter's ``base_url`` and the OpenRouter API key. Agents
pass the model to ``create_agent``; one-off calls use ``ainvoke``.
"""

import httpx
from langchain_openai import ChatOpenAI

from src.workflow.agent_config import MAX_COMPLETION_TOKENS, MODEL_TIMEOUT_SECONDS


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_CHAT_MODEL = "openai/gpt-4o-mini"
_IDENTIFYING_HEADERS = {
    "HTTP-Referer": "https://scheme-saathi.local",
    "X-Title": "Scheme Saathi",
}


def _http_client() -> httpx.AsyncClient | None:
    """Return a custom HTTP client, or None for the SDK default.

    Tests replace this function to answer requests with a fake transport,
    so no test ever reaches the network.
    """

    return None


def openrouter_chat_model(api_key: str, model: str = DEFAULT_CHAT_MODEL) -> ChatOpenAI:
    """Build the chat model used for every OpenRouter call.

    Args:
        api_key: The OpenRouter key (the standard chat key, not the free
            embeddings key).
        model: An OpenRouter ``provider/model`` name.
    """

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        default_headers=_IDENTIFYING_HEADERS,
        temperature=0,
        # ChatOpenAI would send OpenAI's newer "max_completion_tokens"; send
        # OpenRouter's documented "max_tokens" so the cost cap always applies.
        extra_body={"max_tokens": MAX_COMPLETION_TOKENS},
        timeout=MODEL_TIMEOUT_SECONDS,
        # Callers reserve one model call in the conversation budget before
        # calling. Automatic SDK retries would send extra, uncounted requests.
        max_retries=0,
        http_async_client=_http_client(),
    )
