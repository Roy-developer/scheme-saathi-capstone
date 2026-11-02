"""FastAPI entry point for Scheme Saathi."""

from contextlib import asynccontextmanager
import logging
import os
import sys
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID

import aiosqlite
from fastapi import FastAPI, HTTPException, Query, Request
# Client connects to the MCP server; parameters explain how to launch stdio.
from mcp import Client, StdioServerParameters
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.config import PROJECT_ROOT
from src.api.eligibility import EligibilityResponse
from src.api.scheme_search import SchemePassage
from src.rules.data_provider import RulePackageProvider
from src.rules.models import HouseholdProfile
# This adapter calls the MCP tool and translates failures for the API layer.
from src.workflow.eligibility import (
    evaluate_eligibility,
)
from src.workflow.errors import MCPToolError
from src.workflow.intake import IntakeAgentError
from src.workflow.journey import (
    JourneyRequest,
    JourneyResponse,
    build_journey_graph,
    run_journey,
)
from src.workflow.scheme_search import search_scheme_passages


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

    checkpoint_path = Path(
        os.getenv(
            "SCHEME_SAATHI_CHECKPOINT_DB",
            str(PROJECT_ROOT / "data" / "runtime" / "journey.sqlite3"),
        )
    )
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_connection = await aiosqlite.connect(checkpoint_path)
    checkpointer = AsyncSqliteSaver(checkpoint_connection)
    await checkpointer.setup()

    # Find the project root so the child process can import the `src` package.
    project_root = PROJECT_ROOT
    # Launch the MCP server with the same Python executable as this API.
    server_parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_servers.saathi_mcp_server"],
        env={
            "SCHEME_SAATHI_DISABLE_DOTENV": "1",
            "SCHEME_SAATHI_RERANKER": "openrouter",
            "OPENBLAS_NUM_THREADS": "1",
            **{
                name: value
                for name in (
                    "OPENROUTER_API_KEY_FREE",
                    "OPEN_ROUTER_FREE",
                    "OPENROUTER_EMBEDDING_MODEL",
                )
                if (value := os.getenv(name)) is not None
            },
        },
        cwd=project_root,
    )
    # Entering Client starts the child MCP process and opens the stdio link.
    try:
        async with Client(server_parameters) as mcp_client:
            # Make the connected client available to API request handlers.
            application.state.mcp_client = mcp_client
            application.state.journey_checkpointer = checkpointer
            application.state.journey_graph = build_journey_graph(
                mcp_client,
                packages,
                checkpointer=checkpointer,
            )
            logger.info("Connected to the local Saathi MCP server")
            # FastAPI serves requests inside this context. On shutdown, leaving
            # it closes the client and stops its child process.
            yield
    except Exception:
        logger.exception("Failed to connect to the Saathi MCP server")
        raise
    finally:
        await checkpoint_connection.close()


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
    eligibility_request: HouseholdProfile,
    http_request: Request,
) -> EligibilityResponse:
    """Evaluate any loaded scheme by calling the MCP rule-engine tool."""

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
    except MCPToolError as error:
        # Return a service error, never a made-up or fixture-based verdict.
        logger.exception("MCP eligibility tool failed for scheme %s", scheme_id)
        raise HTTPException(
            status_code=502,
            detail="The eligibility tool is unavailable.",
        ) from error


@app.get(
    "/api/v1/schemes/search",
    response_model=list[SchemePassage],
)
async def search_schemes(
    request: Request,
    query: str,
    jurisdiction: str | None = None,
    language: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
) -> list[SchemePassage]:
    """Search scheme passages through the shared Saathi MCP server."""

    if not query.strip():
        raise HTTPException(status_code=422, detail="Search query cannot be empty")

    try:
        return await search_scheme_passages(
            request.app.state.mcp_client,
            query,
            jurisdiction=jurisdiction,
            language=language,
            limit=limit,
        )
    except MCPToolError as error:
        logger.exception("MCP scheme search failed")
        raise HTTPException(
            status_code=502,
            detail="The scheme search tool is unavailable.",
        ) from error




@app.post("/api/v1/journey", response_model=JourneyResponse)
async def journey(
    journey_request: JourneyRequest,
    request: Request,
) -> JourneyResponse:
    """Run one orchestrated discovery or synthetic eligibility step."""

    try:
        return await run_journey(
            request.app.state.journey_graph,
            journey_request,
        )
    except MCPToolError as error:
        logger.exception("A journey MCP tool failed")
        raise HTTPException(
            status_code=502,
            detail="A journey tool is unavailable.",
        ) from error
    except IntakeAgentError as error:
        logger.exception("The intake agent failed")
        raise HTTPException(
            status_code=502,
            detail="The intake agent is unavailable.",
        ) from error


@app.delete("/api/v1/journey/{conversation_id}", status_code=204)
async def forget_journey(conversation_id: str, request: Request) -> None:
    """Delete the synthetic conversation's persisted graph checkpoints."""

    try:
        UUID(conversation_id)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail="conversation_id must be a UUID.",
        ) from error
    await request.app.state.journey_checkpointer.adelete_thread(conversation_id)
