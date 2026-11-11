"""The one place that builds Saathi's OpenRouter chat model.

OpenRouter accepts the OpenAI request format, so LangChain's ``ChatOpenAI``
is used with OpenRouter's ``base_url`` and the OpenRouter API key. Agents
pass the model to ``create_agent``; one-off calls use ``ainvoke``. Search
vectors use LangChain's ``OpenAIEmbeddings`` against OpenRouter the same way.
"""

import httpx
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

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


def openrouter_chat_model(
    api_key: str,
    model: str = DEFAULT_CHAT_MODEL,
    *,
    timeout: float = MODEL_TIMEOUT_SECONDS,
    max_tokens: int = MAX_COMPLETION_TOKENS,
    reasoning_effort: str | None = None,
) -> ChatOpenAI:
    """Build the chat model used for every OpenRouter call.

    Args:
        api_key: The OpenRouter key (the standard chat key, not the free
            embeddings key).
        model: An OpenRouter ``provider/model`` name.
        timeout: Seconds to wait for a reply; slow free models need longer.
        max_tokens: Reply cap. Reasoning models spend it on thinking first.
        reasoning_effort: OpenRouter ``reasoning.effort`` (for example "low")
            to keep reasoning models short; None leaves the model default.
    """

    extra_body: dict = {"max_tokens": max_tokens}
    if reasoning_effort:
        extra_body["reasoning"] = {"effort": reasoning_effort}

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        default_headers=_IDENTIFYING_HEADERS,
        temperature=0,
        # ChatOpenAI would send OpenAI's newer "max_completion_tokens"; send
        # OpenRouter's documented "max_tokens" so the cost cap always applies.
        extra_body=extra_body,
        timeout=timeout,
        # Callers reserve one model call in the conversation budget before
        # calling. Automatic SDK retries would send extra, uncounted requests.
        max_retries=0,
        http_async_client=_http_client(),
    )


def openrouter_embeddings(
    api_key: str, model: str, *, http_client: httpx.Client | None = None,
) -> OpenAIEmbeddings:
    """Build the embeddings model used for scheme vector search.

    Args:
        api_key: The free OpenRouter key used for search (not the chat key).
        model: An OpenRouter embeddings model, such as ``voyageai/voyage-4``.
        http_client: Tests pass a fake transport here; None uses the SDK default.
    """

    return OpenAIEmbeddings(
        model=model,
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        default_headers=_IDENTIFYING_HEADERS,
        # Send the text itself. OpenAI-style token splitting would send token
        # IDs, which non-OpenAI models behind OpenRouter do not accept.
        check_embedding_ctx_length=False,
        # The OpenAI SDK asks for base64 by default; ask for plain numbers,
        # which every OpenRouter embeddings provider returns.
        model_kwargs={"encoding_format": "float"},
        timeout=60,
        # Automatic SDK retries would send extra, uncounted paid requests.
        max_retries=0,
        http_client=http_client,
    )
