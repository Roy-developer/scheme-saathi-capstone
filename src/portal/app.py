"""HTTP boundary for the isolated synthetic mock portal and its SQLite store."""

import hashlib
import hmac
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.config import PORTAL_HEALTH_PROOF_MESSAGE
from src.portal.repository import PortalInput, _portal_action


app = FastAPI(
    title="Scheme Saathi Synthetic Portal",
    description="A local-only mock application service; it is not a government portal.",
    version="0.1.0",
)


@app.exception_handler(RequestValidationError)
async def invalid_request(
    _request: Request, _error: RequestValidationError
) -> JSONResponse:
    """Return a structured schema error without echoing submitted values."""

    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "invalid_input",
                "message": "Request did not match the portal schema.",
            }
        },
    )


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Confirm readiness only to the API process that launched this service."""

    expected_token = os.getenv("SCHEME_SAATHI_PORTAL_HEALTH_TOKEN")
    supplied_token = request.headers.get("X-Scheme-Saathi-Startup-Token", "")
    if not expected_token or not hmac.compare_digest(
        supplied_token, expected_token
    ):
        raise HTTPException(status_code=404, detail="Not found.")
    proof = hmac.new(
        expected_token.encode("utf-8"),
        PORTAL_HEALTH_PROOF_MESSAGE,
        hashlib.sha256,
    ).hexdigest()
    return {"status": "ok", "proof": proof}


@app.post("/internal/actions")
async def perform_action(request: PortalInput) -> dict[str, object]:
    """Run one validated action against the portal service's private database."""

    try:
        return _portal_action(request.model_dump(mode="json", exclude_none=True))
    except ValidationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_input",
                "message": "Portal action did not match the expected schema.",
            },
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_input", "message": str(error)},
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict", "message": str(error)},
        ) from error
