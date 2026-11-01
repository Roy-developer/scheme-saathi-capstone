"""FastAPI entry point for Scheme Saathi."""

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
# Client connects to the MCP server; parameters explain how to launch stdio.
from mcp import Client, StdioServerParameters

from src.api.eligibility import (
    EligibilityRequest,
    EligibilityResponse,
)
from src.rules.data_provider import RulePackageProvider
# This adapter calls the MCP tool and translates failures for the API layer.
from src.workflow.eligibility import (
    EligibilityToolError,
    evaluate_eligibility,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Load rules and keep the MCP client alive for the API's lifetime."""

    # Validate rule packages before accepting requests; fail startup if rules
    # are missing or malformed.
    try:
        packages = RulePackageProvider().packages
    except Exception:
        logger.exception("Failed to load scheme rule packages during API startup")
        raise

    # Store known schemes so request handlers can reject unknown IDs early.
    application.state.rule_packages = packages
    # Build an operational summary without including applicant information.
    package_details = ", ".join(
        f"{scheme_id} v{package.package_version} ({len(package.rules)} rules)"
        for scheme_id, package in sorted(packages.items())
    )
    logger.info(
        "Loaded %d scheme rule package(s): %s",
        len(packages),
        package_details,
    )

    # Find the project root so the child process can import the `src` package.
    project_root = Path(__file__).resolve().parents[2]
    # Launch the MCP server with the same Python executable as this API.
    server_parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_servers.rule_engine"],
        cwd=project_root,
    )
    # Entering Client starts the child MCP process and opens the stdio link.
    try:
        async with Client(server_parameters) as mcp_client:
            # Make the connected client available to API request handlers.
            application.state.mcp_client = mcp_client
            logger.info("Connected to the local MCP rule-engine server")
            # FastAPI serves requests inside this context. On shutdown, leaving
            # it closes the client and stops its child process.
            yield
    except Exception:
        logger.exception("Failed to connect to the MCP rule-engine server")
        raise


app = FastAPI(
    title="Scheme Saathi API",
    description=(
        "Deterministic synthetic mock eligibility API. "
        "It does not decide real applications or submit to government services."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Report API health."""

    return {"status": "ok"}


@app.post(
    "/api/v1/schemes/{scheme_id}/evaluate",
    response_model=EligibilityResponse,
)
async def evaluate(
    scheme_id: str,
    eligibility_request: EligibilityRequest,
    http_request: Request,
) -> EligibilityResponse:
    """Evaluate a scheme by calling the MCP rule-engine tool."""

    # Reject unknown scheme IDs before spending a tool call.
    if scheme_id not in http_request.app.state.rule_packages:
        raise HTTPException(status_code=404, detail="Unknown scheme")
    # Send the validated profile through MCP and return the tool's verdict.
    try:
        return await evaluate_eligibility(
            http_request.app.state.mcp_client,
            scheme_id,
            eligibility_request,
        )
    except EligibilityToolError as error:
        # Return a service error, never a made-up or fixture-based verdict.
        logger.exception("MCP eligibility tool failed for scheme %s", scheme_id)
        raise HTTPException(
            status_code=502,
            detail="The eligibility tool is unavailable.",
        ) from error
