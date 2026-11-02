"""LangGraph flow for discovery and synthetic eligibility journeys."""

from collections.abc import Awaitable, Callable, Mapping
from operator import add
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from mcp import Client
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.eligibility import EligibilityRequest, EligibilityResponse
from src.api.scheme_search import SchemePassage
from src.rules.models import RulePackage
from src.workflow.eligibility import evaluate_eligibility
from src.workflow.errors import MCPToolError
from src.workflow.intake import rewrite_scheme_query
from src.workflow.scheme_search import search_scheme_passages


class JourneyRequest(BaseModel):
    """Input for one step in a resumable synthetic user journey."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["search", "evaluate"]
    conversation_id: UUID = Field(default_factory=uuid4)
    query: str | None = None
    scheme_id: str | None = None
    profile: dict[str, Any] | None = None


class JourneyState(TypedDict, total=False):
    """Typed state shared by the graph's agent and tool nodes."""

    action: Literal["search", "evaluate"]
    conversation_id: str
    query: str
    normalized_query: str
    scheme_id: str
    profile: dict[str, Any]
    plan: str
    status: str
    message: str
    missing_fields: list[str]
    passages: list[dict[str, Any]]
    eligibility_result: dict[str, Any] | None
    validation_errors: list[str]
    conversation: Annotated[list[dict[str, str]], add]


class JourneyResponse(BaseModel):
    """User-facing output from one graph step."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    plan: str
    status: Literal[
        "search_results",
        "need_information",
        "information_only",
        "eligible",
        "not_eligible",
        "need_more_information",
        "invalid_input",
    ]
    message: str
    missing_fields: list[str] = Field(default_factory=list)
    passages: list[SchemePassage] = Field(default_factory=list)
    eligibility_result: EligibilityResponse | None = None
    conversation: list[dict[str, str]] = Field(default_factory=list)


async def _search_with_mcp(
    client: Client,
    query: str,
) -> list[SchemePassage]:
    return await search_scheme_passages(client, query, limit=5)


async def _evaluate_with_mcp(
    client: Client,
    scheme_id: str,
    profile: EligibilityRequest,
) -> EligibilityResponse:
    return await evaluate_eligibility(client, scheme_id, profile)


def build_journey_graph(
    client: Client,
    rule_packages: Mapping[str, RulePackage],
    *,
    search_tool: Callable[
        [Client, str], Awaitable[list[SchemePassage]]
    ] = _search_with_mcp,
    eligibility_tool: Callable[
        [Client, str, EligibilityRequest], Awaitable[EligibilityResponse]
    ] = _evaluate_with_mcp,
    query_rewriter: Callable[[str], Awaitable[str]] = rewrite_scheme_query,
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """Build and compile the three-agent journey with a checkpointer."""

    async def orchestrator_agent(state: JourneyState) -> dict[str, Any]:
        if state["action"] == "search":
            plan = "Understand the request, then find source-cited schemes."
        else:
            plan = (
                "Collect the required synthetic facts, then ask the "
                "deterministic rule engine to evaluate the selected scheme."
            )
        return {
            "plan": plan,
            "conversation": [{"role": "assistant", "content": plan}],
        }

    async def intake_agent(state: JourneyState) -> dict[str, Any]:
        if state["action"] == "search":
            query = state.get("query", "").strip()
            if not query:
                message = "Enter a question or describe the support you need."
                return {
                    "status": "need_information",
                    "message": message,
                    "missing_fields": ["query"],
                    "passages": [],
                    "eligibility_result": None,
                    "conversation": [{"role": "assistant", "content": message}],
                }
            normalized_query = await query_rewriter(query)
            return {
                "query": normalized_query,
                "status": "searching",
                "normalized_query": normalized_query,
                "passages": [],
                "eligibility_result": None,
            }

        scheme_id = state.get("scheme_id", "").strip()
        if not scheme_id:
            message = "Choose a scheme before checking eligibility."
            return {
                "status": "need_information",
                "message": message,
                "missing_fields": ["scheme_id"],
                "eligibility_result": None,
                "conversation": [{"role": "assistant", "content": message}],
            }
        if scheme_id not in rule_packages:
            message = (
                "This scheme is information-only in the current pilot. "
                "A reviewed deterministic eligibility rule package is not "
                "available, so no eligibility decision can be provided."
            )
            return {
                "status": "information_only",
                "message": message,
                "missing_fields": [],
                "eligibility_result": None,
                "conversation": [{"role": "assistant", "content": message}],
            }

        profile_data = state.get("profile")
        if profile_data is None:
            message = "Provide the required synthetic profile facts to continue."
            return {
                "status": "need_information",
                "message": message,
                "missing_fields": [
                    "date_of_birth",
                    "application_date",
                    "is_widow",
                    "bpl_card_shown",
                ],
                "eligibility_result": None,
                "conversation": [{"role": "assistant", "content": message}],
            }

        try:
            profile = EligibilityRequest.model_validate(profile_data)
        except ValidationError as error:
            missing_fields = sorted(
                {
                    str(item["loc"][0])
                    for item in error.errors()
                    if item["loc"]
                }
            )
            return {
                "status": "invalid_input",
                "message": (
                    "Some profile answers are missing or invalid. Review "
                    "the highlighted fields and try again."
                ),
                "missing_fields": missing_fields,
                "validation_errors": missing_fields,
                "eligibility_result": None,
            }

        return {
            "scheme_id": scheme_id,
            "profile": profile.model_dump(mode="json"),
            "status": "ready_for_eligibility",
            "missing_fields": [],
            "eligibility_result": None,
            "conversation": [
                {
                    "role": "user",
                    "content": f"Check eligibility for {scheme_id}.",
                }
            ],
        }

    async def eligibility_agent(state: JourneyState) -> dict[str, Any]:
        profile = EligibilityRequest.model_validate(state["profile"])
        result = await eligibility_tool(
            client,
            state["scheme_id"],
            profile,
        )
        message = result.reason
        return {
            "status": result.result,
            "message": message,
            "missing_fields": result.missing_fields,
            "eligibility_result": result.model_dump(mode="json"),
            "conversation": [{"role": "assistant", "content": message}],
        }

    async def scheme_search_tool(state: JourneyState) -> dict[str, Any]:
        passages = await search_tool(client, state["query"])
        message = (
            f"Found {len(passages)} relevant cited passage(s)."
            if passages
            else "No matching passages were found. Try different wording."
        )
        return {
            "status": "search_results",
            "message": message,
            "passages": [
                passage.model_dump(mode="json") for passage in passages
            ],
            "missing_fields": [],
            "conversation": [{"role": "assistant", "content": message}],
        }

    def route_after_intake(state: JourneyState) -> str:
        if state.get("status") != "ready_for_eligibility":
            return END
        return "eligibility_agent"

    graph = StateGraph(JourneyState)
    graph.add_node("orchestrator_agent", orchestrator_agent)
    graph.add_node("intake_agent", intake_agent)
    graph.add_node("eligibility_agent", eligibility_agent)
    graph.add_node("scheme_search_tool", scheme_search_tool)
    graph.add_edge(START, "orchestrator_agent")
    graph.add_edge("orchestrator_agent", "intake_agent")
    graph.add_conditional_edges(
        "intake_agent",
        lambda state: (
            "scheme_search_tool"
            if state["action"] == "search"
            and state.get("status") == "searching"
            else route_after_intake(state)
        ),
        {
            "scheme_search_tool": "scheme_search_tool",
            "eligibility_agent": "eligibility_agent",
            END: END,
        },
    )
    graph.add_edge("scheme_search_tool", END)
    graph.add_edge("eligibility_agent", END)
    return graph.compile(checkpointer=checkpointer)


async def run_journey(
    graph: Any,
    request: JourneyRequest,
) -> JourneyResponse:
    """Run one graph step, resuming conversation state by its session ID."""

    initial_state: JourneyState = {
        "action": request.action,
        "conversation_id": str(request.conversation_id),
        "conversation": [],
    }
    if request.query is not None:
        initial_state["query"] = request.query
        initial_state["conversation"] = [
            {"role": "user", "content": request.query}
        ]
    if request.scheme_id is not None:
        initial_state["scheme_id"] = request.scheme_id
    if request.profile is not None:
        initial_state["profile"] = request.profile

    result = await graph.ainvoke(
        initial_state,
        config={
            "configurable": {
                "thread_id": str(request.conversation_id),
            }
        },
    )
    return JourneyResponse(
        conversation_id=request.conversation_id,
        plan=result.get("plan", ""),
        status=result["status"],
        message=result["message"],
        missing_fields=result.get("missing_fields", []),
        passages=[
            SchemePassage.model_validate(passage)
            for passage in result.get("passages", [])
        ],
        eligibility_result=(
            EligibilityResponse.model_validate(result["eligibility_result"])
            if result.get("eligibility_result") is not None
            else None
        ),
        conversation=result.get("conversation", []),
    )
