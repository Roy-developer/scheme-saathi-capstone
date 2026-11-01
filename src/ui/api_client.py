"""HTTP client for the deterministic eligibility API."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import ValidationError

from src.api.eligibility import EligibilityResponse
from src.ui.models import SyntheticProfile


class EligibilityApiError(Exception):
    """Report a safe, user-actionable API request or response failure."""


def evaluate_profile(
    scheme_id: str,
    profile: SyntheticProfile,
) -> EligibilityResponse:
    """Send synthetic profile facts to the API and validate its response."""

    base_url = os.getenv("SCHEME_SAATHI_API_URL", "http://127.0.0.1:8000")
    endpoint = (
        f"{base_url.rstrip('/')}/api/v1/schemes/"
        f"{quote(scheme_id, safe='')}/evaluate"
    )
    payload = {
        "date_of_birth": profile.date_of_birth.isoformat(),
        "application_date": profile.application_date.isoformat(),
        "is_widow": profile.is_widow,
        "bpl_card_shown": profile.bpl_card_shown,
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=5) as response:
            response_body = response.read()
    except HTTPError as error:
        raise EligibilityApiError(
            f"The eligibility API returned HTTP {error.code}."
        ) from error
    except (URLError, TimeoutError) as error:
        raise EligibilityApiError(
            "Could not reach the eligibility API. Start it locally and try again."
        ) from error

    try:
        response_data = json.loads(response_body)
        return EligibilityResponse.model_validate(response_data)
    except (json.JSONDecodeError, ValidationError) as error:
        raise EligibilityApiError(
            "The eligibility API returned an invalid response."
        ) from error
