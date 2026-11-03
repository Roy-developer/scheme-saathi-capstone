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
from src.api.applications import (
    DocumentAssessmentRequest,
    DraftApprovalRequest,
    DraftCreateRequest,
    DraftEditRequest,
    call_application_tool,
)
from src.api.scheme_search import SchemePassage
from src.rules.data_provider import RulePackageProvider
from src.rules.models import HouseholdProfile
# This adapter calls the MCP tool and translates failures for the API layer.
from src.workflow.eligibility import (
    evaluate_eligibility,
)
from src.workflow.errors import MCPToolError
from src.workflow.application_gate import (
    application_gate_thread_id,
)
from src.workflow.intake import IntakeAgentError
from src.workflow.journey import (
    ApplicationTaskError,
    JourneyMessage,
    JourneyCorrection,
    JourneyNotWaitingError,
    JourneyRequest,
    JourneyResponse,
    build_journey_graph,
    correct_journey_answer,
    get_journey,
    resume_journey,
    run_journey,
    run_application_task,
)
from src.workflow.state import ApplicationOperation
from src.workflow.scheme_search import search_scheme_passages


logger = logging.getLogger(__name__)


async def _dispatch_application_task(
    request: Request,
    conversation_id: UUID,
    operation: ApplicationOperation,
    arguments: dict,
) -> dict:
    """Keep HTTP translation here; the supervisor owns specialist execution."""

    try:
        return await run_application_task(
            request.app.state.journey_graph, conversation_id, operation, arguments
        )
    except ApplicationTaskError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.detail
        ) from error


async def _application_state(
    request: Request,
    conversation_id: UUID,
    scheme_id: str,
) -> tuple[dict, HouseholdProfile]:
    """Require a saved, current eligible result and return its profile."""

    snapshot = await request.app.state.journey_graph.aget_state(
        {"configurable": {"thread_id": str(conversation_id)}}
    )
    values = snapshot.values
    if not values:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    verdict = values.get("candidate_verdicts", {}).get(scheme_id)
    if verdict is None or verdict.get("result") != "eligible":
        raise HTTPException(
            status_code=409,
            detail="This scheme has no current eligible result in this conversation.",
        )
    profile_data = values.get("profile")
    if not profile_data:
        raise HTTPException(
            status_code=409,
            detail="A completed profile is required for a mock application.",
        )
    try:
        profile = HouseholdProfile.model_validate(profile_data)
    except Exception as error:
        logger.exception("Saved journey profile could not be validated")
        raise HTTPException(status_code=409, detail="The saved profile is invalid.") from error
    return values, profile


async def _get_mock_draft(
    request: Request,
    conversation_id: UUID,
    draft_id: str,
) -> dict:
    record = await call_application_tool(
        request.app.state.mcp_client,
        "mock_portal",
        {
            "action": "get_draft",
            "journey_id": str(conversation_id),
            "draft_id": draft_id,
        },
    )
    if record.get("not_found"):
        raise HTTPException(
            status_code=404,
            detail="Draft not found for this conversation.",
        )
    return record


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
    application_db_path = Path(os.getenv(
        "SCHEME_SAATHI_APPLICATION_DB",
        str(PROJECT_ROOT / "data" / "runtime" / "applications.sqlite3"),
    ))
    application_db_path.parent.mkdir(parents=True, exist_ok=True)
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
            "SCHEME_SAATHI_APPLICATION_DB": str(application_db_path),
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


@app.get("/api/v1/info", tags=["service"])
def service_info() -> dict[str, str | bool]:
    """Return non-sensitive build metadata for shared-deployment diagnostics."""

    return {
        "name": "scheme-saathi-api",
        "api_version": app.version,
        "app_version": os.getenv("APP_VERSION", "development"),
        "deployed_ref": os.getenv("DEPLOYED_REF", "local"),
        "synthetic_only": True,
    }


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


@app.post(
    "/api/v1/journey/{conversation_id}/messages",
    response_model=JourneyResponse,
)
async def journey_message(
    conversation_id: UUID,
    journey_message: JourneyMessage,
    request: Request,
) -> JourneyResponse:
    """Answer the question a paused interview is waiting on.

    Returns the next question, or the verdict once intake is done.
    409 means the conversation is not waiting for an answer.
    """

    try:
        return await resume_journey(
            request.app.state.journey_graph,
            conversation_id,
            journey_message.message,
        )
    except JourneyNotWaitingError as error:
        raise HTTPException(
            status_code=409,
            detail="This conversation is not waiting for an answer.",
        ) from error
    except MCPToolError as error:
        logger.exception("A journey MCP tool failed")
        raise HTTPException(
            status_code=502,
            detail="A journey tool is unavailable.",
        ) from error


@app.post(
    "/api/v1/journey/{conversation_id}/corrections",
    response_model=JourneyResponse,
)
async def journey_correction(
    conversation_id: UUID,
    correction: JourneyCorrection,
    request: Request,
) -> JourneyResponse:
    """Correct a known answer and rerun the candidate scheme checks."""

    try:
        return await correct_journey_answer(
            request.app.state.journey_graph, conversation_id, correction
        )
    except JourneyNotWaitingError as error:
        raise HTTPException(
            status_code=409,
            detail="This conversation has no multi-scheme answers to correct.",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MCPToolError as error:
        logger.exception("A journey tool failed while applying a correction")
        raise HTTPException(
            status_code=502,
            detail="A journey tool is unavailable.",
        ) from error


@app.get(
    "/api/v1/journey/{conversation_id}",
    response_model=JourneyResponse,
)
async def journey_state(
    conversation_id: UUID,
    request: Request,
) -> JourneyResponse:
    """Return a saved conversation, e.g. to continue after a page refresh."""

    response = await get_journey(
        request.app.state.journey_graph,
        conversation_id,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return response


@app.post("/api/v1/journey/{conversation_id}/documents")
async def assess_application_documents(
    conversation_id: UUID,
    assessment: DocumentAssessmentRequest,
    request: Request,
) -> dict:
    """Check user-reported synthetic document metadata for an eligible scheme."""

    await _application_state(request, conversation_id, assessment.scheme_id)
    if assessment.scheme_id not in request.app.state.rule_packages:
        raise HTTPException(status_code=409, detail="This scheme is information-only.")
    try:
        result = await _dispatch_application_task(
            request, conversation_id, "check_documents",
            {
                "scheme_id": assessment.scheme_id,
                "documents": assessment.documents,
            },
        )
        return result
    except MCPToolError as error:
        logger.exception("Document checklist MCP tool failed")
        raise HTTPException(
            status_code=502,
            detail="The document checklist is unavailable.",
        ) from error


@app.post("/api/v1/journey/{conversation_id}/drafts")
async def create_application_draft(
    conversation_id: UUID,
    draft_request: DraftCreateRequest,
    request: Request,
) -> dict:
    """Create a mock draft only after current eligibility and demo documents pass."""

    await _application_state(
        request, conversation_id, draft_request.scheme_id
    )
    package = request.app.state.rule_packages.get(draft_request.scheme_id)
    if package is None:
        raise HTTPException(status_code=409, detail="This scheme is information-only.")
    try:
        created = await _dispatch_application_task(
            request, conversation_id, "create_draft",
            {
                "scheme_id": draft_request.scheme_id,
                "documents": draft_request.documents,
                "applicant_reference": draft_request.applicant_reference,
                "district": draft_request.district,
            },
        )
        return created
    except HTTPException:
        raise
    except MCPToolError as error:
        logger.exception("Mock application draft MCP tool failed")
        raise HTTPException(
            status_code=502,
            detail="The mock application service is unavailable.",
        ) from error


@app.get("/api/v1/journey/{conversation_id}/drafts")
async def list_application_drafts(
    conversation_id: UUID,
    request: Request,
) -> dict:
    """List saved mock drafts for a conversation after refresh."""

    try:
        return await call_application_tool(
            request.app.state.mcp_client,
            "mock_portal",
            {
                "action": "list_drafts",
                "journey_id": str(conversation_id),
            },
        )
    except MCPToolError as error:
        logger.exception("Could not list mock application drafts")
        raise HTTPException(
            status_code=502,
            detail="The mock application service is unavailable.",
        ) from error


@app.get("/api/v1/journey/{conversation_id}/drafts/{draft_id}")
async def get_application_draft(
    conversation_id: UUID,
    draft_id: str,
    request: Request,
) -> dict:
    """Load a persisted draft only within its owning conversation."""

    try:
        return await _get_mock_draft(request, conversation_id, draft_id)
    except MCPToolError as error:
        raise HTTPException(
            status_code=502,
            detail="The mock application service is unavailable.",
        ) from error


@app.put("/api/v1/journey/{conversation_id}/drafts/{draft_id}")
async def edit_application_draft(
    conversation_id: UUID,
    draft_id: str,
    edit: DraftEditRequest,
    request: Request,
) -> dict:
    """Save an allowlisted edit as a new revision and clear any old approval."""

    try:
        record = await _get_mock_draft(request, conversation_id, draft_id)
        if edit.revision != record["revision"]:
            raise HTTPException(status_code=409, detail="The draft revision is stale.")
        _, profile = await _application_state(
            request, conversation_id, record["scheme_id"]
        )
        package = request.app.state.rule_packages.get(record["scheme_id"])
        if (
            package is None
            or record["draft"].get("profile") != profile.model_dump(mode="json")
            or record["draft"].get("rule_package_version") != package.package_version
        ):
            raise HTTPException(
                status_code=409,
                detail="Answers or scheme rules changed. Create a new draft.",
            )
        edited = await _dispatch_application_task(
            request, conversation_id, "edit_draft",
            {
                "draft_id": draft_id,
                "revision": edit.revision,
                "applicant_reference": edit.applicant_reference,
                "district": edit.district,
            },
        )
        return edited
    except HTTPException:
        raise
    except MCPToolError as error:
        raise HTTPException(
            status_code=409,
            detail="The draft could not be edited; reload it and try again.",
        ) from error


@app.post("/api/v1/journey/{conversation_id}/drafts/{draft_id}/approval")
async def update_application_approval(
    conversation_id: UUID,
    draft_id: str,
    decision: DraftApprovalRequest,
    request: Request,
) -> dict:
    """Approve, reject or submit only the exact current synthetic draft."""

    try:
        record = await _get_mock_draft(request, conversation_id, draft_id)
        if (
            decision.revision != record["revision"]
            or decision.fingerprint != record["fingerprint"]
        ):
            raise HTTPException(
                status_code=409,
                detail="The draft changed. Reload and review it before continuing.",
            )
        if decision.action == "submit" and not record["approved"]:
            raise HTTPException(
                status_code=409,
                detail="Approve this exact draft before submitting it.",
            )
        if decision.action == "approve" and (
            record["rejected"] or record["receipt_id"]
        ):
            raise HTTPException(
                status_code=409,
                detail="This draft cannot be approved in its current state.",
            )
        if decision.action != "reject":
            _, profile = await _application_state(
                request, conversation_id, record["scheme_id"]
            )
            draft = record["draft"]
            package = request.app.state.rule_packages.get(record["scheme_id"])
            if package is None or draft.get("rule_package_version") != package.package_version:
                raise HTTPException(
                    status_code=409,
                    detail="Scheme rules changed. Create and review a new draft.",
                )
            if draft.get("profile") != profile.model_dump(mode="json"):
                raise HTTPException(
                    status_code=409,
                    detail="Your answers changed. Recheck eligibility and create a new draft.",
                )
        return await _dispatch_application_task(
            request, conversation_id, decision.action,
            {
                "draft_id": draft_id,
                "revision": decision.revision,
                "fingerprint": decision.fingerprint,
                "scheme_id": record["scheme_id"],
                "documents": {
                    item["document_id"]: item["status"]
                    for item in record["draft"].get("documents", [])
                },
            },
        )
    except HTTPException:
        raise
    except MCPToolError as error:
        logger.exception("Mock application approval MCP tool failed")
        raise HTTPException(
            status_code=502,
            detail="The mock application service is unavailable.",
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
    try:
        drafts = await call_application_tool(
            request.app.state.mcp_client,
            "mock_portal",
            {"action": "list_drafts", "journey_id": conversation_id},
        )
        await _dispatch_application_task(
            request, UUID(conversation_id), "delete_journey", {},
        )
        for draft in drafts.get("drafts", []):
            for revision in range(1, draft["revision"] + 1):
                thread_id = application_gate_thread_id(
                    conversation_id, draft["draft_id"], revision
                )
                await request.app.state.journey_checkpointer.adelete_thread(
                    thread_id
                )
    except MCPToolError as error:
        logger.exception("Could not clear mock application data")
        raise HTTPException(
            status_code=502,
            detail="The mock application service could not clear this session.",
        ) from error
    await request.app.state.journey_checkpointer.adelete_thread(conversation_id)
