"""The only module that sends chat requests to OpenRouter.

Callers build the request body (model, messages, tools, ...) and read the
reply. ``OpenRouterChatClient`` owns everything else: the address, the
identifying headers, the timeout, the retry setting, the reusable
connection and turning transport failures into one error type.

OpenRouter accepts the OpenAI request format, so the official ``openai`` SDK
is used with OpenRouter's ``base_url`` and the OpenRouter API key.

Two ways to use it:

    # Long-lived (one client reused for many requests, closed at shutdown)
    chat = OpenRouterChatClient(api_key)
    reply = await chat.complete(body)
    ...
    await chat.aclose()

    # One-off (opened and closed around a single request)
    async with OpenRouterChatClient(api_key) as chat:
        reply = await chat.complete(body)
"""

from types import TracebackType
from typing import Any

import httpx
from openai import APIStatusError, AsyncOpenAI, OpenAIError
from openai.types.chat import ChatCompletion

from src.workflow.agent_config import MODEL_TIMEOUT_SECONDS


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_CHAT_MODEL = "openai/gpt-4o-mini"
_IDENTIFYING_HEADERS = {
    "HTTP-Referer": "https://scheme-saathi.local",
    "X-Title": "Scheme Saathi",
}


class ChatRequestError(RuntimeError):
    """The chat request failed: network error, timeout or HTTP error status.

    Attributes:
        status_code: The HTTP status for a rejected request, otherwise None.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _http_client() -> httpx.AsyncClient | None:
    """Return a custom HTTP client, or None for the SDK default.

    Tests replace this function to answer requests with a fake transport,
    so no test ever reaches the network.
    """

    return None


class OpenRouterChatClient:
    """One OpenRouter chat connection, reusable for several requests."""

    def __init__(self, api_key: str) -> None:
        """Prepare the connection settings; nothing is sent until ``complete``.

        Args:
            api_key: The OpenRouter key (the standard chat key, not the
                free embeddings key).
        """

        self._client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            default_headers=_IDENTIFYING_HEADERS,
            timeout=MODEL_TIMEOUT_SECONDS,
            # Callers reserve one model call in the conversation budget before
            # calling. Automatic SDK retries would send extra, uncounted requests.
            max_retries=0,
            http_client=_http_client(),
        )

    async def complete(self, body: dict[str, Any]) -> ChatCompletion:
        """Send one chat-completions request and return the SDK reply object.

        Args:
            body: Keyword arguments for ``chat.completions.create`` (model,
                messages, max_tokens, tools, response_format, ...).

        Raises:
            ChatRequestError: The request could not be completed.
        """

        try:
            return await self._client.chat.completions.create(**body)
        except APIStatusError as error:
            raise ChatRequestError(
                "The chat model rejected the request.", error.status_code
            ) from error
        except OpenAIError as error:
            raise ChatRequestError("The chat model request failed.") from error

    async def aclose(self) -> None:
        """Close the underlying connection."""

        await self._client.close()

    async def __aenter__(self) -> "OpenRouterChatClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
