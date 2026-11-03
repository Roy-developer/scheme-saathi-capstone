"""LangGraph flow for discovery, eligibility and synthetic applications.

Supervisor shape (a manager with helpers):

    START -> supervisor --+--> intake_agent --(question?)--> ask_user
                ^         |         |                          |
                |         |         +----(done)--> supervisor  +--> intake_agent
                |         +--> eligibility_agent --> supervisor
                |         +--> scheme_search_tool --> supervisor
                |         +--> document_agent --> supervisor
                |         +--> application_agent --> supervisor
                +-- every specialist reports back here; supervisor ends the run

- The supervisor writes a visible ``Plan``, hands each step to one specialist
  with a typed ``Handoff``, and moves on when the specialist reports back.
- In an "interview", intake asks one question at a time. ``ask_user`` pauses
  the graph with ``interrupt()``; the user's reply resumes it from the saved
  checkpoint (see ``resume_journey``).
- Eligibility is always decided by the deterministic rule engine through MCP.
- Application actions preserve the saved profile and verdicts. The application
  agent alone writes to the portal and manages a separate, per-revision approval
  interrupt so other eligible schemes can still be checked while review waits.
"""

from collections.abc import Awaitable, Callable, Mapping
from datetime import date
import logging
from operator import add
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from mcp import Client
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.api.eligibility import EligibilityResponse
from src.api.applications import call_application_tool
from src.api.scheme_search import SchemePassage
from src.rules.models import FactName, HouseholdProfile, RulePackage
from src.workflow.eligibility import evaluate_eligibility
from src.workflow.application_gate import (
    build_application_gate,
    pause_for_application_approval,
    resume_application_approval,
)
from src.workflow.errors import MCPToolError
from src.workflow.intake import (
    AnswerInterpretation,
    IntakeAgentError,
    interpret_free_text_answer,
    rewrite_scheme_query,
)
from src.workflow.question_picker import pick_next_fact, pick_shared_fact
from src.workflow.questions import (
    parse_answer,
    parse_interpreted_answer,
    question_for,
)
from src.workflow.scheme_search import search_scheme_passages
from src.workflow.state import (
    ApplicationOperation,
    ApplicationTask,
    CandidateVerdict,
    Handoff,
    JourneyHistoryEvent,
    Plan,
    PlanChange,
    SpecialistName,
)
from src.workflow.supervisor import (
    advance_plan,
    build_application_plan,
    build_initial_plan,
    plan_summary,
)

logger = logging.getLogger(__name__)
ANSWER_INTERPRETATION_CONFIDENCE = 0.85
MAX_CANDIDATE_SCHEMES = 20
SEARCH_PASSAGE_LIMIT = MAX_CANDIDATE_SCHEMES


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
    # A visible request limit; do not silently discard excess candidates.
    candidate_scheme_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_CANDIDATE_SCHEMES,
    )

    @model_validator(mode="after")
    def validate_candidates(self) -> "JourneyRequest":
        """Keep the old single-scheme API unambiguous and reject blank IDs."""

        if self.candidate_scheme_ids:
            if self.action == "search" or self.scheme_id is not None:
                raise ValueError(
                    "Use candidate_scheme_ids for evaluate/interview without scheme_id"
                )
            if any(not candidate.strip() for candidate in self.candidate_scheme_ids):
                raise ValueError("Candidate scheme IDs cannot be blank")
            self.candidate_scheme_ids = list(dict.fromkeys(
                candidate.strip() for candidate in self.candidate_scheme_ids
            ))
        return self


class JourneyCorrection(BaseModel):
    """A corrected answer for a fact already saved in a multi-scheme chat."""

    model_config = ConfigDict(extra="forbid")

    fact_name: FactName
    answer: str = Field(min_length=1, max_length=500)


class JourneyMessage(BaseModel):
    """The user's reply to the question the journey is waiting on."""

    model_config = ConfigDict(extra="forbid")

    # Short limit: answers are yes/no or a date, and it caps abuse.
    message: str = Field(min_length=1, max_length=500)


class JourneyNotWaitingError(Exception):
    """A reply was sent, but the journey is not waiting for an answer."""


class ApplicationTaskError(Exception):
    """A specialist could not safely complete a requested application action."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


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
    candidate_scheme_ids: list[str]
    multi_scheme: bool
    plan_version_start: int
    plan_restart_reason: str
    candidate_verdicts: dict[str, dict[str, Any]]
    eligibility_results: dict[str, dict[str, Any]]
    plan_change_history: Annotated[list[dict[str, Any]], add]
    journey_history: Annotated[list[dict[str, Any]], add]
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
    pending_confirmation: bool
    pending_interpreted_value: bool | str | None
    llm_attempted_facts: list[str]
    # Annotated with "add": new items are appended to the saved history
    # instead of replacing it.
    handoffs: Annotated[list[dict[str, Any]], add]
    conversation: Annotated[list[dict[str, str]], add]
    application_task: dict[str, Any] | None
    application_task_result: dict[str, Any] | None
    application_task_error: dict[str, Any] | None
    document_assessments: dict[str, dict[str, Any]]


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
        "completed",
        "tool_error",
    ]
    message: str
    # Set only while status is "awaiting_answer".
    question: str | None = None
    pending_fact: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    passages: list[SchemePassage] = Field(default_factory=list)
    eligibility_result: EligibilityResponse | None = None
    # Additive fields: older clients can still use eligibility_result.
    # Full results keep evidence; summaries also represent information-only schemes.
    candidate_scheme_ids: list[str] = Field(default_factory=list)
    candidate_verdicts: dict[str, CandidateVerdict] = Field(default_factory=dict)
    eligibility_results: dict[str, EligibilityResponse] = Field(default_factory=dict)
    plan_change_history: list[PlanChange] = Field(default_factory=list)
    journey_history: list[JourneyHistoryEvent] = Field(default_factory=list)
    known_fact_names: list[FactName] = Field(default_factory=list)
    conversation: list[dict[str, str]] = Field(default_factory=list)
    document_assessments: dict[str, dict[str, Any]] = Field(default_factory=dict)


async def _search_with_mcp(
    client: Client,
    query: str,
) -> list[SchemePassage]:
    """Default search tool: ask for up to 20 passages for candidate discovery."""

    return await search_scheme_passages(
        client, query, limit=SEARCH_PASSAGE_LIMIT
    )


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
    answer_interpreter: Callable[
        [str, str, str], Awaitable[AnswerInterpretation]
    ] = interpret_free_text_answer,
    checkpointer: BaseCheckpointSaver | None = None,
    today: Callable[[], date] = date.today,
    application_tool: Callable[
        [Client, str, dict[str, Any]], Awaitable[dict[str, Any]]
    ] = call_application_tool,
) -> Any:
    """Build and compile the supervisor journey with a checkpointer.

    Args:
        client: Connected MCP client used by the tool nodes.
        rule_packages: Loaded rule packages; intake uses them to know which
            schemes can be checked and which facts each one needs.
        search_tool, eligibility_tool, query_rewriter, answer_interpreter,
        application_tool:
            Replaceable so tests can pass fakes instead of calling MCP or a
            paid LLM.
        checkpointer: Saves state after each node, keyed by conversation ID.
            Required for interviews, because pausing needs saved state.
        today: Gives the default application date for interviews. Tests
            pass a fixed date so results do not change from day to day.
    """

    application_gate = (
        build_application_gate(checkpointer) if checkpointer is not None else None
    )

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
            task_data = state.get("application_task")
            if task_data:
                task = ApplicationTask.model_validate(task_data)
                plan = build_application_plan(
                    task.operation, task.arguments.get("scheme_id")
                )
            else:
                plan = build_initial_plan(
                    state["action"], state.get("scheme_id"),
                    state.get("candidate_scheme_ids") if state.get("multi_scheme") else None,
                )
            version_start = state.get("plan_version_start", 1)
            if version_start > 1:
                reason = state.get(
                    "plan_restart_reason", "The plan restarted."
                )
                plan = Plan(
                    version=version_start,
                    steps=plan.steps,
                    replan_reason=reason,
                )
            first = plan.steps[0]
            summary = plan_summary(plan)
            handoff = Handoff(
                sender="supervisor",
                recipient=first.specialist,
                step_id=first.step_id,
                payload=(
                    {"operation": task_data["operation"]}
                    if task_data else {"action": state["action"]}
                ),
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
        previous_plan = Plan.model_validate(state["plan_detail"])
        plan, next_step = advance_plan(
            previous_plan,
            report["sender"],
            report["payload"]["status"],
        )
        update: dict[str, Any] = {"plan_detail": plan.model_dump(mode="json")}
        if state.get("multi_scheme") and report["sender"] == "eligibility":
            scheme_id = state["scheme_id"]
            verdict_data = state.get("candidate_verdicts", {}).get(scheme_id)
            if verdict_data is None:
                raise ValueError(
                    f"Eligibility step for {scheme_id} reported without a verdict"
                )
            verdict = CandidateVerdict.model_validate(verdict_data)
            if verdict.result == "not_eligible":
                reason = (
                    f"{scheme_id} was ruled out by the mock rules"
                    + (
                        f" ({', '.join(verdict.deciding_rule_ids)})"
                        if verdict.deciding_rule_ids else ""
                    )
                    + ". Its result is saved; continuing with the next candidate."
                )
            elif verdict.result == "eligible":
                reason = (
                    f"{scheme_id} meets the current mock rules. Its result is "
                    "saved; continuing with the next candidate."
                )
            elif verdict.result == "information_only":
                reason = (
                    f"{scheme_id} has no reviewed rule package. No eligibility "
                    "decision was made; continuing with the next candidate."
                )
            elif verdict.result == "tool_error":
                reason = (
                    f"{scheme_id} could not be checked after two attempts. "
                    "No eligibility decision was made; continuing with the "
                    "next candidate."
                )
            else:
                reason = (
                    f"{scheme_id} still needs information"
                    + (
                        f" ({', '.join(verdict.missing_fields)})"
                        if verdict.missing_fields else ""
                    )
                    + ". Its result is saved; continuing with the next candidate."
                )
            changed_plan = Plan(
                version=previous_plan.version + 1,
                steps=plan.steps,
                replan_reason=reason,
            )
            change = PlanChange(
                from_version=previous_plan.version,
                to_version=changed_plan.version,
                scheme_id=scheme_id,
                result=verdict.result,
                deciding_rule_ids=verdict.deciding_rule_ids,
                reason=reason,
            )
            plan = changed_plan
            update["plan_detail"] = plan.model_dump(mode="json")
            update["plan_change_history"] = [change.model_dump(mode="json")]
        if next_step is None:
            # Plan finished or stopped early; END keeps the last status.
            update["next_agent"] = END
            if state.get("application_task"):
                task = ApplicationTask.model_validate(state["application_task"])
                if (
                    task.operation in {"create_draft", "approve", "submit"}
                    and report["sender"] == "documents"
                    and report["payload"]["status"] != "checklist_complete"
                    and not state.get("application_task_error")
                ):
                    update["application_task_error"] = {
                        "status_code": 409,
                        "detail": "Complete every synthetic demo document item before continuing.",
                    }
                update["application_task"] = None
            if state.get("multi_scheme") and report["sender"] == "eligibility":
                update["status"] = "completed"
                update["message"] = "Candidate checks finished. Review each scheme's result."
                if any(
                    verdict["result"] == "tool_error"
                    for verdict in state.get("candidate_verdicts", {}).values()
                ):
                    update["message"] = (
                        "Candidate checks finished. Some tools failed; no "
                        "eligibility decision was made for those schemes."
                    )
                update["eligibility_result"] = None
                update["missing_fields"] = list(dict.fromkeys(
                    fact for verdict in state.get("candidate_verdicts", {}).values()
                    for fact in verdict["missing_fields"]
                ))
            return update

        handoff = Handoff(
            sender="supervisor",
            recipient=next_step.specialist,
            step_id=next_step.step_id,
            payload={"scheme_id": next_step.scheme_id},
        )
        update["next_agent"] = next_step.specialist
        if next_step.scheme_id is not None:
            update["scheme_id"] = next_step.scheme_id
        update["handoffs"] = [handoff.model_dump(mode="json")]
        return update

    def task_failure(
        specialist: SpecialistName, detail: str, status_code: int = 409
    ) -> dict[str, Any]:
        return {
            "application_task_error": {"status_code": status_code, "detail": detail},
            "handoffs": _report_to_supervisor(
                specialist, "tool_error" if status_code == 502 else "blocked"
            ),
        }

    async def document_agent(state: JourneyState) -> dict[str, Any]:
        """Only inspect reported metadata; this specialist has no portal writes."""

        task = ApplicationTask.model_validate(state["application_task"])
        arguments = task.arguments
        scheme_id = arguments["scheme_id"]
        verdict = state.get("candidate_verdicts", {}).get(scheme_id, {})
        if verdict.get("result") != "eligible" or scheme_id not in rule_packages:
            return task_failure("documents", "This scheme has no current eligible result.")
        try:
            assessment = await application_tool(
                client, "check_documents",
                {"scheme_id": scheme_id, "documents": arguments.get("documents", {})},
            )
        except MCPToolError:
            return task_failure("documents", "The document checklist is unavailable.", 502)
        return {
            "application_task_result": assessment,
            "document_assessments": {
                **state.get("document_assessments", {}),
                scheme_id: assessment,
            },
            "handoffs": _report_to_supervisor("documents", assessment["status"]),
        }

    async def application_agent(state: JourneyState) -> dict[str, Any]:
        """Own portal mutations and the checkpointed exact-draft approval pause."""

        task = ApplicationTask.model_validate(state["application_task"])
        arguments = {
            **task.arguments,
            "action": task.operation,
            "journey_id": state["conversation_id"],
        }
        if task.operation in {"create_draft", "edit_draft", "approve", "reject"}:
            if application_gate is None:
                return task_failure(
                    "application", "Application approval requires checkpoint persistence."
                )
        try:
            record = None
            if task.operation in {"edit_draft", "approve", "reject", "submit"}:
                record = await application_tool(
                    client, "mock_portal",
                    {
                        "action": "get_draft",
                        "journey_id": state["conversation_id"],
                        "draft_id": arguments["draft_id"],
                    },
                )
                if (
                    record.get("not_found")
                    or record["revision"] != arguments["revision"]
                    or (
                        task.operation != "edit_draft"
                        and record["fingerprint"] != arguments["fingerprint"]
                    )
                ):
                    return task_failure(
                        "application", "The draft changed. Reload and review it."
                    )
                if task.operation == "submit" and not record["approved"]:
                    return task_failure(
                        "application", "Approve this exact draft before submitting it."
                    )
                if (
                    task.operation == "approve"
                    and (record["rejected"] or record["receipt_id"])
                ) or (
                    task.operation in {"edit_draft", "reject"} and record["receipt_id"]
                ):
                    return task_failure(
                        "application", "This draft cannot be changed in its current state."
                    )
            if task.operation in {"create_draft", "edit_draft", "approve", "submit"}:
                scheme_id = record["scheme_id"] if record else arguments["scheme_id"]
                profile_data = state.get("profile")
                verdict = state.get("candidate_verdicts", {}).get(scheme_id, {})
                package = rule_packages.get(scheme_id)
                if (
                    not profile_data
                    or package is None
                    or verdict.get("result") != "eligible"
                ):
                    return task_failure(
                        "application", "This scheme has no current eligible profile."
                    )
                profile = HouseholdProfile.model_validate(profile_data)
                if record and (
                    record["draft"]["profile"] != profile.model_dump(mode="json")
                    or record["draft"]["rule_package_version"] != package.package_version
                ):
                    return task_failure(
                        "application", "Answers or scheme rules changed. Create a new draft."
                    )
                if task.operation != "edit_draft":
                    current_verdict = await eligibility_tool(client, scheme_id, profile)
                    if current_verdict.result != "eligible":
                        return task_failure(
                            "application",
                            "The current profile is no longer eligible under the mock rules.",
                        )
                if task.operation == "create_draft":
                    arguments.update({
                        "profile": profile.model_dump(mode="json"),
                        "rule_package_version": package.package_version,
                        "deciding_rule_ids": current_verdict.deciding_rule_ids,
                    })
                if task.operation in {"approve", "submit"}:
                    saved_documents = {
                        item["document_id"]: item["status"]
                        for item in record["draft"]["documents"]
                    }
                    if (
                        arguments.get("scheme_id") != scheme_id
                        or arguments.get("documents") != saved_documents
                    ):
                        return task_failure(
                            "application", "Recheck the documents from this exact draft."
                        )
            if task.operation in {"approve", "reject"}:
                await resume_application_approval(
                    application_gate, state["conversation_id"], record,
                    {
                        key: arguments[key]
                        for key in ("action", "draft_id", "revision", "fingerprint")
                    },
                )
            result = await application_tool(client, "mock_portal", arguments)
            if task.operation in {"create_draft", "edit_draft"}:
                await pause_for_application_approval(
                    application_gate, state["conversation_id"], result
                )
        except MCPToolError:
            return task_failure(
                "application", "The mock application service is unavailable.", 502
            )
        statuses = {
            "create_draft": "awaiting_approval",
            "edit_draft": "awaiting_approval",
            "approve": "approved",
            "reject": "rejected",
            "submit": "submitted",
            "delete_journey": "deleted",
        }
        return {
            "application_task_result": result,
            "handoffs": _report_to_supervisor("application", statuses[task.operation]),
        }

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
        candidates = state.get("candidate_scheme_ids", [])
        multi = state.get("multi_scheme", False)
        scheme_id = (state.get("scheme_id") or "").strip()
        if multi:
            scheme_id = next(
                (candidate for candidate in candidates if candidate in rule_packages),
                candidates[0],
            )
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
        if scheme_id not in rule_packages and not multi:
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
                "candidate_verdicts": {
                    scheme_id: CandidateVerdict(
                        scheme_id=scheme_id, result="information_only"
                    ).model_dump(mode="json")
                },
                "conversation": [{"role": "assistant", "content": message}],
                "handoffs": _report_to_supervisor(
                    "intake", "information_only"
                ),
            }
        packages = (
            [rule_packages[candidate] for candidate in candidates
             if candidate in rule_packages]
            if multi else [rule_packages[scheme_id]]
        )
        package = packages[0] if packages else None

        # Check 3: "evaluate" needs a profile up front. If none was sent,
        # list the facts this scheme needs, read from its rule package.
        # An interview may start empty because it asks for the facts.
        profile_data = state.get("profile")
        if profile_data is None and not interview:
            message = "Provide the required synthetic profile facts to continue."
            return {
                "status": "need_information",
                "message": message,
                "missing_fields": list(dict.fromkeys(
                    fact for candidate in packages for fact in candidate.required_facts
                )),
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
            attempted_facts = set(state.get("llm_attempted_facts") or [])
            pending_fact = state.get("pending_fact")
            reply = state.get("pending_answer")

            # A reply has arrived for the last question: apply it.
            if pending_fact and reply is not None:
                problem: str | None = None
                if state.get("pending_confirmation"):
                    confirmation = parse_answer("is_widow", reply)
                    accepted = (
                        confirmation.kind == "value"
                        and confirmation.value is True
                    )
                    declined = (
                        confirmation.kind == "value"
                        and confirmation.value is False
                    )
                    if accepted:
                        proposed_value = state.get("pending_interpreted_value")
                        if not isinstance(proposed_value, (bool, str)):
                            raise ValueError(
                                "A confirmation prompt has no proposed answer"
                            )
                        parsed = parse_interpreted_answer(
                            pending_fact, proposed_value
                        )
                        value = parsed.value
                        if parsed.kind != "value":
                            problem = parsed.error
                        else:
                            try:
                                profile = HouseholdProfile.model_validate(
                                    {
                                        **profile.model_dump(mode="json"),
                                        pending_fact: value,
                                    }
                                )
                            except ValidationError as error:
                                reason = (
                                    error.errors()[0]["msg"]
                                    .removeprefix("Value error, ")
                                    .replace("_", " ")
                                )
                                problem = f"That answer does not fit: {reason}."
                    elif declined:
                        question = (
                            "Okay. Please answer directly: "
                            f"{question_for(pending_fact)} "
                            f"{parse_answer(pending_fact, '').error or ''}"
                        ).strip()
                        return {
                            "status": "awaiting_answer",
                            "message": question,
                            "question": question,
                            "pending_answer": None,
                            "pending_confirmation": False,
                            "pending_interpreted_value": None,
                            "pending_fact": pending_fact,
                            "llm_attempted_facts": sorted(attempted_facts),
                            "conversation": [
                                {"role": "assistant", "content": question}
                            ],
                        }
                    else:
                        question = (
                            'Please confirm with "yes" or "no". '
                            "Is my interpretation correct?"
                        )
                        return {
                            "status": "awaiting_answer",
                            "message": question,
                            "question": question,
                            "pending_answer": None,
                            "pending_confirmation": True,
                            "pending_interpreted_value": state.get(
                                "pending_interpreted_value"
                            ),
                            "pending_fact": pending_fact,
                            "llm_attempted_facts": sorted(attempted_facts),
                            "conversation": [
                                {"role": "assistant", "content": question}
                            ],
                        }
                else:
                    parsed = parse_answer(pending_fact, reply)
                    if parsed.kind == "unknown":
                        skipped.add(pending_fact)
                    elif parsed.kind == "invalid":
                        if pending_fact not in attempted_facts:
                            attempted_facts.add(pending_fact)
                            try:
                                interpretation = await answer_interpreter(
                                    pending_fact,
                                    question_for(pending_fact),
                                    reply,
                                )
                            except IntakeAgentError as error:
                                logger.warning(
                                    "Free-text answer reading unavailable: %s",
                                    error,
                                )
                                interpretation = None
                            if (
                                interpretation is not None
                                and interpretation.kind == "unknown"
                                and interpretation.confidence
                                >= ANSWER_INTERPRETATION_CONFIDENCE
                            ):
                                skipped.add(pending_fact)
                            if (
                                interpretation is not None
                                and interpretation.kind == "value"
                                and interpretation.confidence
                                >= ANSWER_INTERPRETATION_CONFIDENCE
                                and interpretation.value is not None
                            ):
                                proposed = interpretation.value
                                candidate = parse_interpreted_answer(
                                    pending_fact, proposed
                                )
                                if candidate.kind == "value":
                                    value = candidate.value
                                    try:
                                        HouseholdProfile.model_validate(
                                            {
                                                **profile.model_dump(mode="json"),
                                                pending_fact: value,
                                            }
                                        )
                                    except ValidationError:
                                        pass
                                    else:
                                        display_value = (
                                            value.isoformat()
                                            if hasattr(value, "isoformat")
                                            else "yes" if value is True
                                            else "no" if value is False
                                            else str(value)
                                        )
                                        question = (
                                            f'I understood your answer as "{display_value}". '
                                            'Is that correct? Please answer yes or no.'
                                        )
                                        return {
                                            "status": "awaiting_answer",
                                            "message": question,
                                            "question": question,
                                            "pending_fact": pending_fact,
                                            "pending_answer": None,
                                            "pending_confirmation": True,
                                            "pending_interpreted_value": (
                                                value.isoformat()
                                                if hasattr(value, "isoformat")
                                                else value
                                            ),
                                            "llm_attempted_facts": sorted(attempted_facts),
                                            "conversation": [
                                                {"role": "assistant", "content": question}
                                            ],
                                        }
                        if pending_fact not in skipped:
                            problem = parsed.error
                    else:
                        try:
                            profile = HouseholdProfile.model_validate(
                                {
                                    **profile.model_dump(mode="json"),
                                    pending_fact: parsed.value,
                                }
                            )
                        except ValidationError as error:
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
                        "pending_confirmation": False,
                        "pending_interpreted_value": None,
                        "pending_fact": pending_fact,
                        "llm_attempted_facts": sorted(attempted_facts),
                        "conversation": [
                            {"role": "assistant", "content": question}
                        ],
                    }

            next_fact = (
                pick_shared_fact(profile, packages, frozenset(skipped))
                if multi else pick_next_fact(profile, package, frozenset(skipped))
            )
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
                    "pending_confirmation": False,
                    "pending_interpreted_value": None,
                    "llm_attempted_facts": sorted(
                        attempted_facts
                    ),
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
                "pending_confirmation": False,
                "pending_interpreted_value": None,
                "llm_attempted_facts": sorted(attempted_facts),
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

        scheme_id = state["scheme_id"]
        if state.get("multi_scheme") and scheme_id not in rule_packages:
            verdict = CandidateVerdict(scheme_id=scheme_id, result="information_only")
            return {
                "status": "information_only",
                "eligibility_result": None,
                "candidate_verdicts": {
                    **state.get("candidate_verdicts", {}),
                    scheme_id: verdict.model_dump(mode="json"),
                },
                "handoffs": _report_to_supervisor("eligibility", "information_only"),
            }
        # Rebuild the typed profile from the saved JSON.
        profile = HouseholdProfile.model_validate(state["profile"])
        # The rule engine runs in the MCP server; this node never reads
        # rule files itself (least privilege).
        history: list[dict[str, Any]] = []
        result = None
        for attempt in (1, 2):
            try:
                result = await eligibility_tool(client, scheme_id, profile)
                break
            except MCPToolError:
                if attempt == 1:
                    history.append(JourneyHistoryEvent(
                        event_type="tool_retry",
                        scheme_id=scheme_id,
                        attempt=attempt,
                        reason=f"Eligibility check for {scheme_id} failed. Retrying once.",
                    ).model_dump(mode="json"))
                else:
                    history.append(JourneyHistoryEvent(
                        event_type="tool_failed",
                        scheme_id=scheme_id,
                        attempt=attempt,
                        reason=(
                            f"Eligibility check for {scheme_id} failed twice. "
                            "No decision was made."
                        ),
                    ).model_dump(mode="json"))
        if result is None:
            verdict = CandidateVerdict(scheme_id=scheme_id, result="tool_error")
            return {
                "status": "tool_error",
                "message": f"Could not check {scheme_id}. No eligibility decision was made.",
                "eligibility_result": None,
                "candidate_verdicts": {
                    **state.get("candidate_verdicts", {}),
                    scheme_id: verdict.model_dump(mode="json"),
                },
                "journey_history": history,
                "handoffs": _report_to_supervisor("eligibility", "tool_error"),
            }
        message = result.reason
        verdict = CandidateVerdict(
            scheme_id=result.scheme_id,
            result=result.result,
            missing_fields=result.missing_fields,
            deciding_rule_ids=result.deciding_rule_ids,
        )
        return {
            "status": result.result,
            "message": message,
            "missing_fields": result.missing_fields,
            "eligibility_result": result.model_dump(mode="json"),
            "candidate_verdicts": {
                **state.get("candidate_verdicts", {}),
                result.scheme_id: verdict.model_dump(mode="json"),
            },
            "eligibility_results": {
                **state.get("eligibility_results", {}),
                result.scheme_id: result.model_dump(mode="json"),
            },
            "conversation": [{"role": "assistant", "content": message}],
            "handoffs": _report_to_supervisor("eligibility", result.result),
            "journey_history": history,
        }

    async def scheme_search_tool(state: JourneyState) -> dict[str, Any]:
        """Find cited scheme passages for the rewritten query."""

        history: list[dict[str, Any]] = []
        passages = None
        for attempt in (1, 2):
            try:
                passages = await search_tool(client, state["query"])
                break
            except MCPToolError:
                if attempt == 1:
                    history.append(JourneyHistoryEvent(
                        event_type="tool_retry",
                        scheme_id=None,
                        attempt=attempt,
                        reason="Scheme search failed. Retrying once.",
                    ).model_dump(mode="json"))
                else:
                    history.append(JourneyHistoryEvent(
                        event_type="tool_failed",
                        scheme_id=None,
                        attempt=attempt,
                        reason="Scheme search failed twice. No search results are available.",
                    ).model_dump(mode="json"))
        if passages is None:
            message = "Scheme search is unavailable. Please try again later."
            return {
                "status": "tool_error",
                "message": message,
                "passages": [],
                "candidate_scheme_ids": [],
                "journey_history": history,
                "conversation": [{"role": "assistant", "content": message}],
                "handoffs": _report_to_supervisor("search", "tool_error"),
            }
        candidate_scheme_ids = list(
            dict.fromkeys(passage.scheme_id for passage in passages)
        )
        if passages:
            passage_label = "passage" if len(passages) == 1 else "passages"
            scheme_label = (
                "scheme" if len(candidate_scheme_ids) == 1 else "schemes"
            )
            message = (
                f"Found {len(passages)} relevant cited {passage_label} across "
                f"{len(candidate_scheme_ids)} {scheme_label}. Showing up to "
                f"{SEARCH_PASSAGE_LIMIT} passages; search may not find every "
                "relevant scheme."
            )
        else:
            message = "No matching passages were found. Try different wording."
        return {
            "status": "search_results",
            "message": message,
            "passages": [
                passage.model_dump(mode="json") for passage in passages
            ],
            # Preserve retrieval order while grouping passages by scheme.
            "candidate_scheme_ids": candidate_scheme_ids,
            "journey_history": history,
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
    graph.add_node("document_agent", document_agent)
    graph.add_node("application_agent", application_agent)
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
            "documents": "document_agent",
            "application": "application_agent",
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
    graph.add_edge("document_agent", "supervisor")
    graph.add_edge("application_agent", "supervisor")
    # compile() turns the wiring into a runnable graph; the checkpointer
    # saves state after every node.
    return graph.compile(checkpointer=checkpointer)


def _thread_config(conversation_id: UUID) -> dict[str, Any]:
    """LangGraph config that selects one saved conversation by its ID."""

    # thread_id tells the checkpointer which saved conversation to load and
    # continue. The same conversation_id resumes the same conversation.
    # Up to 20 explicit candidates need more than the default 25 node visits.
    return {
        "configurable": {"thread_id": str(conversation_id)},
        "recursion_limit": 100,
    }


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
        candidate_scheme_ids=values.get("candidate_scheme_ids", []),
        candidate_verdicts=values.get("candidate_verdicts", {}),
        eligibility_results=values.get("eligibility_results", {}),
        known_fact_names=[
            name for name, value in (values.get("profile") or {}).items()
            if value is not None and name in HouseholdProfile.model_fields
        ],
        plan_change_history=[
            PlanChange.model_validate(change)
            for change in values.get("plan_change_history", [])
        ],
        journey_history=[
            JourneyHistoryEvent.model_validate(event)
            for event in values.get("journey_history", [])
        ],
        conversation=values.get("conversation", []),
        document_assessments=values.get("document_assessments", {}),
    )


async def run_application_task(
    graph: Any,
    conversation_id: UUID,
    operation: ApplicationOperation,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Continue through the supervisor without replacing saved eligibility facts."""

    task = ApplicationTask(operation=operation, arguments=arguments)
    config = _thread_config(conversation_id)
    snapshot = await graph.aget_state(config)
    if snapshot.interrupts and operation != "delete_journey":
        raise ApplicationTaskError(409, "Finish the current interview first.")
    if not snapshot.values and operation != "delete_journey":
        raise ApplicationTaskError(404, "Conversation not found.")
    previous_plan = snapshot.values.get("plan_detail")
    version = Plan.model_validate(previous_plan).version + 1 if previous_plan else 1
    result = await graph.ainvoke(
        {
            "conversation_id": str(conversation_id),
            "application_task": task.model_dump(mode="json"),
            "application_task_result": None,
            "application_task_error": None,
            "plan_detail": None,
            "plan_version_start": version,
            "plan_restart_reason": f"The user requested {operation}.",
        },
        config=config,
    )
    error = result.get("application_task_error")
    if error:
        raise ApplicationTaskError(error["status_code"], error["detail"])
    return {
        **result["application_task_result"],
        "plan_detail": result["plan_detail"],
    }


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
        "application_task": None,
        "application_task_result": None,
        "application_task_error": None,
        "document_assessments": {},
        "conversation_id": str(request.conversation_id),
        "scheme_id": request.scheme_id or "",
        "multi_scheme": bool(request.candidate_scheme_ids),
        "profile": request.profile,
        "plan_detail": None,
        "status": "",
        "message": "",
        "missing_fields": [],
        "eligibility_result": None,
        "candidate_scheme_ids": (
            request.candidate_scheme_ids or
            ([request.scheme_id] if request.scheme_id else [])
        ),
        "candidate_verdicts": {},
        "eligibility_results": {},
        "plan_change_history": [],
        "journey_history": [],
        "plan_version_start": 1,
        "passages": [],
        "pending_fact": None,
        "question": None,
        "pending_answer": None,
        "pending_confirmation": False,
        "pending_interpreted_value": None,
        "llm_attempted_facts": [],
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


async def correct_journey_answer(
    graph: Any,
    conversation_id: UUID,
    correction: JourneyCorrection,
) -> JourneyResponse:
    """Replace one known answer and rerun every candidate check.

    The correction record stores the fact name only, not its old or new value.
    """

    config = _thread_config(conversation_id)
    snapshot = await graph.aget_state(config)
    values = snapshot.values
    if not values or not values.get("multi_scheme"):
        raise JourneyNotWaitingError(str(conversation_id))

    profile = HouseholdProfile.model_validate(values.get("profile") or {})
    if getattr(profile, correction.fact_name) is None:
        raise ValueError("Only a previously answered fact can be corrected")

    parsed = parse_answer(correction.fact_name, correction.answer)
    if parsed.kind != "value":
        raise ValueError(
            parsed.error or "A correction must be a clear yes, no, or date"
        )
    updated_profile = HouseholdProfile.model_validate({
        **profile.model_dump(mode="json"),
        correction.fact_name: parsed.value,
    })
    next_version = Plan.model_validate(values["plan_detail"]).version + 1
    reason = (
        f"The user corrected {correction.fact_name}; rechecking affected "
        "scheme rules."
    )
    event = JourneyHistoryEvent(
        event_type="answer_corrected",
        fact_name=correction.fact_name,
        plan_version=next_version,
        reason=reason,
    )
    initial_state: JourneyState = {
        "action": "interview",
        "application_task": None,
        "application_task_result": None,
        "application_task_error": None,
        "document_assessments": {},
        "conversation_id": str(conversation_id),
        "scheme_id": "",
        "multi_scheme": True,
        "candidate_scheme_ids": list(values["candidate_scheme_ids"]),
        "profile": updated_profile.model_dump(mode="json"),
        "plan_detail": None,
        "plan_version_start": next_version,
        "plan_restart_reason": reason,
        "status": "",
        "message": "",
        "missing_fields": [],
        "passages": values.get("passages", []),
        "eligibility_result": None,
        "candidate_verdicts": {},
        "eligibility_results": {},
        "skipped_facts": sorted(
            set(values.get("skipped_facts", [])) - {correction.fact_name}
        ),
        "llm_attempted_facts": list(
            values.get("llm_attempted_facts", [])
        ),
        "pending_fact": None,
        "question": None,
        "pending_answer": None,
        "pending_confirmation": False,
        "pending_interpreted_value": None,
        "llm_attempted_facts": [],
        "conversation": [{
            "role": "assistant",
            "content": f"Answer corrected for {correction.fact_name}. Rechecking schemes.",
        }],
        "journey_history": [event.model_dump(mode="json")],
    }
    result = await graph.ainvoke(initial_state, config=config)
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
