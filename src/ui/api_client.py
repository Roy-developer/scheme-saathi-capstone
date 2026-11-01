"""HTTP client for the orchestrated Scheme Saathi journey API."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import ValidationError

from src.workflow.journey import JourneyRequest, JourneyResponse


class JourneyApiError(Exception):
    """Report a safe, user-actionable orchestrated journey failure."""


def run_journey(journey: JourneyRequest) -> JourneyResponse:
    """Run one conversational step through the LangGraph API."""

    base_url = os.getenv("SCHEME_SAATHI_API_URL", "http://127.0.0.1:8000")
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/journey",
        data=journey.model_dump_json().encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            response_body = response.read()
    except HTTPError as error:
        raise JourneyApiError(
            f"The journey API returned HTTP {error.code}."
        ) from error
    except (URLError, TimeoutError) as error:
        raise JourneyApiError(
            "Could not reach the journey API. Start the API and try again."
        ) from error

    try:
        return JourneyResponse.model_validate(json.loads(response_body))
    except (json.JSONDecodeError, ValidationError) as error:
        raise JourneyApiError(
            "The journey API returned an invalid response."
        ) from error


def forget_journey(conversation_id: str) -> None:
    """Delete the session's persisted LangGraph checkpoint."""

    base_url = os.getenv("SCHEME_SAATHI_API_URL", "http://127.0.0.1:8000")
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/journey/{quote(conversation_id, safe='')}",
        method="DELETE",
    )
    try:
        with urlopen(request, timeout=10):
            pass
    except HTTPError as error:
        raise JourneyApiError(
            "The journey API could not clear the saved session."
        ) from error
    except (URLError, TimeoutError) as error:
        raise JourneyApiError(
            "Could not clear the saved journey. The API may be unavailable."
        ) from error
