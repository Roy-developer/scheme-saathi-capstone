"""HTTP client for the supervised Scheme Saathi journey API.

The Streamlit screen never runs the LangGraph graph itself. It calls these
small functions, and each one sends one HTTP request to the FastAPI service:

    run_journey          POST   /api/v1/journey                      start a request
    send_journey_message POST   /api/v1/journey/{id}/messages        answer a question
    get_journey_state    GET    /api/v1/journey/{id}                 reload after refresh
    forget_journey       DELETE /api/v1/journey/{id}                 delete saved data

Every failure becomes a JourneyApiError with a short, safe message that the
screen can show. Raw server details are never shown to the user.
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import ValidationError

from src.workflow.journey import (
    JourneyCorrection,
    JourneyMessage,
    JourneyRequest,
    JourneyResponse,
)


class JourneyApiError(Exception):
    """Report a safe, user-actionable journey failure."""


class ApplicationApiError(Exception):
    """Report a safe failure while using synthetic document/draft routes."""


def _journey_url(path: str = "") -> str:
    """Build a journey API address from the configured base URL.

    Args:
        path: Extra path after ``/api/v1/journey``, for example ``/<id>``.
    """

    # Docker and Azure set SCHEME_SAATHI_API_URL; local runs use port 8000.
    base_url = os.getenv("SCHEME_SAATHI_API_URL", "http://127.0.0.1:8000")
    return f"{base_url.rstrip('/')}/api/v1/journey{path}"


def _conversation_path(conversation_id: str) -> str:
    """Return ``/<id>`` with the ID made safe for use in a URL."""

    # quote() stops odd characters (like "/") from changing the address.
    return f"/{quote(str(conversation_id), safe='')}"


def _send(request: Request, *, timeout: float) -> JourneyResponse:
    """Send a request and turn the JSON reply into a JourneyResponse.

    Raises:
        JourneyApiError: the API could not be reached, returned an HTTP
            error, or returned JSON that does not match JourneyResponse.
    """

    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except HTTPError as error:
        if error.code == 409:
            # The conversation is not waiting for an answer any more, for
            # example because the page was open in two tabs.
            raise JourneyApiError(
                "This conversation is no longer waiting for an answer. "
                "Start again."
            ) from error
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


def run_journey(journey: JourneyRequest) -> JourneyResponse:
    """Start one request (search, evaluate or interview) in a conversation."""

    request = Request(
        _journey_url(),
        data=journey.model_dump_json().encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # Search may call the LLM and the reranker, so allow a long wait.
    return _send(request, timeout=60)


def send_journey_message(conversation_id: str, message: str) -> JourneyResponse:
    """Send the user's answer to the question the conversation is waiting on.

    Args:
        conversation_id: The conversation that asked the question.
        message: The user's reply exactly as typed.

    Returns:
        The next state: another question, or the final verdict.
    """

    try:
        # Check the reply here first (1 to 500 characters), so the user gets
        # a clear message instead of an HTTP 422 from the API.
        body = JourneyMessage(message=message)
    except ValidationError as error:
        raise JourneyApiError(
            "Please type a shorter answer (up to 500 characters)."
        ) from error
    request = Request(
        _journey_url(f"{_conversation_path(conversation_id)}/messages"),
        data=body.model_dump_json().encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return _send(request, timeout=60)


def correct_journey_answer(
    conversation_id: str,
    fact_name: str,
    answer: str,
) -> JourneyResponse:
    """Correct a saved answer and ask the API to recheck every candidate."""

    try:
        body = JourneyCorrection(fact_name=fact_name, answer=answer)
    except ValidationError as error:
        raise JourneyApiError("Choose a known fact and enter a valid answer.") from error
    request = Request(
        _journey_url(f"{_conversation_path(conversation_id)}/corrections"),
        data=body.model_dump_json().encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return _send(request, timeout=60)


def get_journey_state(conversation_id: str) -> JourneyResponse | None:
    """Load a saved conversation, used to continue after a page refresh.

    Returns:
        The saved state, or None when the API has no such conversation
        (HTTP 404), for example after "forget" or a server restart.
    """

    request = Request(
        _journey_url(_conversation_path(conversation_id)),
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        return _send(request, timeout=10)
    except JourneyApiError as error:
        # 404 is a normal answer ("nothing saved"), not a failure.
        cause = error.__cause__
        if isinstance(cause, HTTPError) and cause.code == 404:
            return None
        raise


def forget_journey(conversation_id: str) -> None:
    """Delete the conversation's saved LangGraph checkpoint."""

    request = Request(
        _journey_url(_conversation_path(conversation_id)),
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


def _household_url(path: str = "") -> str:
    """Build a household API address from the configured base URL."""

    base_url = os.getenv("SCHEME_SAATHI_API_URL", "http://127.0.0.1:8000")
    return f"{base_url.rstrip('/')}/api/v1/household{path}"


def save_household_profile(
    conversation_id: str,
    return_code: str | None = None,
    *,
    memory_consent: bool = False,
) -> str:
    """Save the conversation's facts and return the return code."""

    body: dict[str, object] = {
        "conversation_id": conversation_id,
        "memory_consent": memory_consent,
    }
    if return_code:
        body["return_code"] = return_code
    request = Request(
        _household_url(),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        raise JourneyApiError(
            f"Could not save household profile (HTTP {error.code})."
        ) from error
    except (URLError, TimeoutError) as error:
        raise JourneyApiError(
            "Could not reach the API to save the household profile."
        ) from error
    code = result.get("return_code")
    if not code:
        raise JourneyApiError("The API did not return a return code.")
    return code


def load_household_profile(
    return_code: str,
    *,
    memory_consent: bool = False,
) -> dict | None:
    """Load a saved household profile. Returns None when the code is unknown."""

    request = Request(
        _household_url(
            f"/{quote(return_code.strip(), safe='')}"
            f"?memory_consent={str(memory_consent).lower()}"
        ),
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except HTTPError as error:
        if error.code == 404:
            return None
        raise JourneyApiError(
            f"Could not load household profile (HTTP {error.code})."
        ) from error
    except (URLError, TimeoutError) as error:
        raise JourneyApiError(
            "Could not reach the API to load the household profile."
        ) from error


def delete_household_profile(return_code: str) -> None:
    """Delete a household's saved profile by return code."""

    request = Request(
        _household_url(f"/{quote(return_code.strip(), safe='')}"),
        method="DELETE",
    )
    try:
        with urlopen(request, timeout=10):
            pass
    except HTTPError as error:
        if error.code == 404:
            return
        raise JourneyApiError(
            f"Could not delete household profile (HTTP {error.code})."
        ) from error
    except (URLError, TimeoutError) as error:
        raise JourneyApiError(
            "Could not reach the API to delete the household profile."
        ) from error


def forget_personal_data(
    conversation_id: str | None = None,
    return_code: str | None = None,
) -> None:
    """Delete journey data and household memory in one retryable request."""

    body = {
        key: value
        for key, value in {
            "conversation_id": conversation_id,
            "return_code": return_code,
        }.items()
        if value
    }
    if not body:
        raise JourneyApiError("No saved data was selected for deletion.")
    base_url = os.getenv("SCHEME_SAATHI_API_URL", "http://127.0.0.1:8000")
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/forget",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="DELETE",
    )
    try:
        with urlopen(request, timeout=15):
            pass
    except HTTPError as error:
        raise JourneyApiError(
            "Could not delete all saved data. Retry the forget action."
        ) from error
    except (URLError, TimeoutError) as error:
        raise JourneyApiError(
            "Could not reach the API to delete saved data."
        ) from error


def _application_request(
    conversation_id: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    reviewer_code: str | None = None,
) -> dict:
    """Send an application request and expose only a safe API message."""

    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if reviewer_code:
        headers["X-Reviewer-Code"] = reviewer_code
    request = Request(
        _journey_url(f"{_conversation_path(conversation_id)}{path}"),
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get("detail")
        except (json.JSONDecodeError, AttributeError):
            detail = None
        message = (
            detail if isinstance(detail, str)
            else f"The application API returned HTTP {error.code}."
        )
        raise ApplicationApiError(message) from error
    except (URLError, TimeoutError) as error:
        raise ApplicationApiError(
            "Could not reach the application API. Start the API and try again."
        ) from error
    except json.JSONDecodeError as error:
        raise ApplicationApiError(
            "The application API returned invalid data."
        ) from error
    if not isinstance(result, dict):
        raise ApplicationApiError("The application API returned invalid data.")
    return result


def assess_documents(
    conversation_id: str,
    scheme_id: str,
    documents: dict[str, str] | None = None,
    profile_name: str | None = None,
    document_metadata: dict[str, dict[str, str | None]] | None = None,
) -> dict:
    return _application_request(
        conversation_id,
        "/documents",
        method="POST",
        body={
            "scheme_id": scheme_id,
            "documents": documents or {},
            "profile_name": profile_name,
            "document_metadata": document_metadata or {},
        },
    )


def list_document_files(conversation_id: str) -> dict:
    return _application_request(conversation_id, "/documents/files")


def upload_document(
    conversation_id: str, document_id: str, file_name: str, content: bytes
) -> dict:
    """Send one file as a raw body; the API enforces type and the 20 MB cap."""

    request = Request(
        _journey_url(
            f"{_conversation_path(conversation_id)}/documents/files/"
            f"{quote(document_id, safe='')}"
        ),
        data=content,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/octet-stream",
            "X-File-Name": quote(file_name, safe=""),
        },
        method="PUT",
    )
    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get("detail")
        except (json.JSONDecodeError, AttributeError):
            detail = None
        raise ApplicationApiError(
            detail if isinstance(detail, str)
            else f"The upload failed with HTTP {error.code}."
        ) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ApplicationApiError(
            "Could not upload the file. Start the API and try again."
        ) from error


def fetch_document_file(
    conversation_id: str, document_id: str, reviewer_code: str | None = None
) -> bytes:
    """Download one stored file's bytes for the reviewer."""

    request = Request(
        _journey_url(
            f"{_conversation_path(conversation_id)}/documents/files/"
            f"{quote(document_id, safe='')}/content"
        ),
        headers={"X-Reviewer-Code": reviewer_code} if reviewer_code else {},
        method="GET",
    )
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get("detail")
        except (json.JSONDecodeError, AttributeError):
            detail = None
        raise ApplicationApiError(
            detail if isinstance(detail, str)
            else f"The file could not be loaded (HTTP {error.code})."
        ) from error
    except (URLError, TimeoutError) as error:
        raise ApplicationApiError("Could not load the file.") from error


def get_document_suggestion(conversation_id: str, document_id: str) -> dict:
    return _application_request(
        conversation_id, f"/documents/files/{quote(document_id, safe='')}/suggestion"
    )


def extract_document_suggestion(conversation_id: str, document_id: str) -> dict:
    return _application_request(
        conversation_id,
        f"/documents/files/{quote(document_id, safe='')}/extract",
        method="POST",
    )


def review_document_file(
    conversation_id: str,
    document_id: str,
    reviewer_name: str,
    note: str = "",
    reviewer_code: str | None = None,
) -> dict:
    return _application_request(
        conversation_id,
        f"/documents/files/{quote(document_id, safe='')}/review",
        method="POST",
        body={"reviewer_name": reviewer_name, "note": note},
        reviewer_code=reviewer_code,
    )


def remove_document_review(
    conversation_id: str, document_id: str, reviewer_code: str | None = None
) -> dict:
    return _application_request(
        conversation_id,
        f"/documents/files/{quote(document_id, safe='')}/review",
        method="DELETE",
        reviewer_code=reviewer_code,
    )


def delete_document_file(conversation_id: str, document_id: str) -> dict:
    return _application_request(
        conversation_id,
        f"/documents/files/{quote(document_id, safe='')}",
        method="DELETE",
    )


def _check_body(
    scheme_id: str | None,
    documents: dict[str, str] | None,
    profile_name: str | None,
    document_metadata: dict[str, dict[str, str | None]] | None,
) -> dict:
    body = {
        "documents": documents or {},
        "profile_name": profile_name,
        "document_metadata": document_metadata or {},
    }
    if scheme_id is not None:
        body["scheme_id"] = scheme_id
    return body


def check_documents_report(
    conversation_id: str,
    scheme_id: str,
    documents: dict[str, str] | None = None,
    profile_name: str | None = None,
    document_metadata: dict[str, dict[str, str | None]] | None = None,
) -> dict:
    return _application_request(
        conversation_id,
        "/documents/check",
        method="POST",
        body=_check_body(scheme_id, documents, profile_name, document_metadata),
    )


def document_readiness(
    conversation_id: str,
    documents: dict[str, str] | None = None,
    profile_name: str | None = None,
    document_metadata: dict[str, dict[str, str | None]] | None = None,
) -> dict:
    return _application_request(
        conversation_id,
        "/documents/readiness",
        method="POST",
        body=_check_body(None, documents, profile_name, document_metadata),
    )


def resolve_document_issue(
    conversation_id: str,
    scheme_id: str,
    document_id: str,
    issue_code: str,
    reason: str,
    documents: dict[str, str] | None = None,
    profile_name: str | None = None,
    document_metadata: dict[str, dict[str, str | None]] | None = None,
) -> dict:
    return _application_request(
        conversation_id,
        "/documents/resolutions",
        method="POST",
        body={
            **_check_body(scheme_id, documents, profile_name, document_metadata),
            "document_id": document_id,
            "issue_code": issue_code,
            "reason": reason,
        },
    )


def reopen_document_issue(
    conversation_id: str,
    scheme_id: str,
    document_id: str,
    issue_code: str,
    documents: dict[str, str] | None = None,
    profile_name: str | None = None,
    document_metadata: dict[str, dict[str, str | None]] | None = None,
) -> dict:
    return _application_request(
        conversation_id,
        "/documents/resolutions/reopen",
        method="POST",
        body={
            **_check_body(scheme_id, documents, profile_name, document_metadata),
            "document_id": document_id,
            "issue_code": issue_code,
        },
    )


def list_application_drafts(conversation_id: str) -> list[dict]:
    result = _application_request(conversation_id, "/drafts")
    drafts = result.get("drafts")
    if not isinstance(drafts, list) or not all(isinstance(item, dict) for item in drafts):
        raise ApplicationApiError("The application API returned invalid draft data.")
    return drafts


def create_application_draft(
    conversation_id: str,
    scheme_id: str,
    documents: dict[str, str],
    profile_name: str | None = None,
    document_metadata: dict[str, dict[str, str | None]] | None = None,
    form_values: dict[str, object] | None = None,
) -> dict:
    return _application_request(
        conversation_id,
        "/drafts",
        method="POST",
        body={
            "scheme_id": scheme_id,
            "documents": documents,
            "profile_name": profile_name,
            "document_metadata": document_metadata or {},
            "form_values": form_values or {},
        },
    )


def edit_application_draft(
    conversation_id: str,
    draft: dict,
) -> dict:
    payload = draft["draft"]
    return _application_request(
        conversation_id,
        f"/drafts/{quote(str(draft['draft_id']), safe='')}",
        method="PUT",
        body={
            "revision": draft["revision"],
            "applicant_reference": payload["applicant_reference"],
            "district": payload["district"],
        },
    )


def decide_application_draft(
    conversation_id: str,
    draft: dict,
    action: str,
) -> dict:
    return _application_request(
        conversation_id,
        f"/drafts/{quote(str(draft['draft_id']), safe='')}/approval",
        method="POST",
        body={
            "action": action,
            "revision": draft["revision"],
            "fingerprint": draft["fingerprint"],
        },
    )
