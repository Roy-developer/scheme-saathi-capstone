"""FastAPI entry point for Scheme Saathi."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from datetime import date
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
from langgraph.store.sqlite.aio import AsyncSqliteStore

from src.config import (
    PORTAL_URL,
    PROJECT_ROOT,
    openrouter_chat_settings,
    portal_database_path,
    test_rule_package_directory,
)
from src.api.database_backup import DatabaseBackups
from src.api.portal_service import start_portal_service, stop_portal_service
from src.api.eligibility import EligibilityResponse
from src.api.applications import (
    DocumentAssessmentRequest,
    document_input_fingerprint,
    DraftApprovalRequest,
    DraftCreateRequest,
    DraftEditRequest,
    call_application_tool,
    check_and_bind_documents,
)
from src.api.scheme_search import SchemePassage
from src.documents.forms import build_form_fields, load_mock_form_snapshot
from src.rules.facts import HouseholdProfile
from src.rules.bundles import bundle_fingerprint
# This adapter calls the MCP tool and translates failures for the API layer.
from src.workflow.eligibility import (
    evaluate_eligibility,
)
from src.workflow.errors import MCPToolError
from src.workflow.application_gate import (
    application_gate_thread_id,
)
from src.llm_client import DEFAULT_CHAT_MODEL, openrouter_chat_model
from src.workflow.intake import IntakeAgentError
from src.workflow.conversation_budget import BUDGET_NAMESPACE
from src.workflow.household_memory import (
    HOUSEHOLD_NAMESPACE,
    generate_return_code,
    load_household,
    load_household_locale,
    normalize_return_code,
    save_household,
)
from src.workflow.journey import (
    confirmed_answers,
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
from src.mcp_servers.service_routing import (
    SERVICE_TOOLS,
    ServiceClientRouter,
    ToolClient,
)
from src.mcp_servers.rule_data import get_active_rule_data
from src.observability.metrics import (
    observe_duration,
    record_conversation,
    record_evaluation,
    record_new_verdicts,
    record_question,
    record_verdict,
    record_waiting_approvals_change,
)
from src.observability.telemetry import configure_telemetry


logger = logging.getLogger(__name__)


def _tool_failure(
    detail: str, log_message: str | None = None, *log_args: object, status_code: int = 502,
) -> HTTPException:
    """Build the HTTP error for a failed MCP tool call.

    Call it inside ``except MCPToolError``; when ``log_message`` is given the
    failure is logged with its traceback first. The detail is a short, safe
    message: raw tool errors are never shown to the user.
    """

    if log_message is not None:
        logger.exception(log_message, *log_args)
    return HTTPException(status_code=status_code, detail=detail)


def _bundle_fingerprint(request: Request, scheme_id: str) -> str:
    """Return exact active rule, registry and bundle version dependencies."""

    bundle = getattr(request.app.state, "rule_bundles", {}).get(scheme_id)
    if bundle is None:
        return ""
    return bundle_fingerprint(bundle)


def _confirmed_form_values(
    request: Request,
    scheme_id: str,
    typed_facts: dict[str, object] | None,
    extra_values: dict[str, object] | None = None,
    profile: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Return exact confirmed values and a localized, data-driven form preview."""

    snapshot = load_mock_form_snapshot(
        scheme_id, request.app.state.fact_registry,
        bundle=request.app.state.rule_bundles.get(scheme_id),
    )
    if snapshot.mapping is None:
        return {}, {
            "status": "unavailable",
            "notice": snapshot.notice,
            "missing_fields": [],
            "fields": [],
        }
    store = None
    if typed_facts is None:
        bundle = request.app.state.rule_bundles.get(scheme_id)
        facts = {}
        for fact_id in (bundle.fact_ids if bundle else ()):
            value = (profile or {}).get(fact_id)
            facts[fact_id] = (
                request.app.state.fact_registry.get(fact_id).validate_value(value)
                if value is not None
                else None
            )
    else:
        store = HouseholdProfile.from_wire(typed_facts, request.app.state.fact_registry)
        facts = {
            fact_id: state.value if state.status == "known" else None
            for fact_id, state in store.facts.items()
        }
    fields, missing = build_form_fields(
        snapshot, request.app.state.fact_registry, facts, extra_values,
        bundle=request.app.state.rule_bundles.get(scheme_id),
        typed_store=store,
    )
    preview = {
        "status": snapshot.mapping.status,
        "form_version": snapshot.mapping.form_version,
        "mapping_fingerprint": snapshot.fingerprint,
        "notice": snapshot.notice,
        "missing_fields": missing,
        "fields": [
            {
                **field.model_dump(mode="json"),
                "value": fields.get(field.field_id),
            }
            for field in snapshot.mapping.fields
        ],
    }
    return fields, preview


def _form_mapping_fingerprint(request: Request, scheme_id: str) -> str | None:
    """Return the active mapping hash or fail closed when it is invalid."""

    snapshot = load_mock_form_snapshot(
        scheme_id, request.app.state.fact_registry,
        bundle=request.app.state.rule_bundles.get(scheme_id),
    )
    return snapshot.fingerprint if snapshot.mapping is not None else None


def _portal_reader(request: Request, conversation_id: UUID | str) -> ToolClient:
    """Bind read-only portal access to the journey from the trusted route."""

    return request.app.state.mcp_client.for_actor(
        "api_read", str(conversation_id)
    )


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
) -> tuple[dict, dict[str, object]]:
    """Require a saved, current eligible result and return its confirmed answers."""

    try:
        current = await get_journey(request.app.state.journey_graph, conversation_id)
    except MCPToolError as error:
        raise _tool_failure("The mock application service is unavailable.") from error
    if current is not None and current.status == "invalid_input":
        raise HTTPException(status_code=409, detail=current.message)
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
    if not profile_data and not (
        values.get("registry_intake") and values.get("typed_facts")
    ):
        raise HTTPException(
            status_code=409,
            detail="A completed profile is required for a mock application.",
        )
    try:
        profile = confirmed_answers(values)
    except Exception as error:
        logger.exception("Saved journey profile could not be validated")
        raise HTTPException(status_code=409, detail="The saved profile is invalid.") from error
    return values, profile


async def _get_mock_draft(
    request: Request,
    conversation_id: UUID,
    draft_id: str,
) -> dict:
    await get_journey(request.app.state.journey_graph, conversation_id)
    record = await call_application_tool(
        _portal_reader(request, conversation_id),
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


def _awaiting_approval(record: dict) -> bool:
    return not record.get("approved") and not record.get("rejected") and not record.get("receipt_id")


def _track_waiting_approval(before: dict | None, after: dict) -> None:
    previous = _awaiting_approval(before) if before is not None else False
    record_waiting_approvals_change(int(_awaiting_approval(after)) - int(previous))


def _public_application_record(record: dict) -> dict:
    """Keep the one-use portal authorization inside trusted backend code."""

    public = {key: value for key, value in record.items() if key != "approval_token"}
    if isinstance(public.get("drafts"), list):
        public["drafts"] = [
            {key: value for key, value in item.items() if key != "approval_token"}
            for item in public["drafts"]
            if isinstance(item, dict)
        ]
    return public


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Load rules and keep four isolated MCP clients and a portal alive."""

    # Validate rule packages before accepting requests; fail startup if rules
    # are missing or malformed.
    try:
        get_active_rule_data.cache_clear()
        rule_data = get_active_rule_data()
        packages = rule_data.packages
    except Exception:
        logger.exception("Failed to load scheme rule packages during API startup")
        raise

    # Store known schemes so request handlers can reject unknown IDs early.
    application.state.rule_packages = packages
    application.state.rule_bundles = rule_data.bundles
    application.state.fact_registry = rule_data.registry
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
    # Bring back saved databases before anything opens them.
    backups = DatabaseBackups.from_environment(
        (checkpoint_path, portal_database_path())
    )
    if backups is not None:
        await asyncio.to_thread(backups.restore)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_connection = await aiosqlite.connect(checkpoint_path)
    checkpointer = AsyncSqliteSaver(checkpoint_connection)
    await checkpointer.setup()
    # Same SQLite file, own autocommit connection (as AsyncSqliteStore's
    # from_conn_string opens it): per-conversation data survives restarts.
    store_connection = await aiosqlite.connect(checkpoint_path, isolation_level=None)
    store = AsyncSqliteStore(store_connection)
    await store.setup()

    server_modules = {
        "rule-engine": "src.mcp_servers.rule_engine_server",
        "schemes-kb": "src.mcp_servers.schemes_kb_server",
        "doc-check": "src.mcp_servers.doc_check_server",
        "mock-portal": "src.mcp_servers.mock_portal_server",
    }
    portal_process = None
    backup_task = (
        asyncio.create_task(backups.save_regularly()) if backups is not None else None
    )
    try:
        portal_db_path = portal_database_path()
        portal_process = start_portal_service(portal_db_path)
        async with AsyncExitStack() as client_stack:
            clients: dict[str, ToolClient] = {}
            for service_name, module_name in server_modules.items():
                service_environment = {
                    "SCHEME_SAATHI_DISABLE_DOTENV": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                }
                if service_name == "schemes-kb":
                    service_environment["SCHEME_SAATHI_RERANKER"] = "openrouter"
                    if embedding_credential := (
                        os.getenv("OPENROUTER_API_KEY_FREE")
                        or os.getenv("OPEN_ROUTER_FREE")
                    ):
                        service_environment["OPENROUTER_API_KEY_FREE"] = (
                            embedding_credential
                        )
                    if embedding_model := os.getenv("OPENROUTER_EMBEDDING_MODEL"):
                        service_environment["OPENROUTER_EMBEDDING_MODEL"] = (
                            embedding_model
                        )
                elif service_name == "mock-portal":
                    service_environment["SCHEME_SAATHI_PORTAL_URL"] = PORTAL_URL
                if test_packages := test_rule_package_directory():
                    service_environment["SCHEME_SAATHI_TEST_RULE_PACKAGE_DIR"] = (
                        str(test_packages)
                    )
                    service_environment["PYTEST_CURRENT_TEST"] = os.environ[
                        "PYTEST_CURRENT_TEST"
                    ]
                server_parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", module_name],
                    env=service_environment,
                    cwd=PROJECT_ROOT,
                )
                client = await client_stack.enter_async_context(
                    Client(server_parameters)
                )
                discovered = await client.list_tools()
                discovered_names = {tool.name for tool in discovered.tools}
                if discovered_names != SERVICE_TOOLS[service_name]:
                    missing_tools = SERVICE_TOOLS[service_name] - discovered_names
                    unexpected_tools = (
                        discovered_names - SERVICE_TOOLS[service_name]
                    )
                    raise RuntimeError(
                        f"MCP service {service_name} tool inventory mismatch; "
                        f"missing={sorted(missing_tools)}, "
                        f"unexpected={sorted(unexpected_tools)}"
                    )
                clients[service_name] = client
            mcp_client = ServiceClientRouter(clients)
            application.state.mcp_client = mcp_client
            application.state.mcp_services = tuple(server_modules)
            application.state.journey_checkpointer = checkpointer
            application.state.journey_store = store
            api_key, model_name = openrouter_chat_settings(DEFAULT_CHAT_MODEL)
            # No key: every agent uses its deterministic (no-AI) path.
            model_provider = (
                openrouter_chat_model(api_key, model_name) if api_key else None
            )
            application.state.journey_graph = build_journey_graph(
                mcp_client,
                packages,
                model_provider=model_provider,
                eligibility_model_provider=model_provider,
                checkpointer=checkpointer,
                store=store,
                fact_registry=rule_data.registry,
                rule_bundles=rule_data.bundles,
            )
            logger.info(
                "Connected to four purpose-specific MCP services and the mock portal"
            )
            yield
    except Exception:
        logger.exception("Failed to connect to the Saathi MCP services")
        raise
    finally:
        if backup_task is not None:
            backup_task.cancel()
            with suppress(asyncio.CancelledError):
                await backup_task
        if portal_process is not None:
            stop_portal_service(portal_process)
        await checkpoint_connection.close()
        await store_connection.close()
        if backups is not None:
            await asyncio.to_thread(backups.save)


configure_telemetry()

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
    eligibility_request: dict[str, object],
    http_request: Request,
) -> EligibilityResponse:
    """Evaluate any loaded scheme by calling the MCP rule-engine tool."""

    # Reject unknown scheme IDs before spending a tool call.
    if scheme_id not in http_request.app.state.rule_packages:
        raise HTTPException(status_code=404, detail="Unknown scheme")
    bundle = http_request.app.state.rule_bundles[scheme_id]
    try:
        HouseholdProfile.from_answers(
            eligibility_request, http_request.app.state.fact_registry,
        )
        answers = HouseholdProfile.from_answers(
            {
                fact_id: value for fact_id, value in eligibility_request.items()
                if fact_id in bundle.fact_ids
            },
            http_request.app.state.fact_registry,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=422, detail="Some answers are missing or invalid.",
        ) from error
    # Send the validated answers through MCP and return the tool's verdict.
    try:
        with observe_duration("evaluate"):
            result = await evaluate_eligibility(
                http_request.app.state.mcp_client,
                scheme_id,
                answers,
            )
        record_evaluation(scheme_id, source="api")
        record_verdict(scheme_id, result.result)
        return result
    except MCPToolError as error:
        # Return a service error, never a made-up or fixture-based verdict.
        raise _tool_failure(
            "The eligibility tool is unavailable.",
            "MCP eligibility tool failed for scheme %s", scheme_id,
        ) from error


async def _mark_changed_document_reports(
    request: Request,
    conversation_id: UUID,
    response: JourneyResponse,
) -> JourneyResponse:
    """Compare saved document reports with each checklist's current file snapshot."""

    if not response.document_assessments:
        return response
    snapshot = await request.app.state.journey_graph.aget_state(
        {"configurable": {"thread_id": str(conversation_id)}}
    )
    values = snapshot.values
    if not (values.get("profile") or values.get("typed_facts")):
        return response.model_copy(update={
            "document_assessments": {
                scheme_id: {
                    **assessment,
                    "report_stale": True,
                    "report_status": "stale",
                }
                for scheme_id, assessment in response.document_assessments.items()
            }
        })
    try:
        profile = confirmed_answers(values)
    except ValueError:
        return response.model_copy(update={
            "document_assessments": {
                scheme_id: {
                    **assessment,
                    "report_stale": True,
                    "report_status": "stale",
                }
                for scheme_id, assessment in response.document_assessments.items()
            }
        })
    inputs = values.get("document_input_reports", {})
    updated: dict[str, dict] = {}
    document_client = request.app.state.mcp_client.for_actor("documents")
    dependency_client = request.app.state.mcp_client.for_actor(
        "dependency_control", str(conversation_id)
    )
    for scheme_id, saved in response.document_assessments.items():
        prior = inputs.get(scheme_id)
        if prior is None:
            updated[scheme_id] = {
                **saved, "report_stale": True, "report_status": "stale"
            }
            continue
        try:
            current = await check_and_bind_documents(
                call_application_tool,
                document_client,
                dependency_client,
                journey_id=str(conversation_id),
                scheme_id=scheme_id,
                documents=prior.get("documents", {}),
                profile_name=prior.get("profile_name"),
                profile_date_of_birth=(
                    profile.get("date_of_birth")
                ),
                document_metadata=prior.get("document_metadata", {}),
                typed_facts=values.get("typed_facts"),
                profile_conditions={
                    "is_widow": profile.get("is_widow"),
                    "bpl_card_shown": profile.get("bpl_card_shown"),
                },
                bundle_fingerprint=_bundle_fingerprint(request, scheme_id),
            )
        except MCPToolError:
            updated[scheme_id] = {
                **saved, "report_stale": True, "report_status": "stale"
            }
            continue
        is_stale = (
            current.get("active_fingerprint")
            != saved.get("active_fingerprint")
            or current["document_dependency_version"]
            != saved.get("document_dependency_version")
        )
        updated[scheme_id] = {
            **saved,
            "report_stale": is_stale,
            "report_status": "stale" if is_stale else "current",
            "current_document_dependency_version": current[
                "document_dependency_version"
            ],
        }
    return response.model_copy(update={"document_assessments": updated})


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
        passages = await search_scheme_passages(
            request.app.state.mcp_client,
            query,
            jurisdiction=jurisdiction,
            language=language,
            limit=limit,
        )
        return [
            passage.model_copy(update={
                "eligible_for_mock_flow": passage.scheme_id
                in request.app.state.rule_packages
            })
            for passage in passages
        ]
    except MCPToolError as error:
        raise _tool_failure(
            "The scheme search tool is unavailable.",
            "MCP scheme search failed",
        ) from error




def _record_journey_metrics(endpoint: str, result: JourneyResponse) -> None:
    """Record conversation, question, and verdict counters for a journey reply."""

    record_conversation(endpoint)
    if result.question is not None:
        scheme_id = None
        if result.eligibility_result is not None:
            scheme_id = result.eligibility_result.scheme_id
        elif result.candidate_scheme_ids:
            scheme_id = result.candidate_scheme_ids[0]
        record_question(scheme_id)
    verdicts = {
        scheme_id: verdict.result
        for scheme_id, verdict in result.eligibility_results.items()
    }
    if not verdicts and result.eligibility_result is not None:
        verdicts = {
            result.eligibility_result.scheme_id: result.eligibility_result.result,
        }
    record_new_verdicts(str(result.conversation_id), verdicts)


@app.post("/api/v1/journey", response_model=JourneyResponse)
async def journey(
    journey_request: JourneyRequest,
    request: Request,
) -> JourneyResponse:
    """Run one orchestrated discovery or synthetic eligibility step."""

    try:
        with observe_duration("journey"):
            result = await run_journey(
                request.app.state.journey_graph,
                journey_request,
            )
        result = result.model_copy(update={
            "passages": [
                passage.model_copy(update={
                    "eligible_for_mock_flow": passage.scheme_id
                    in request.app.state.rule_packages
                })
                for passage in result.passages
            ],
        })
        _record_journey_metrics("journey", result)
        return result
    except MCPToolError as error:
        raise _tool_failure(
            "A journey tool is unavailable.",
            "A journey MCP tool failed",
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
        with observe_duration("journey_message"):
            result = await resume_journey(
                request.app.state.journey_graph,
                conversation_id,
                journey_message.message,
            )
        _record_journey_metrics("journey_message", result)
        return result
    except JourneyNotWaitingError as error:
        raise HTTPException(
            status_code=409,
            detail="This conversation is not waiting for an answer.",
        ) from error
    except MCPToolError as error:
        raise _tool_failure(
            "A journey tool is unavailable.",
            "A journey MCP tool failed",
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
            detail="This conversation has no confirmed answers to correct.",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MCPToolError as error:
        raise _tool_failure(
            "A journey tool is unavailable.",
            "A journey tool failed while applying a correction",
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

    try:
        response = await get_journey(
            request.app.state.journey_graph,
            conversation_id,
        )
    except MCPToolError as error:
        raise _tool_failure("A journey tool is unavailable.") from error
    if response is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return await _mark_changed_document_reports(
        request, conversation_id, response
    )


@app.post("/api/v1/journey/{conversation_id}/documents")
async def assess_application_documents(
    conversation_id: UUID,
    assessment: DocumentAssessmentRequest,
    request: Request,
) -> dict:
    """Check user-reported synthetic document metadata for an eligible scheme."""

    values, profile = await _application_state(
        request, conversation_id, assessment.scheme_id
    )
    if assessment.scheme_id not in request.app.state.rule_packages:
        raise HTTPException(status_code=409, detail="This scheme is information-only.")
    try:
        result = await _dispatch_application_task(
            request, conversation_id, "check_documents",
            {
                "scheme_id": assessment.scheme_id,
                "documents": assessment.documents,
                "profile_name": assessment.profile_name,
                "profile_date_of_birth": (
                    profile.get("date_of_birth")
                ),
                "document_metadata": {
                    document_id: metadata.model_dump(mode="json")
                    for document_id, metadata in assessment.document_metadata.items()
                },
                "typed_facts": values.get("typed_facts"),
            },
        )
        _, result["form_preview"] = _confirmed_form_values(
            request, assessment.scheme_id, values.get("typed_facts"),
            profile=profile,
        )
        return result
    except MCPToolError as error:
        raise _tool_failure(
            "The document checklist is unavailable.",
            "Document checklist MCP tool failed",
        ) from error


@app.post("/api/v1/journey/{conversation_id}/drafts")
async def create_application_draft(
    conversation_id: UUID,
    draft_request: DraftCreateRequest,
    request: Request,
) -> dict:
    """Create a mock draft only after current eligibility and demo documents pass."""

    values, profile = await _application_state(
        request, conversation_id, draft_request.scheme_id
    )
    package = request.app.state.rule_packages.get(draft_request.scheme_id)
    if package is None:
        raise HTTPException(status_code=409, detail="This scheme is information-only.")
    assessment = values.get("document_assessments", {}).get(
        draft_request.scheme_id, {}
    )
    document_metadata = {
        document_id: metadata.model_dump(mode="json", exclude_none=True)
        for document_id, metadata in draft_request.document_metadata.items()
    }
    expected_report = document_input_fingerprint(
        draft_request.scheme_id,
        draft_request.documents,
        draft_request.profile_name,
        date.fromisoformat(profile["date_of_birth"]) if profile.get("date_of_birth") else None,
        document_metadata,
        assessment.get("checklist_fingerprint", ""),
        assessment.get("evidence_fingerprint", ""),
        assessment.get("active_fingerprint", ""),
        {
            "is_widow": profile.get("is_widow"),
            "bpl_card_shown": profile.get("bpl_card_shown"),
        },
        values.get("typed_facts"),
        _bundle_fingerprint(request, draft_request.scheme_id),
    )
    try:
        _, form_preview = _confirmed_form_values(
            request,
            draft_request.scheme_id,
            values.get("typed_facts"),
            draft_request.form_values,
            profile,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail="The active synthetic form mapping is unavailable.",
        ) from error
    if form_preview["status"] == "unavailable":
        raise HTTPException(
            status_code=409,
            detail="The active synthetic form mapping is unavailable.",
        )
    if form_preview["missing_fields"]:
        raise HTTPException(
            status_code=422,
            detail="Confirm missing registered facts or complete required synthetic form fields.",
        )
    if (
        assessment.get("status") != "checklist_complete"
        or assessment.get("profile_dependency_version")
        != values.get("dependency_version", 0)
        or assessment.get("input_fingerprint") != expected_report
    ):
        raise HTTPException(
            status_code=409,
            detail="Recheck the documents against the current confirmed profile.",
        )
    try:
        created = await _dispatch_application_task(
            request, conversation_id, "create_draft",
            {
                "scheme_id": draft_request.scheme_id,
                "documents": draft_request.documents,
                "profile_name": draft_request.profile_name,
                "profile_date_of_birth": (
                    profile.get("date_of_birth")
                ),
                "document_metadata": document_metadata,
                "typed_facts": values.get("typed_facts"),
                "form_values": draft_request.form_values,
                "applicant_reference": draft_request.applicant_reference,
                "district": draft_request.district,
            },
        )
        _track_waiting_approval(None, created)
        return _public_application_record(created)
    except HTTPException:
        raise
    except MCPToolError as error:
        raise _tool_failure(
            "The mock application service is unavailable.",
            "Mock application draft MCP tool failed",
        ) from error


@app.get("/api/v1/journey/{conversation_id}/drafts")
async def list_application_drafts(
    conversation_id: UUID,
    request: Request,
) -> dict:
    """List saved mock drafts for a conversation after refresh."""

    try:
        await get_journey(request.app.state.journey_graph, conversation_id)
        result = await call_application_tool(
            _portal_reader(request, conversation_id),
            "mock_portal",
            {
                "action": "list_drafts",
                "journey_id": str(conversation_id),
            },
        )
        return _public_application_record(result)
    except MCPToolError as error:
        raise _tool_failure(
            "The mock application service is unavailable.",
            "Could not list mock application drafts",
        ) from error


@app.get("/api/v1/journey/{conversation_id}/drafts/{draft_id}")
async def get_application_draft(
    conversation_id: UUID,
    draft_id: str,
    request: Request,
) -> dict:
    """Load a persisted draft only within its owning conversation."""

    try:
        return _public_application_record(
            await _get_mock_draft(request, conversation_id, draft_id)
        )
    except MCPToolError as error:
        raise _tool_failure("The mock application service is unavailable.") from error


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
            or record["draft"].get("profile") != profile
            or record["draft"].get("rule_package_version") != package.package_version
            or record["draft"].get("bundle_fingerprint")
            != _bundle_fingerprint(request, record["scheme_id"])
            or record["draft"].get("form_mapping_fingerprint")
            != _form_mapping_fingerprint(request, record["scheme_id"])
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
        _track_waiting_approval(record, edited)
        return _public_application_record(edited)
    except HTTPException:
        raise
    except MCPToolError as error:
        raise _tool_failure(
            "The draft could not be edited; reload it and try again.",
            status_code=409,
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
        if decision.action != "reject" and not record.get("receipt_id"):
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
            if (
                draft.get("bundle_fingerprint")
                != _bundle_fingerprint(request, record["scheme_id"])
                or draft.get("form_mapping_fingerprint")
                != _form_mapping_fingerprint(request, record["scheme_id"])
            ):
                raise HTTPException(
                    status_code=409,
                    detail="The scheme form or bundle changed. Create and review a new draft.",
                )
            if draft.get("profile") != profile:
                raise HTTPException(
                    status_code=409,
                    detail="Your answers changed. Recheck eligibility and create a new draft.",
                )
        result = await _dispatch_application_task(
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
        _track_waiting_approval(record, result)
        return _public_application_record(result)
    except HTTPException:
        raise
    except MCPToolError as error:
        raise _tool_failure(
            "The mock application service is unavailable.",
            "Mock application approval MCP tool failed",
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
            _portal_reader(request, conversation_id),
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
        await request.app.state.journey_store.adelete(BUDGET_NAMESPACE, conversation_id)
    except MCPToolError as error:
        raise _tool_failure(
            "The mock application service could not clear this session.",
            "Could not clear mock application data",
        ) from error
    await request.app.state.journey_checkpointer.adelete_thread(conversation_id)


# -- Household memory endpoints -----------------------------------------------


@app.get("/api/v1/household/{return_code}", tags=["household"])
async def get_household(return_code: str, request: Request) -> dict:
    """Load a saved household profile by its return code.

    Returns the saved typed facts as a wire dict, or 404 when the code is
    unknown or the saved profile cannot be restored against the current
    registry.
    """

    try:
        code = normalize_return_code(return_code)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    registry = request.app.state.fact_registry
    store = request.app.state.journey_store
    profile = await load_household(store, code, registry)
    if profile is None:
        raise HTTPException(status_code=404, detail="Unknown return code.")
    locale = await load_household_locale(store, code)
    return {
        "return_code": code,
        "typed_facts": profile.to_wire(registry),
        "locale": locale or "en",
    }


@app.post("/api/v1/household", tags=["household"])
async def save_household_profile(
    body: dict,
    request: Request,
) -> dict:
    """Save or update a household profile under a return code.

    Body:
        return_code (optional): Reuse an existing code; generates one when absent.
        conversation_id: The conversation whose typed_facts to save.
    """

    conversation_id = body.get("conversation_id")
    if not conversation_id:
        raise HTTPException(status_code=422, detail="conversation_id is required.")
    try:
        UUID(conversation_id)
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=422, detail="conversation_id must be a UUID.",
        ) from error

    graph = request.app.state.journey_graph
    config = {"configurable": {"thread_id": conversation_id}}
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}
    typed_data = values.get("typed_facts")
    if not typed_data:
        raise HTTPException(
            status_code=404,
            detail="No profile facts found in this conversation.",
        )
    registry = request.app.state.fact_registry
    try:
        profile = HouseholdProfile.from_wire(typed_data, registry)
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=422, detail="Saved facts could not be validated.",
        ) from error

    raw_code = body.get("return_code")
    if raw_code:
        try:
            code = normalize_return_code(raw_code)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    else:
        code = generate_return_code()

    locale = values.get("locale", "en")
    store = request.app.state.journey_store
    await save_household(store, code, profile, registry, locale)
    return {"return_code": code}


@app.delete("/api/v1/household/{return_code}", status_code=204, tags=["household"])
async def forget_household(return_code: str, request: Request) -> None:
    """Delete a household's saved profile."""

    try:
        code = normalize_return_code(return_code)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    store = request.app.state.journey_store
    existing = await store.aget(HOUSEHOLD_NAMESPACE, code)
    if existing is None:
        raise HTTPException(status_code=404, detail="Unknown return code.")
    await store.adelete(HOUSEHOLD_NAMESPACE, code)
