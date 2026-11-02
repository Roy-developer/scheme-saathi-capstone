"""LangGraph flow for discovery and synthetic eligibility journeys.

Phase 2 shape (a manager with helpers):

    START -> supervisor --+--> intake_agent --(question?)--> ask_user
                ^         |         |                          |
                |         |         +----(done)--> supervisor  +--> intake_agent
                |         +--> eligibility_agent --> supervisor
                |         +--> scheme_search_tool --> supervisor
                +-- every specialist reports back here; supervisor ends the run

- The supervisor writes a visible ``Plan``, hands each step to one specialist
  with a typed ``Handoff``, and moves on when the specialist reports back.
- In an "interview", intake asks one question at a time. ``ask_user`` pauses
  the graph with ``interrupt()``; the user's reply resumes it from the saved
  checkpoint (see ``resume_journey``).
- Eligibility is always decided by the deterministic rule engine through MCP.
"""

from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from operator import add
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from mcp import Client
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.eligibility import EligibilityResponse
from src.api.scheme_search import SchemePassage
from src.rules.models import HouseholdProfile, RulePackage
from src.workflow.eligibility import evaluate_eligibility
from src.workflow.intake import rewrite_scheme_query
from src.workflow.question_picker import pick_next_fact
from src.workflow.questions import parse_answer, question_for
from src.workflow.scheme_search import search_scheme_passages
from src.workflow.state import Handoff, Plan, SpecialistName
from src.workflow.supervisor import (
    advance_plan,
    build_initial_plan,
    plan_summary,
)


class JourneyRequest(BaseModel):
    """Input that starts one request in a resumable synthetic journey.

    action:
        "search"    - find schemes for ``query``.
        "evaluate"  - check ``scheme_id`` with a complete ``profile`` at once.
        "interview" - check ``scheme_id`` by asking one question at a time.
            ``profile`` is optional here and pre-fills known facts.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["search", "evaluate", "interview"]
    conversation_id: UUID = Field(default_factory=uuid4)
    query: str | None = None
    scheme_id: str | None = None
    profile: dict[str, Any] | None = None


class JourneyMessage(BaseModel):
    """The user's reply to the question the journey is waiting on."""

    model_config = ConfigDict(extra="forbid")

    # Short limit: answers are yes/no or a date, and it caps abuse.
    message: str = Field(min_length=1, max_length=500)


class JourneyNotWaitingError(Exception):
    """A reply was sent, but the journey is not waiting for an answer."""


class JourneyState(TypedDict, total=False):
    """Typed state shared by the graph's supervisor and specialist nodes.

    Each node returns a dict with only the keys it changes; LangGraph merges
    that dict into this state. ``total=False`` means every key is optional.
    """

    action: Literal["search", "evaluate", "interview"]
    conversation_id: str
    query: str
    normalized_query: str
    scheme_id: str
    # Kept as plain JSON so the checkpointer can save it.
    profile: dict[str, Any] | None
    # One-line plan text (kept for older screens) and the full typed plan.
    plan: str
    plan_detail: dict[str, Any] | None
    # Which specialist the supervisor chose to run next ("__end__" = stop).
    next_agent: str
    status: str
    message: str
    missing_fields: list[str]
    passages: list[dict[str, Any]]
    eligibility_result: dict[str, Any] | None
    validation_errors: list[str]
    # Interview fields:
    # pending_fact   - the profile field the current question is about.
    # question       - the question text shown to the user.
    # pending_answer - the user's raw reply, set by ask_user on resume.
    # skipped_facts  - facts answered "I don't know"; never asked again.
    pending_fact: str | None
    question: str | None
    pending_answer: str | None
    skipped_facts: list[str]
    # Annotated with "add": new items are appended to the saved history
    # instead of replacing it.
    handoffs: Annotated[list[dict[str, Any]], add]
    conversation: Annotated[list[dict[str, str]], add]


class JourneyResponse(BaseModel):
    """User-facing output from one graph run (or one resumed step)."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    plan: str
    plan_detail: Plan | None = None
    status: Literal[
        "search_results",
        "need_information",
        "information_only",
        "eligible",
        "not_eligible",
        "need_more_information",
        "invalid_input",
        "awaiting_answer",
    ]
    message: str
    # Set only while status is "awaiting_answer".
    question: str | None = None
    pending_fact: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    passages: list[SchemePassage] = Field(default_factory=list)
    eligibility_result: EligibilityResponse | None = None
    conversation: list[dict[str, str]] = Field(default_factory=list)


async def _search_with_mcp(
    client: Client,
    query: str,
) -> list[SchemePassage]:
    """Default search tool: ask the MCP server for the top 5 passages."""

    return await search_scheme_passages(client, query, limit=5)


async def _evaluate_with_mcp(
    client: Client,
    scheme_id: str,
    profile: HouseholdProfile,
) -> EligibilityResponse:
    """Default eligibility tool: ask the MCP server's rule engine."""

    return await evaluate_eligibility(client, scheme_id, profile)


def _report_to_supervisor(
    specialist: SpecialistName,
    status: str,
) -> list[dict[str, Any]]:
    """Build the typed handoff a specialist sends back when its step ends.

    Returned as a one-item list so it can be appended to ``handoffs``.
    """

    handoff = Handoff(
        sender=specialist,
        recipient="supervisor",
        step_id=specialist,
        payload={"status": status},
    )
    return [handoff.model_dump(mode="json")]


def build_journey_graph(
    client: Client,
    rule_packages: Mapping[str, RulePackage],
    *,
    search_tool: Callable[
        [Client, str], Awaitable[list[SchemePassage]]
    ] = _search_with_mcp,
    eligibility_tool: Callable[
        [Client, str, HouseholdProfile], Awaitable[EligibilityResponse]
    ] = _evaluate_with_mcp,
    query_rewriter: Callable[[str], Awaitable[str]] = rewrite_scheme_query,
    checkpointer: BaseCheckpointSaver | None = None,
    today: Callable[[], date] = date.today,
) -> Any:
    """Build and compile the supervisor journey with a checkpointer.

    Args:
        client: Connected MCP client used by the tool nodes.
        rule_packages: Loaded rule packages; intake uses them to know which
            schemes can be checked and which facts each one needs.
        search_tool, eligibility_tool, query_rewriter: Replaceable so tests
            can pass fakes instead of calling MCP or a paid LLM.
        checkpointer: Saves state after each node, keyed by conversation ID.
            Required for interviews, because pausing needs saved state.
        today: Gives the default application date for interviews. Tests
            pass a fixed date so results do not change from day to day.
    """

    # The functions below are graph nodes. Each receives the current state
    # and returns only the keys it wants to change.

    async def supervisor(state: JourneyState) -> dict[str, Any]:
        """Plan the request, then route each step to one specialist.

        First visit in a run: there is no plan yet, so write one and hand
        the first step to intake. Later visits: a specialist has just
        reported back (the last handoff), so record it and pick the next
        step, or end the run.
        """

        if not state.get("plan_detail"):
            plan = build_initial_plan(state["action"], state.get("scheme_id"))
            first = plan.steps[0]
            summary = plan_summary(plan)
            handoff = Handoff(
                sender="supervisor",
                recipient=first.specialist,
                step_id=first.step_id,
                payload={"action": state["action"]},
            )
            return {
                "plan": summary,
                "plan_detail": plan.model_dump(mode="json"),
                "next_agent": first.specialist,
                "handoffs": [handoff.model_dump(mode="json")],
                "conversation": [{"role": "assistant", "content": summary}],
            }

        # A specialist just finished: read its report.
        report = state["handoffs"][-1]
        plan, next_step = advance_plan(
            Plan.model_validate(state["plan_detail"]),
            report["sender"],
            report["payload"]["status"],
        )
        update: dict[str, Any] = {"plan_detail": plan.model_dump(mode="json")}
        if next_step is None:
            # Plan finished or stopped early; END keeps the last status.
            update["next_agent"] = END
            return update

        handoff = Handoff(
            sender="supervisor",
            recipient=next_step.specialist,
            step_id=next_step.step_id,
            payload={"scheme_id": next_step.scheme_id},
        )
        update["next_agent"] = next_step.specialist
        update["handoffs"] = [handoff.model_dump(mode="json")]
        return update

    async def intake_agent(state: JourneyState) -> dict[str, Any]:
        """Collect and check what the request needs before any tool runs.

        Search: rewrite the question for retrieval.
        Evaluate: check scheme, rule package and profile, stopping at the
        first problem with a clear status and message.
        Interview: the same checks, then ask the next question (or finish
        when nothing useful is left to ask).
        """

        # ---- Search path ----
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
                    "handoffs": _report_to_supervisor(
                        "intake", "need_information"
                    ),
                }
            # The LLM rewrites the user's words into a better search query.
            normalized_query = await query_rewriter(query)
            return {
                "query": normalized_query,
                "status": "searching",
                "normalized_query": normalized_query,
                "passages": [],
                "eligibility_result": None,
                "handoffs": _report_to_supervisor("intake", "searching"),
            }

        # ---- Evaluate and interview paths ----
        interview = state["action"] == "interview"

        # Check 1: a scheme must be chosen.
        scheme_id = (state.get("scheme_id") or "").strip()
        if not scheme_id:
            message = "Choose a scheme before checking eligibility."
            return {
                "status": "need_information",
                "message": message,
                "missing_fields": ["scheme_id"],
                "eligibility_result": None,
                "conversation": [{"role": "assistant", "content": message}],
                "handoffs": _report_to_supervisor(
                    "intake", "need_information"
                ),
            }
        # Check 2: the scheme must have a reviewed rule package. Without one
        # we only show information and never guess eligibility.
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
                "handoffs": _report_to_supervisor(
                    "intake", "information_only"
                ),
            }
        package = rule_packages[scheme_id]

        # Check 3: "evaluate" needs a profile up front. If none was sent,
        # list the facts this scheme needs, read from its rule package.
        # An interview may start empty because it asks for the facts.
        profile_data = state.get("profile")
        if profile_data is None and not interview:
            message = "Provide the required synthetic profile facts to continue."
            return {
                "status": "need_information",
                "message": message,
                "missing_fields": list(package.required_facts),
                "eligibility_result": None,
                "conversation": [{"role": "assistant", "content": message}],
                "handoffs": _report_to_supervisor(
                    "intake", "need_information"
                ),
            }
        profile_data = dict(profile_data or {})
        if interview and not profile_data.get("application_date"):
            # People apply "today"; asking them for it would be odd.
            profile_data["application_date"] = today().isoformat()

        # Check 4: the profile must match HouseholdProfile (right types,
        # sensible dates, no unknown fields). Empty facts are allowed.
        try:
            profile = HouseholdProfile.model_validate(profile_data)
        except ValidationError as error:
            # Collect the name of each bad field, e.g. "is_widow".
            # item["loc"] is the path to the error; [0] is the field name.
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
                "handoffs": _report_to_supervisor("intake", "invalid_input"),
            }

        conversation: list[dict[str, str]] = []
        if interview:
            skipped = set(state.get("skipped_facts") or [])
            pending_fact = state.get("pending_fact")
            reply = state.get("pending_answer")

            # A reply has arrived for the last question: apply it.
            if pending_fact and reply is not None:
                parsed = parse_answer(pending_fact, reply)
                problem: str | None = None
                if parsed.kind == "unknown":
                    # Remember it so the picker never asks it again.
                    skipped.add(pending_fact)
                elif parsed.kind == "invalid":
                    problem = parsed.error
                else:
                    try:
                        # Re-validate the whole profile, so cross-field
                        # checks run (e.g. birth date after application).
                        profile = HouseholdProfile.model_validate(
                            {
                                **profile.model_dump(mode="json"),
                                pending_fact: parsed.value,
                            }
                        )
                    except ValidationError as error:
                        # e.g. "Value error, date_of_birth cannot be after
                        # application_date" -> "date of birth cannot be
                        # after application date".
                        reason = (
                            error.errors()[0]["msg"]
                            .removeprefix("Value error, ")
                            .replace("_", " ")
                        )
                        problem = f"That answer does not fit: {reason}."
                if problem:
                    # Ask the same question again, with a hint.
                    question = f"{problem} {question_for(pending_fact)}"
                    return {
                        "status": "awaiting_answer",
                        "message": question,
                        "question": question,
                        "pending_answer": None,
                        "conversation": [
                            {"role": "assistant", "content": question}
                        ],
                    }

            next_fact = pick_next_fact(profile, package, frozenset(skipped))
            if next_fact is not None:
                question = question_for(next_fact)
                return {
                    "scheme_id": scheme_id,
                    "profile": profile.model_dump(mode="json"),
                    "skipped_facts": sorted(skipped),
                    "status": "awaiting_answer",
                    "message": question,
                    "question": question,
                    "pending_fact": next_fact,
                    "pending_answer": None,
                    "missing_fields": [],
                    "eligibility_result": None,
                    "conversation": [
                        {"role": "assistant", "content": question}
                    ],
                }
            # Nothing useful left to ask: fall through and hand over.
            state_extra = {
                "skipped_facts": sorted(skipped),
                "pending_fact": None,
                "question": None,
                "pending_answer": None,
            }
        else:
            state_extra = {}
            conversation = [
                {
                    "role": "user",
                    "content": f"Check eligibility for {scheme_id}.",
                }
            ]

        # All checks passed: save the cleaned profile and report back so the
        # supervisor can start the eligibility step.
        return {
            "scheme_id": scheme_id,
            "profile": profile.model_dump(mode="json"),
            "status": "ready_for_eligibility",
            "missing_fields": [],
            "eligibility_result": None,
            "conversation": conversation,
            "handoffs": _report_to_supervisor(
                "intake", "ready_for_eligibility"
            ),
            **state_extra,
        }

    async def ask_user(state: JourneyState) -> dict[str, Any]:
        """Pause the graph until the user answers the current question.

        ``interrupt()`` saves the state and stops this run. The API returns
        the question to the UI. When the user replies, ``resume_journey``
        calls the graph with ``Command(resume=reply)``; this node then runs
        again and ``interrupt()`` returns the reply instead of pausing.
        """

        reply = interrupt(
            {"question": state["question"], "fact": state["pending_fact"]}
        )
        return {
            "pending_answer": reply,
            "conversation": [{"role": "user", "content": reply}],
        }

    async def eligibility_agent(state: JourneyState) -> dict[str, Any]:
        """Ask the MCP rule tool for a verdict and store it in the state."""

        # Rebuild the typed profile from the saved JSON.
        profile = HouseholdProfile.model_validate(state["profile"])
        # The rule engine runs in the MCP server; this node never reads
        # rule files itself (least privilege).
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
            "handoffs": _report_to_supervisor("eligibility", result.result),
        }

    async def scheme_search_tool(state: JourneyState) -> dict[str, Any]:
        """Find cited scheme passages for the rewritten query."""

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
            "handoffs": _report_to_supervisor("search", "search_results"),
        }

    def route_after_intake(state: JourneyState) -> str:
        """Ask the user if intake has a question; otherwise report back."""

        if state.get("status") == "awaiting_answer":
            return "ask_user"
        return "supervisor"

    # Wire the nodes together (see the diagram at the top of this file).
    graph = StateGraph(JourneyState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("intake_agent", intake_agent)
    graph.add_node("ask_user", ask_user)
    graph.add_node("eligibility_agent", eligibility_agent)
    graph.add_node("scheme_search_tool", scheme_search_tool)
    graph.add_edge(START, "supervisor")
    # A conditional edge looks at the state and picks the next node. The
    # supervisor stores its choice in "next_agent".
    graph.add_conditional_edges(
        "supervisor",
        lambda state: state["next_agent"],
        {
            "intake": "intake_agent",
            "eligibility": "eligibility_agent",
            "search": "scheme_search_tool",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "intake_agent",
        route_after_intake,
        {"ask_user": "ask_user", "supervisor": "supervisor"},
    )
    # After the user answers, intake reads the answer and continues.
    graph.add_edge("ask_user", "intake_agent")
    graph.add_edge("eligibility_agent", "supervisor")
    graph.add_edge("scheme_search_tool", "supervisor")
    # compile() turns the wiring into a runnable graph; the checkpointer
    # saves state after every node.
    return graph.compile(checkpointer=checkpointer)


def _thread_config(conversation_id: UUID) -> dict[str, Any]:
    """LangGraph config that selects one saved conversation by its ID."""

    # thread_id tells the checkpointer which saved conversation to load and
    # continue. The same conversation_id resumes the same conversation.
    return {"configurable": {"thread_id": str(conversation_id)}}


def _to_response(
    conversation_id: UUID,
    values: Mapping[str, Any],
) -> JourneyResponse:
    """Convert raw graph state into the typed API response."""

    awaiting = values.get("status") == "awaiting_answer"
    return JourneyResponse(
        conversation_id=conversation_id,
        plan=values.get("plan", ""),
        plan_detail=(
            Plan.model_validate(values["plan_detail"])
            if values.get("plan_detail")
            else None
        ),
        status=values["status"],
        message=values.get("message", ""),
        # Only show a question while the graph is actually waiting.
        question=values.get("question") if awaiting else None,
        pending_fact=values.get("pending_fact") if awaiting else None,
        missing_fields=values.get("missing_fields", []),
        passages=[
            SchemePassage.model_validate(passage)
            for passage in values.get("passages", [])
        ],
        eligibility_result=(
            EligibilityResponse.model_validate(values["eligibility_result"])
            if values.get("eligibility_result") is not None
            else None
        ),
        conversation=values.get("conversation", []),
    )


async def run_journey(
    graph: Any,
    request: JourneyRequest,
) -> JourneyResponse:
    """Start a new request in a conversation (search, evaluate or interview).

    Any question still waiting from an earlier request is dropped: new
    input always starts the graph again from START.
    """

    # Start state for this request. Keys from an earlier request in the same
    # conversation are saved in the checkpoint, so every per-request key is
    # reset here; otherwise an old plan, profile or answer could leak in.
    # Only "conversation" and "handoffs" keep growing as history.
    initial_state: JourneyState = {
        "action": request.action,
        "conversation_id": str(request.conversation_id),
        "scheme_id": request.scheme_id or "",
        "profile": request.profile,
        "plan_detail": None,
        "status": "",
        "message": "",
        "missing_fields": [],
        "eligibility_result": None,
        "pending_fact": None,
        "question": None,
        "pending_answer": None,
        "skipped_facts": [],
        "conversation": [],
    }
    if request.query is not None:
        initial_state["query"] = request.query
        initial_state["conversation"] = [
            {"role": "user", "content": request.query}
        ]

    result = await graph.ainvoke(
        initial_state,
        config=_thread_config(request.conversation_id),
    )
    return _to_response(request.conversation_id, result)


async def resume_journey(
    graph: Any,
    conversation_id: UUID,
    message: str,
) -> JourneyResponse:
    """Send the user's reply to a paused interview and run to the next pause.

    Raises:
        JourneyNotWaitingError: the conversation is not waiting for a reply
            (unknown ID, already finished, or never asked a question).
    """

    config = _thread_config(conversation_id)
    snapshot = await graph.aget_state(config)
    # snapshot.interrupts is non-empty only while ask_user is paused.
    if not snapshot.interrupts:
        raise JourneyNotWaitingError(str(conversation_id))

    result = await graph.ainvoke(Command(resume=message), config=config)
    return _to_response(conversation_id, result)


async def get_journey(
    graph: Any,
    conversation_id: UUID,
) -> JourneyResponse | None:
    """Return the saved state of a conversation, or None if there is none.

    The UI uses this to continue a conversation after a page refresh.
    """

    snapshot = await graph.aget_state(_thread_config(conversation_id))
    # An unknown conversation has empty values; a saved one always has a
    # status once its first request has run.
    if not snapshot.values or not snapshot.values.get("status"):
        return None
    return _to_response(conversation_id, snapshot.values)
