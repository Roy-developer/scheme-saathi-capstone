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
- When configured, a bounded ReAct runtime lets the supervisor propose a
  dependency-checked plan and intake propose facts that the person confirms;
  deterministic C0 planning and question selection remain the safe fallback.
- Application actions preserve the saved profile and verdicts. The application
  agent alone writes to the portal and manages a separate, per-revision approval
  interrupt so other eligible schemes can still be checked while review waits.
"""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from datetime import date
from operator import add
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from mcp import Client
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from langchain_core.language_models import BaseChatModel

from src.api.eligibility import EligibilityResponse
from src.api.applications import (
    call_application_tool,
    check_and_bind_documents,
)
from src.api.scheme_search import SchemePassage
from src.mcp_servers.service_routing import ServiceClientRouter, ToolActor
from src.rules.bundles import SchemeBundle
from src.rules.bundles import bundle_fingerprint
from src.rules.facts import (
    FactDefinition,
    FactRegistry, FactState, HouseholdProfile, decode_wire_value, encode_wire_value,
)
from src.mcp_servers.rule_data import get_active_rule_data
from src.rules.models import RulePackage
from src.workflow.eligibility import evaluate_eligibility
from src.workflow.eligibility_agent import run_eligibility_specialist
from src.workflow.discovery import (
    MAX_DISCOVERY_CALLS, RELEVANT_FACT_TERMS, DiscoveryEvent, discovery_input, discovery_signature,
    discovery_message,
    merge_candidates,
)
from src.workflow.application_gate import (
    build_application_gate,
    pause_for_application_approval,
    resume_application_approval,
)
from src.workflow.agent_config import (
    MAX_CONVERSATION_HISTORY,
    MAX_HANDOFF_HISTORY,
    MAX_TRACE_EVENTS,
)
from src.workflow.agent_runtime import (
    AgentTraceEvent,
    DEFAULT_CHAT_MODEL,
    mask_sensitive_text,
    run_accounted_model_call,
)
from src.workflow.errors import MCPToolError
from src.workflow.conversation_budget import (
    CURRENT_BUDGET, ConversationBudget, attempted_facts as durable_attempted_facts,
    durable_counters, reserve_counters, reserve_fact,
)
from src.workflow.household_memory import (
    load_household,
    normalize_return_code,
)
from src.workflow.intake import (
    AnswerInterpretation,
    IntakeAgentError,
    interpret_free_text_answer,
    rewrite_scheme_query,
)
from src.workflow.input_guardrails import is_prompt_injection
from src.workflow.question_picker import (
    pick_shared_registered_fact,
)
from src.workflow.intake_agent import (
    propose_initial_registered_facts,
)
from src.workflow.scam_screen import apply_scam_screen, scam_warning_for_locale
from src.workflow.supervisor_agent import (
    propose_supervisor_plan,
)
from src.workflow.application_agent import (
    run_application_specialist,
)
from src.workflow.document_agent import (
    run_document_specialist,
)
from src.workflow.questions import (
    parse_confirmation,
    parse_interpreted_registered_answer,
    registered_confirmation_details,
    registered_direct_answer_question,
    registered_fact_confirmation,
    unknown_answer_label,
    ParsedAnswer,
    confirm_yes_or_no_question,
    parse_registered_answer,
    registered_question_details,
    registry_question_for,
    UNCLEAR_REPLY_PREFIX,
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
    replan_reason,
)

ANSWER_INTERPRETATION_CONFIDENCE = 0.85
MAX_CANDIDATE_SCHEMES = 20
MAX_INTERPRETER_CONTEXT = 3
SEARCH_PASSAGE_LIMIT = MAX_CANDIDATE_SCHEMES


def _merge_agent_trace(
    current: list[dict[str, Any]],
    added: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only recent scrubbed events in the durable conversation state."""

    return (current + added)[-MAX_TRACE_EVENTS:]


def _merge_conversation(
    current: list[dict[str, str]],
    added: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Keep only the most recent conversation turns in active graph state."""

    return (current + added)[-MAX_CONVERSATION_HISTORY:]


def _merge_handoffs(
    current: list[dict[str, Any]],
    added: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bound active graph state to recent agent handoffs."""

    return (current + added)[-MAX_HANDOFF_HISTORY:]


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
    profile_description: str | None = Field(default=None, max_length=1200)
    locale: Literal["en", "hi", "mr"] = "en"
    mode: Literal["citizen", "csc"] = "citizen"
    # CSC-assisted sessions require an explicit declaration that the citizen
    # is present; an operator cannot supply this confirmation on their behalf.
    citizen_present: bool = False
    return_code: str | None = None
    memory_consent: bool = False
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
        if self.profile_description is not None and self.action != "interview":
            raise ValueError("profile_description is only supported for interviews")
        if self.return_code and not self.memory_consent:
            raise ValueError("Loading household memory requires explicit consent")
        if (
            self.action == "interview"
            and self.mode == "csc"
            and not self.citizen_present
        ):
            raise ValueError("CSC-assisted intake requires the citizen to be present")
        return self


class JourneyCorrection(BaseModel):
    """A corrected answer for a registered or legacy fact already saved."""

    model_config = ConfigDict(extra="forbid")

    fact_name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    answer: str = Field(min_length=1, max_length=500)


class JourneyMessage(BaseModel):
    """The user's reply to the question the journey is waiting on."""

    model_config = ConfigDict(extra="forbid")

    # Short limit: answers are yes/no or a date, and it caps abuse.
    message: str = Field(min_length=1, max_length=500)


class QuestionChoice(BaseModel):
    """Localized label and stable code for a finite-choice answer."""

    code: str
    label: str


class QuestionPresentation(BaseModel):
    """Registry-derived widget and validation details for the pending fact."""

    fact_id: str
    value_type: str
    unit: str | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    max_length: int | None = None
    choices: list[QuestionChoice] = Field(default_factory=list)
    help_text: str | None = None
    confirming: bool = False


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
    profile_description: str | None
    locale: Literal["en", "hi", "mr"]
    mode: Literal["citizen", "csc"]
    citizen_present: bool
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
    question_definition: dict[str, Any] | None
    typed_facts: dict[str, Any] | None
    registry_intake: bool
    registry_dependencies: str | None
    dependency_review_required: bool
    fact_intake_mode: Literal["model_assisted", "deterministic_only"]
    fact_questions: dict[str, str]
    pending_answer: str | None
    pending_registered_answer: dict[str, Any] | None
    skipped_facts: list[str]
    pending_confirmation: bool
    pending_confirmation_source: str
    pending_interpreted_value: bool | str | None
    llm_attempted_facts: list[str]
    interpreter_context: list[str]
    return_code: str | None
    profile_proposals: list[dict[str, Any]]
    initial_description_processed: bool
    agent_budget: dict[str, int]
    agent_trace: Annotated[list[dict[str, Any]], _merge_agent_trace]
    react_status: str
    # Annotated with "add": new items are appended to the saved history
    # instead of replacing it.
    handoffs: Annotated[list[dict[str, Any]], _merge_handoffs]
    conversation: Annotated[list[dict[str, str]], _merge_conversation]
    application_task: dict[str, Any] | None
    application_task_result: dict[str, Any] | None
    application_task_error: dict[str, Any] | None
    document_assessments: dict[str, dict[str, Any]]
    document_input_reports: dict[str, dict[str, Any]]
    dependency_version: int
    dependency_blocked: bool
    search_calls: int
    discovery_signature: str
    discovery_notices: list[str]
    discovery_events: Annotated[list[dict[str, Any]], add]
    unprocessed_candidate_ids: list[str]


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
    locale: Literal["en", "hi", "mr"] = "en"
    mode: Literal["citizen", "csc"] = "citizen"
    mode_acknowledgement: str = ""
    react_status: Literal[
        "deterministic", "model_validated", "model_assisted",
        "deterministic_fallback",
    ] = "deterministic"
    agent_budget: dict[str, int] = Field(default_factory=dict)
    agent_trace: list[AgentTraceEvent] = Field(default_factory=list)
    # Set only while status is "awaiting_answer".
    question: str | None = None
    question_definition: QuestionPresentation | None = None
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
    known_fact_names: list[str] = Field(default_factory=list)
    correctable_fact_names: list[str] = Field(default_factory=list)
    fact_questions: dict[str, str] = Field(default_factory=dict)
    conversation: list[dict[str, str]] = Field(default_factory=list)
    document_assessments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    dependency_version: int = 0
    discovery_notices: list[str] = Field(default_factory=list)
    discovery_events: list[DiscoveryEvent] = Field(default_factory=list)
    discovery_messages: list[str] = Field(default_factory=list)
    return_code: str | None = None
    search_calls: int = 0
    unprocessed_candidate_ids: list[str] = Field(default_factory=list)


async def _search_with_mcp(
    client: Client,
    query: str,
) -> list[SchemePassage]:
    """Default search tool: ask for up to 20 passages for candidate discovery."""

    return await search_scheme_passages(
        client, query, limit=SEARCH_PASSAGE_LIMIT
    )


MODE_ACKNOWLEDGEMENTS: dict[str, dict[str, str]] = {
    "citizen": {
        "en": "You provide and confirm your own household facts.",
        "hi": "आप अपने परिवार की जानकारी स्वयं देते और पुष्टि करते हैं।",
        "mr": "तुम्ही स्वतःच्या कुटुंबाची माहिती देता आणि तिची पुष्टी करता.",
    },
    "csc": {
        "en": (
            "A CSC operator may assist while the citizen is present. The "
            "citizen confirms every fact and must personally approve any exact draft."
        ),
        "hi": (
            "नागरिक की उपस्थिति में CSC ऑपरेटर सहायता कर सकता है। हर तथ्य की "
            "पुष्टि नागरिक करेंगे और किसी भी आवेदन का अनुमोदन भी नागरिक ही करेंगे।"
        ),
        "mr": (
            "नागरिक उपस्थित असताना CSC ऑपरेटर मदत करू शकतो. प्रत्येक तथ्याची "
            "पुष्टी नागरिक करतात आणि कोणत्याही अर्जाला मंजुरीही नागरिकच देतात."
        ),
    },
}

INPUT_GUARDRAIL_MESSAGES: dict[str, str] = {
    "en": (
        "I can help with government benefit schemes and eligibility, but I can't "
        "follow instructions to change my role or reveal internal instructions. "
        "Please ask a scheme-related question."
    ),
    "hi": (
        "मैं सरकारी लाभ योजनाओं और पात्रता में मदद कर सकता हूँ, लेकिन अपनी भूमिका "
        "बदलने या आंतरिक निर्देश बताने वाले निर्देशों का पालन नहीं कर सकता। कृपया "
        "योजना से जुड़ा प्रश्न पूछें।"
    ),
    "mr": (
        "मी सरकारी लाभ योजना आणि पात्रता याबद्दल मदत करू शकतो; पण माझी भूमिका "
        "बदलण्याच्या किंवा अंतर्गत सूचना उघड करण्याच्या सूचनांचे पालन करू शकत "
        "नाही. कृपया योजनेशी संबंधित प्रश्न विचारा."
    ),
}


def _guardrail_response(
    conversation_id: UUID,
    locale: Literal["en", "hi", "mr"],
    mode: Literal["citizen", "csc"],
) -> JourneyResponse:
    """Return a localized refusal without persisting or forwarding the input."""

    return JourneyResponse(
        conversation_id=conversation_id,
        plan="",
        status="invalid_input",
        message=INPUT_GUARDRAIL_MESSAGES[locale],
        locale=locale,
        mode=mode,
        mode_acknowledgement=MODE_ACKNOWLEDGEMENTS[mode][locale],
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


# The state fields that say "a question is waiting for an answer".
# Spread this into an update to clear all of them together.
NO_PENDING_QUESTION: dict[str, Any] = {
    "pending_fact": None,
    "question": None,
    "question_definition": None,
    "pending_answer": None,
    "pending_registered_answer": None,
    "pending_confirmation": False,
    "pending_confirmation_source": "",
    "pending_interpreted_value": None,
}


def confirmed_answers(values: Mapping[str, Any]) -> dict[str, object]:
    """Return the confirmed answers saved on a draft, keyed by fact ID."""

    typed = values.get("typed_facts") or {}
    return {
        fact_id: fact["value"]
        for fact_id, fact in typed.get("facts", {}).items()
        if fact.get("status") == "known"
    }



def build_journey_graph(
    client: Client,
    rule_packages: Mapping[str, RulePackage],
    *,
    search_tool: Callable[
        [Client, str], Awaitable[list[SchemePassage]]
    ] = _search_with_mcp,
    eligibility_tool: Callable[
        [Client, str, HouseholdProfile],
        Awaitable[EligibilityResponse],
    ] = _evaluate_with_mcp,
    query_rewriter: Callable[[str], Awaitable[str]] = rewrite_scheme_query,
    answer_interpreter: Callable[
        [str, str, str], Awaitable[AnswerInterpretation]
    ] = interpret_free_text_answer,
    model_provider: BaseChatModel | None = None,
    eligibility_model_provider: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
    today: Callable[[], date] = date.today,
    application_tool: Callable[
        [Client, str, dict[str, Any]], Awaitable[dict[str, Any]]
    ] = call_application_tool,
    fact_registry: FactRegistry | None = None,
    rule_bundles: Mapping[str, SchemeBundle] | None = None,
) -> Any:
    """Build and compile the supervisor journey with a checkpointer.

    Args:
        client: Connected MCP client used by the tool nodes.
        rule_packages: Loaded rule packages; intake uses them to know which
            schemes can be checked and which facts each one needs.
        fact_registry, rule_bundles: Validated registry dependencies used for
            data-defined questions and typed facts; omitted for legacy callers.
        search_tool, eligibility_tool, query_rewriter, answer_interpreter,
        model_provider, eligibility_model_provider, application_tool:
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
    offline_dependency_versions: dict[str, int] = {}

    def specialist_client(
        actor: ToolActor, journey_id: str | None = None
    ) -> Client | ServiceClientRouter:
        """Use code-owned caller capabilities; injected test clients stay compatible."""

        if isinstance(client, ServiceClientRouter):
            return client.for_actor(actor, journey_id)
        return client

    async def dependency_action(
        conversation_id: str, action: str, version: int | None = None
    ) -> int:
        """Hold portal writes closed across a profile checkpoint transition."""

        # A C0 graph without the service router cannot perform portal writes.
        # Explicit portal test adapters still exercise the durable transaction.
        if not isinstance(client, ServiceClientRouter) and application_tool is call_application_tool:
            if action == "begin_profile_change":
                offline_dependency_versions[conversation_id] = version or (
                    offline_dependency_versions.get(conversation_id, 0) + 1
                )
            return version if version is not None else offline_dependency_versions[conversation_id]
        arguments: dict[str, Any] = {"journey_id": conversation_id, "action": action}
        if version is not None:
            arguments["dependency_version"] = version
        response = await application_tool(
            specialist_client("dependency_control", conversation_id),
            "mock_portal", arguments,
        )
        return int(response["dependency_version"])

    async def verify_dependencies(conversation_id: str, version: int) -> bool:
        """Check reconciliation without modifying a paused graph checkpoint."""

        if not isinstance(client, ServiceClientRouter) and application_tool is call_application_tool:
            return True
        response = await application_tool(
            specialist_client("dependency_control", conversation_id), "mock_portal",
            {"journey_id": conversation_id, "action": "dependency_status"},
        )
        return (
            response.get("blocked") is False
            and response.get("dependency_version") == version
        )

    if fact_registry is None or rule_bundles is None:
        active_rules = get_active_rule_data()
        fact_registry = fact_registry or active_rules.registry
        rule_bundles = active_rules.bundles if rule_bundles is None else rule_bundles

    def registry_dependencies() -> str | None:
        """Bind meaning, review state, bundle mappings and rule contents together."""

        if fact_registry is None:
            return None
        data = {
            "registry": fact_registry.model_dump(mode="json"),
            "bundles": {
                key: value.model_dump(mode="json")
                for key, value in (rule_bundles or {}).items()
            },
            "packages": {
                key: value.model_dump(mode="json")
                for key, value in rule_packages.items()
            },
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    async def bind_rules(state: JourneyState, scheme_id: str) -> None:
        """Invalidate saved approvals when an observed rule package changes."""

        if not isinstance(client, ServiceClientRouter) and application_tool is call_application_tool:
            return
        package = rule_packages.get(scheme_id)
        fingerprint = hashlib.sha256(json.dumps(
            {"package": package.model_dump(mode="json") if package else
             {"scheme_id": scheme_id, "status": "information_only"},
             "registry_dependencies": registry_dependencies()},
            sort_keys=True,
        ).encode("utf-8")).hexdigest()
        await application_tool(
            specialist_client("dependency_control", state["conversation_id"]),
            "mock_portal",
            {"action": "bind_rules", "journey_id": state["conversation_id"],
             "scheme_id": scheme_id, "rules_fingerprint": fingerprint,
             "dependency_version": state.get("dependency_version", 0)},
        )

    def restore_typed_store(data: object) -> HouseholdProfile:
        """Restore checkpoint JSON without allowing JSON strings to coerce types."""

        if fact_registry is None:
            raise ValueError("A fact registry is required for typed intake")
        if not isinstance(data, dict):
            return HouseholdProfile(
             registry_version=fact_registry.registry_version, facts={}
            )
        return HouseholdProfile.from_wire(data, fact_registry)

    def validate_registered_store(
        store: HouseholdProfile,
        candidate_ids: list[str],
    ) -> HouseholdProfile:
        """Check a proposed store; cross-fact checks live in the store itself."""

        return store.validate_against(fact_registry)

    async def discover_candidates(
        state: JourneyState,
        facts: Mapping[str, object],
        age: int | None,
    ) -> dict[str, Any]:
        """Rediscover candidates from explicitly confirmed supported profile facts."""

        updates: dict[str, Any] = {}
        if not state.get("multi_scheme"):
            return updates
        candidates = state.get("candidate_scheme_ids", [])
        locale = state.get("locale", "en")
        signature = discovery_signature(facts, age)
        search = discovery_input(facts, age, locale)
        query = search.query
        if signature == state.get("discovery_signature", "") or not query:
            return updates
        calls = durable_counters({"search_calls": state.get("search_calls", 0)})["search_calls"]
        notices = list(state.get("discovery_notices", []))
        updates["discovery_signature"] = signature
        if calls >= MAX_DISCOVERY_CALLS:
            notices.append("budget_exhausted")
            updates["discovery_events"] = [
                DiscoveryEvent(
                    code="budget_exhausted", search_calls=calls,
                ).model_dump(mode="json")
            ]
        else:
            found = None
            # Hand-written retry, not RetryPolicy: a failed attempt must leave a visible
            # history note and the final failure must become a calm reply, not an error.
            for attempt in (1, 2):
                if calls >= MAX_DISCOVERY_CALLS:
                    break
                calls += 1
                await reserve_counters({"search_calls": calls})
                try:
                    if search_tool is _search_with_mcp:
                        found = await search_scheme_passages(
                            specialist_client("eligibility"), query,
                            language=search.language, limit=search.limit,
                        )
                    else:
                        found = await search_tool(specialist_client("eligibility"), query)
                    break
                except MCPToolError:
                    if attempt == 1 and calls < MAX_DISCOVERY_CALLS:
                        updates.setdefault("discovery_events", []).append(
                            DiscoveryEvent(code="tool_retry", search_calls=calls).model_dump(mode="json")
                        )
            updates["search_calls"] = calls
            if found is None:
                notices.append("tool_error")
            else:
                updates["passages"] = list({
                    item["passage_id"]: item for item in [
                        *state.get("passages", []),
                        *(item.model_dump(mode="json") for item in found),
                    ]
                }.values())
                updated, excess = merge_candidates(
                    candidates,
                    [*state.get("unprocessed_candidate_ids", []),
                     *(passage.scheme_id for passage in found)],
                )
                added = [candidate for candidate in updated if candidate not in candidates]
                updates["unprocessed_candidate_ids"] = excess
                if excess:
                    notices.append("candidate_limit")
                if added:
                    refreshed = build_initial_plan(
                        "interview", candidate_scheme_ids=updated, locale=locale,
                    )
                    old_plan = Plan.model_validate(state["plan_detail"])
                    refreshed = refreshed.model_copy(update={
                        "version": old_plan.version + 1,
                        "replan_reason": "Confirmed facts added retrieved candidates.",
                    })
                    updates.update({
                        "candidate_scheme_ids": updated,
                        "plan_detail": refreshed.model_dump(mode="json"),
                    })
                    notices.append("candidates_added")
            updates.setdefault("discovery_events", []).append(
                DiscoveryEvent(
                    code=(
                        "tool_error" if found is None
                        else "candidates_added" if added
                        else "search_completed"
                    ),
                    search_calls=calls,
                    candidate_ids=added if found is not None else [],
                    unprocessed_candidate_ids=(
                        excess if found is not None else
                        state.get("unprocessed_candidate_ids", [])
                    ),
                ).model_dump(mode="json")
            )
        updates["discovery_notices"] = list(dict.fromkeys(notices))
        return updates

    def registered_evaluation_input(
        scheme_id: str | None, answers: dict[str, object], packages: list[RulePackage],
    ) -> dict[str, Any]:
        """Check a complete set of answers sent with an evaluate request."""

        allowed = {
            fact_id for package in packages
            for fact_id in (rule_bundles or {})[package.scheme_id].fact_ids
        }
        invalid = sorted(
            fact_id for fact_id, value in answers.items()
            if not _valid_answer(fact_id, value)
        )
        store = None
        if not invalid:
            try:
                store = HouseholdProfile.from_answers(
                    {fact_id: value for fact_id, value in answers.items() if fact_id in allowed},
                    fact_registry,
                )
            except (KeyError, TypeError, ValueError):
                pass
        if store is None:
            return {
                "status": "invalid_input",
                "message": (
                    "Some profile answers are missing or invalid. Review "
                    "the highlighted fields and try again."
                ),
                "missing_fields": invalid,
                "validation_errors": invalid,
                "eligibility_result": None,
                "handoffs": _report_to_supervisor("intake", "invalid_input"),
            }
        return {
            "scheme_id": scheme_id,
            "profile": {},
            "typed_facts": store.to_wire(fact_registry),
            "registry_intake": True,
            "status": "ready_for_eligibility",
            "missing_fields": [],
            "eligibility_result": None,
            "conversation": [
                {"role": "user", "content": f"Check eligibility for {scheme_id}."}
            ],
            "handoffs": _report_to_supervisor("intake", "ready_for_eligibility"),
        }

    def _valid_answer(fact_id: str, value: object) -> bool:
        """Return whether one supplied answer fits its registered fact."""

        try:
            HouseholdProfile.from_answers({fact_id: value}, fact_registry)
        except (KeyError, TypeError, ValueError):
            return False
        return True

    async def registered_intake_result(
        state: JourneyState,
        packages: list[RulePackage],
    ) -> dict[str, Any]:
        """Collect one registry-backed fact and persist compatible typed values."""

        if fact_registry is None:
            raise ValueError("A fact registry is required for typed intake")
        bundles = [(rule_bundles or {}).get(package.scheme_id) for package in packages]
        if not bundles or any(bundle is None for bundle in bundles):
            raise ValueError("A validated scheme bundle is required for typed intake")
        allowed_facts = {
            fact_id for bundle in bundles if bundle for fact_id in bundle.fact_ids
        }
        if state.get("multi_scheme"):
            allowed_facts |= set(RELEVANT_FACT_TERMS) & {
                definition.fact_id for definition in fact_registry.definitions
            }
        try:
            store = restore_typed_store(state.get("typed_facts"))
            facts = dict(store.facts)
            # Answers sent with the request; later steps use the store alone.
            if state.get("profile") and not state.get("typed_facts"):
                supplied = HouseholdProfile.from_answers(state["profile"], fact_registry)
                # A household's answers can cover more than these schemes use;
                # keeping them lets a later correction discover other schemes.
                for fact_id, fact in supplied.facts.items():
                    if fact_id in facts and facts[fact_id].value != fact.value:
                        raise ValueError("Use a correction to replace a saved answer")
                    facts.setdefault(fact_id, fact)
            for fact_id in allowed_facts & set(state.get("skipped_facts", [])):
                if fact_id not in facts:
                    facts[fact_id] = FactState(
                        status="declined",
                        definition_version=fact_registry.get(fact_id).version,
                    )
            store = store.model_copy(update={"facts": facts})
            store.validate_against(fact_registry)
        except (KeyError, TypeError, ValueError) as error:
            return {
                "status": "invalid_input",
                "message": (
                    "Saved answers use a different fact definition. "
                    "Start a new conversation to review them."
                ),
                "validation_errors": ["fact_definition_version"],
                "eligibility_result": None,
                "question": None,
                "question_definition": None,
                "pending_fact": None,
                "handoffs": _report_to_supervisor("intake", "invalid_input"),
            }

        # People apply "today"; asking them for it would be odd.
        if "application_date" in allowed_facts and "application_date" not in store.facts:
            application_date = fact_registry.get("application_date")
            store = HouseholdProfile(
                registry_version=fact_registry.registry_version,
                facts={**store.facts, "application_date": FactState(
                    status="known",
                    value=application_date.validate_value(today()),
                    definition_version=application_date.version,
                    provenance="user_reported",
                )},
            ).validate_against(fact_registry)
        skipped = set(state.get("skipped_facts", [])) | {
            fact_id for fact_id, fact in store.facts.items()
            if fact.status == "declined"
        }
        locale = state.get("locale", "en")
        agent_budget = state.get("agent_budget", {})
        trace_events: list[dict[str, Any]] = []
        react_status = state.get("react_status", "deterministic")
        discovery_notices = list(state.get("discovery_notices") or [])
        scam_screened_this_turn = False
        attempted = durable_attempted_facts(state.get("llm_attempted_facts") or [])
        interp_ctx: list[str] = list(state.get("interpreter_context") or [])
        proposals = list(state.get("profile_proposals") or [])

        def progress() -> dict[str, Any]:
            """Everything a registered intake step must save with its reply."""

            return {
                "registry_intake": True,
                "typed_facts": store.to_wire(fact_registry),
                "skipped_facts": sorted(skipped),
                "llm_attempted_facts": sorted(attempted),
                "interpreter_context": interp_ctx[-MAX_INTERPRETER_CONTEXT:],
                "profile_proposals": proposals,
                "profile_description": None,
                "initial_description_processed": True,
                "fact_intake_mode": (
                    "deterministic_only"
                    if deterministic_fact_intake else "model_assisted"
                ),
                "agent_budget": agent_budget,
                "agent_trace": trace_events,
                "react_status": react_status,
            }

        def waiting_on(
            fact_id: str,
            message: str,
            details: dict[str, object],
            *,
            confirming: bool = False,
            source: str = "",
            proposed: object = None,
        ) -> dict[str, Any]:
            """Pause for one reply about one registered fact."""

            return {
                **progress(),
                "status": "awaiting_answer",
                "message": message,
                "question": message,
                "question_definition": details,
                "pending_fact": fact_id,
                "pending_answer": None,
                "pending_registered_answer": None,
                "pending_confirmation": confirming,
                "pending_confirmation_source": source,
                "pending_interpreted_value": proposed,
                "conversation": [{"role": "assistant", "content": message}],
            }

        def ask_directly(definition: FactDefinition, message: str) -> dict[str, Any]:
            return waiting_on(
                definition.fact_id, message,
                registered_question_details(definition, locale),
            )

        def ask_to_confirm(
            fact_id: str, proposed: object, source: str, message: str | None = None,
        ) -> dict[str, Any]:
            definition = fact_registry.get(fact_id)
            return waiting_on(
                fact_id,
                message or registered_fact_confirmation(definition, proposed, locale),
                registered_confirmation_details(definition),
                confirming=True, source=source, proposed=proposed,
            )

        def ask_next_proposal() -> dict[str, Any]:
            proposal = proposals.pop(0)
            return ask_to_confirm(
                str(proposal["fact_name"]), proposal["value"], "initial_profile",
            )

        def with_fact(fact_id: str, fact_state: FactState) -> None:
            nonlocal store
            store = HouseholdProfile(
                registry_version=fact_registry.registry_version,
                facts={**store.facts, fact_id: fact_state},
            ).validate_against(fact_registry)

        def record_answer(definition: FactDefinition, value: object) -> None:
            with_fact(definition.fact_id, FactState(
                status="known",
                value=definition.validate_value(value),
                definition_version=definition.version,
                provenance="user_reported",
            ))

        def record_not_known(definition: FactDefinition) -> None:
            skipped.add(definition.fact_id)
            with_fact(definition.fact_id, FactState(
                status="declined", definition_version=definition.version,
            ))

        description = state.get("profile_description")
        needed = tuple(dict.fromkeys(
            fact for package in packages for fact in package.required_facts
            if fact in allowed_facts
        ))
        intake_scheme_ids = set(state.get("candidate_scheme_ids") or [])
        if not intake_scheme_ids and state.get("scheme_id"):
            intake_scheme_ids.add(state["scheme_id"])
        intake_packages = [
            package for package in packages
            if package.scheme_id in intake_scheme_ids
        ]
        deterministic_fact_intake = any(
            package.fact_intake_mode == "deterministic_only"
            for package in intake_packages
        )
        if (
            description
            and not state.get("initial_description_processed")
            and not deterministic_fact_intake
        ):
            (
                proposals, agent_budget, description_trace, react_status,
            ) = await propose_initial_registered_facts(
                model_provider,
                specialist_client("intake", state["conversation_id"]),
                "intake",
                packages[0].scheme_id,
                description,
                store,
                fact_registry,
                needed,
                locale,
                agent_budget,
                discovery_facts=tuple(
                    fact for fact in ("is_widow", "landholding_family_in_state_records")
                    if state.get("multi_scheme") and fact in allowed_facts
                ),
            )
            trace_events.extend(description_trace)
            if react_status == "scam_screened":
                scam_screened_this_turn = True
                discovery_notices.append("scam_screened")
                react_status = "deterministic"
            if react_status == "model_assisted":
                interp_ctx.append(f"description: {description}")

        pending_fact = state.get("pending_fact")
        pending_registered_answer = state.get("pending_registered_answer")
        if pending_fact and pending_registered_answer is not None:
            if pending_fact not in allowed_facts:
                return {
                    "status": "invalid_input",
                    "message": "The saved question is not compatible with this scheme.",
                    "validation_errors": ["pending_fact"],
                    "eligibility_result": None,
                    "handoffs": _report_to_supervisor("intake", "invalid_input"),
                }
            definition = fact_registry.get(pending_fact)
            answer_kind = pending_registered_answer.get("kind")
            if answer_kind == "confirmation":
                decision = pending_registered_answer.get("decision")
                source = state.get("pending_confirmation_source", "")
                proposed = state.get("pending_interpreted_value")
                if decision == "unknown":
                    record_not_known(definition)
                elif decision == "no":
                    if not (source == "initial_profile" and proposals):
                        return ask_directly(
                            definition,
                            registered_direct_answer_question(definition, locale),
                        )
                elif decision == "yes":
                    parsed = parse_interpreted_registered_answer(definition, proposed, locale)
                    if parsed.kind != "value":
                        return ask_directly(
                            definition,
                            f"{parsed.error} {registry_question_for(definition, locale)}",
                        )
                    try:
                        record_answer(definition, parsed.value)
                    except (TypeError, ValueError):
                        return ask_directly(definition, " ".join((
                            discovery_message("invalid_input", locale),
                            registry_question_for(definition, locale),
                        )))
                else:
                    return ask_to_confirm(
                        pending_fact, proposed, source, confirm_yes_or_no_question(locale),
                    )
            elif answer_kind == "invalid":
                reply = pending_registered_answer.get("reply")
                scam_reply = (
                    apply_scam_screen(reply) if isinstance(reply, str) else None
                )
                if scam_reply is not None and scam_reply.flagged:
                    scam_screened_this_turn = True
                    discovery_notices.append("scam_screened")
                    warning = scam_warning_for_locale(locale)
                    prior_question = state.get("question") or state.get("message") or ""
                    details = (
                        registered_confirmation_details(definition)
                        if state.get("pending_confirmation")
                        else registered_question_details(definition, locale)
                    )
                    response = waiting_on(
                        pending_fact,
                        f"{warning}\n\n{prior_question}".strip(),
                        details,
                        confirming=bool(state.get("pending_confirmation")),
                        source=state.get("pending_confirmation_source", ""),
                        proposed=state.get("pending_interpreted_value"),
                    )
                    response["discovery_notices"] = list(
                        dict.fromkeys(discovery_notices)
                    )
                    return response
                if (
                    definition.value_type in {"boolean", "date"}
                        and not deterministic_fact_intake
                    and isinstance(reply, str)
                    and pending_fact not in attempted
                ):
                    await reserve_fact(pending_fact)
                    attempted.add(pending_fact)
                    interpretation = None
                    question = registry_question_for(definition, locale)
                    if not (
                        answer_interpreter is interpret_free_text_answer
                        and model_provider is None
                    ):
                        (
                            interpretation, agent_budget, call_trace, call_status,
                        ) = await run_accounted_model_call(
                            agent="intake",
                            action="interpret_free_text_answer",
                            model=(
                                model_provider.model_name
                                if model_provider is not None
                                else DEFAULT_CHAT_MODEL
                            ),
                            input_text=f"{pending_fact}\n{question}\n{reply}",
                            budget=agent_budget,
                            callback=lambda: (
                                answer_interpreter(
                                    pending_fact, question, reply,
                                    prior_exchanges=interp_ctx[-MAX_INTERPRETER_CONTEXT:],
                                )
                                if answer_interpreter is interpret_free_text_answer
                                else answer_interpreter(pending_fact, question, reply)
                            ),
                            failure_type=IntakeAgentError,
                        )
                        trace_events.extend(call_trace)
                        react_status = (
                            "model_assisted" if call_status == "model_assisted"
                            else "deterministic_fallback"
                        )
                        interp_ctx.append(f"Q({pending_fact}): {question} → {reply}")
                    confident = (
                        interpretation is not None
                        and interpretation.confidence >= ANSWER_INTERPRETATION_CONFIDENCE
                    )
                    if confident and interpretation.kind == "unknown":
                        record_not_known(definition)
                    elif (
                        confident
                        and interpretation.kind == "value"
                        and interpretation.value is not None
                    ):
                        candidate = parse_interpreted_registered_answer(
                            definition, interpretation.value, locale,
                        )
                        if candidate.kind == "value":
                            value = candidate.value
                            try:
                                _replace_registered_fact(
                                    store, fact_registry, pending_fact, value, "known",
                                )
                            except (TypeError, ValueError):
                                pass
                            else:
                                return ask_to_confirm(
                                    pending_fact,
                                    value.isoformat() if hasattr(value, "isoformat") else value,
                                    "answer_interpretation",
                                )
                if pending_fact not in skipped:
                    prefix = UNCLEAR_REPLY_PREFIX.get(locale, UNCLEAR_REPLY_PREFIX["en"])
                    error = str(pending_registered_answer.get(
                        "error", "Please provide an answer in the registered format.",
                    ))
                    return ask_directly(
                        definition,
                        f"{prefix} {error} {registry_question_for(definition, locale)}",
                    )
            elif answer_kind == "unknown":
                record_not_known(definition)
            elif answer_kind == "value":
                record_answer(definition, decode_wire_value(
                    definition, pending_registered_answer.get("value")
                ))
            else:
                raise ValueError("Saved registered answer has an invalid status")

        if proposals:
            return ask_next_proposal()

        profile_data: dict[str, object] = {}
        discovery_updates = await discover_candidates(
            state,
            {
                fact_id: fact.value for fact_id, fact in store.facts.items()
                if fact.status == "known"
            },
            (
                store.value("age", fact_registry)
                if any(item.fact_id == "age" for item in fact_registry.definitions)
                else None
            ),
        )
        if scam_screened_this_turn:
            notices = list(
                discovery_updates.get("discovery_notices")
                or state.get("discovery_notices")
                or []
            )
            notices.append("scam_screened")
            discovery_updates["discovery_notices"] = list(dict.fromkeys(notices))
        if discovery_updates.get("candidate_scheme_ids"):
            packages = [
                rule_packages[candidate]
                for candidate in discovery_updates["candidate_scheme_ids"]
                if candidate in rule_packages
            ]
        next_fact = pick_shared_registered_fact(
            store, packages, fact_registry, frozenset(skipped)
        )
        common = {
            **discovery_updates,
            **progress(),
            "registry_intake": True,
            "fact_intake_mode": "model_assisted",
            "fact_questions": {
                fact_id: registry_question_for(
                    fact_registry.get(fact_id), state.get("locale", "en")
                )
                for fact_id in store.facts
            },
        }
        if next_fact is not None:
            definition = fact_registry.get(next_fact)
            question = registry_question_for(definition, state.get("locale", "en"))
            return {
                **common,
                "profile": profile_data,
                "typed_facts": store.to_wire(fact_registry),
                "profile_description": None,
                "initial_description_processed": True,
                "skipped_facts": sorted(skipped),
                "status": "awaiting_answer",
                "message": question,
                "question": question,
                "question_definition": registered_question_details(
                    definition, state.get("locale", "en")
                ),
                "pending_fact": next_fact,
                "pending_answer": None,
                "pending_registered_answer": None,
                "pending_confirmation": False,
                "pending_confirmation_source": "",
                "pending_interpreted_value": None,
                "eligibility_result": None,
                "conversation": [{"role": "assistant", "content": question}],
            }
        return {
            **common,
            "profile": profile_data,
            "typed_facts": store.to_wire(fact_registry),
            "profile_description": None,
            "initial_description_processed": True,
            "skipped_facts": sorted(skipped),
            "status": "ready_for_eligibility",
            "message": "",
            **NO_PENDING_QUESTION,
            "missing_fields": [],
            "eligibility_result": None,
            "handoffs": _report_to_supervisor("intake", "ready_for_eligibility"),
        }

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
                    state.get("locale", "en"),
                )
            agent_budget = state.get("agent_budget", {})
            trace_events: list[dict[str, Any]] = []
            planning_mode = "deterministic"
            if not task_data:
                (
                    plan,
                    agent_budget,
                    trace_events,
                    planning_mode,
                ) = await propose_supervisor_plan(
                    model_provider,
                    plan,
                    state.get("locale", "en"),
                    agent_budget,
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
            summary = plan_summary(plan, state.get("locale", "en"))
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
                "agent_budget": agent_budget,
                "agent_trace": trace_events,
                "react_status": planning_mode,
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
            reason = replan_reason(scheme_id, verdict, state.get("locale", "en"))
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
                update["message"] = discovery_message("checks_finished", state.get("locale", "en"))
                if any(
                    verdict["result"] == "tool_error"
                    for verdict in state.get("candidate_verdicts", {}).values()
                ):
                    update["message"] = discovery_message("checks_partial", state.get("locale", "en"))
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
        """Check user-entered metadata through a read-only bounded specialist."""

        task = ApplicationTask.model_validate(state["application_task"])
        arguments = task.arguments
        scheme_id = arguments["scheme_id"]
        verdict = state.get("candidate_verdicts", {}).get(scheme_id, {})
        if verdict.get("result") != "eligible" or scheme_id not in rule_packages:
            return task_failure("documents", "This scheme has no current eligible result.")
        tool_failed = False
        prior_input = state.get("document_input_reports", {}).get(scheme_id, {})
        current_answers = confirmed_answers(state)
        if task.operation == "check_documents" or task.operation == "create_draft":
            documents = arguments.get("documents", {})
            profile_name = arguments.get("profile_name")
            document_metadata = arguments.get("document_metadata", {})
            typed_facts = arguments.get("typed_facts", state.get("typed_facts"))
        else:
            documents = prior_input.get(
                "documents", arguments.get("documents", {})
            )
            profile_name = prior_input.get("profile_name")
            document_metadata = prior_input.get("document_metadata", {})
            typed_facts = state.get("typed_facts")
        profile_date_of_birth = current_answers.get("date_of_birth")
        # Sent to the checker and also part of the report fingerprint.
        profile_conditions = {
            "is_widow": current_answers.get("is_widow"),
            "bpl_card_shown": current_answers.get("bpl_card_shown"),
        }

        async def inspect() -> dict[str, object]:
            nonlocal tool_failed
            try:
                return await check_and_bind_documents(
                    application_tool,
                    specialist_client("documents"),
                    specialist_client("dependency_control", state["conversation_id"]),
                    journey_id=state["conversation_id"],
                    scheme_id=scheme_id,
                    documents=documents,
                    profile_name=profile_name,
                    profile_date_of_birth=profile_date_of_birth,
                    document_metadata=document_metadata,
                    typed_facts=typed_facts,
                    profile_conditions=profile_conditions,
                    bundle_fingerprint=(
                        bundle_fingerprint(rule_bundles[scheme_id])
                        if rule_bundles and scheme_id in rule_bundles
                        else ""
                    ),
                    dependency_version=state.get("dependency_version", 0),
                )
            except MCPToolError:
                tool_failed = True
                raise

        try:
            assessment, budget, trace, react_status = await run_document_specialist(
                model_provider,
                scheme_id,
                state.get("locale", "en"),
                state.get("agent_budget", {}),
                inspect,
            )
        except MCPToolError:
            assessment = None
            budget = state.get("agent_budget", {})
            trace = []
            react_status = "deterministic_fallback"
        if assessment is None:
            if tool_failed:
                return task_failure(
                    "documents", "The document checklist is unavailable.", 502
                )
            return task_failure(
                "documents", "The document specialist could not complete its check."
            )
        assessment = {
            **assessment,
            "profile_dependency_version": state.get("dependency_version", 0),
        }
        return {
            "application_task_result": assessment,
            "document_assessments": {
                **state.get("document_assessments", {}),
                scheme_id: assessment,
            },
            "document_input_reports": {
                **state.get("document_input_reports", {}),
                scheme_id: {
                    "documents": documents,
                    "profile_name": profile_name,
                    "document_metadata": document_metadata,
                    "typed_facts": typed_facts,
                },
            },
            "agent_budget": budget,
            "agent_trace": trace,
            "react_status": react_status,
            "handoffs": _report_to_supervisor("documents", assessment["status"]),
        }

    async def application_agent(state: JourneyState) -> dict[str, Any]:
        """Own portal mutations and the checkpointed exact-draft approval pause."""

        task = ApplicationTask.model_validate(state["application_task"])
        arguments = {
            **task.arguments,
            "action": task.operation,
            "journey_id": state["conversation_id"],
            "dependency_version": state.get("dependency_version", 0),
        }
        if task.operation in {"create_draft", "edit_draft", "approve", "reject"}:
            if application_gate is None:
                return task_failure(
                    "application", "Application approval requires checkpoint persistence."
                )
        operation_failure: dict[str, Any] | None = None
        tool_failed = False

        def fail(detail: str) -> dict[str, object]:
            """Record why the action is blocked and finish it with no result.

            Returning ``{}`` (instead of raising) marks the action as done, so
            the model cannot retry it and the specific reason is kept.
            """

            nonlocal operation_failure
            operation_failure = task_failure("application", detail)
            return {}

        async def execute() -> dict[str, object]:
            nonlocal tool_failed
            try:
                if task.operation == "create_draft":
                    scheme_id = arguments["scheme_id"]
                    assessment = state.get("document_assessments", {}).get(scheme_id)
                    if (
                        assessment is None
                        or assessment.get("status") != "checklist_complete"
                        or assessment.get("profile_dependency_version")
                        != state.get("dependency_version", 0)
                    ):
                        return fail("Recheck the documents against the current confirmed profile.")
                    await bind_rules(state, scheme_id)
                record = None
                if task.operation in {"edit_draft", "approve", "reject", "submit"}:
                    record = await application_tool(
                        specialist_client("application", state["conversation_id"]),
                        "mock_portal",
                        {
                            "action": "get_draft",
                            "journey_id": state["conversation_id"],
                            "draft_id": arguments["draft_id"],
                        },
                    )
                    if not record.get("not_found"):
                        # Binding the current rules can mark this draft stale,
                        # so read it again before checking it.
                        await bind_rules(state, record["scheme_id"])
                        record = await application_tool(
                            specialist_client("application", state["conversation_id"]),
                            "mock_portal",
                            {
                                "action": "get_draft",
                                "journey_id": state["conversation_id"],
                                "draft_id": arguments["draft_id"],
                            },
                        )
                    if record.get("not_found"):
                        return fail("This draft was not found. Reload and review it.")
                    if record.get("stale"):
                        return fail("The draft is stale. Create a fresh draft.")
                    if record["revision"] != arguments["revision"]:
                        return fail("The draft revision changed. Reload and review it.")
                    if (
                        task.operation != "edit_draft"
                        and record["fingerprint"] != arguments["fingerprint"]
                    ):
                        return fail("The draft fingerprint changed. Reload and review it.")
                    if task.operation == "submit" and not record["approved"]:
                        return fail(
                            "Approve this exact draft again; its prior approval expired or is no longer current.",
                        )
                    if (
                        task.operation == "approve"
                        and (record["rejected"] or record["receipt_id"])
                    ) or (
                        task.operation in {"edit_draft", "reject"} and record["receipt_id"]
                    ):
                        return fail("This draft cannot be changed in its current state.")
                if task.operation in {"create_draft", "edit_draft", "approve", "submit"}:
                    scheme_id = record["scheme_id"] if record else arguments["scheme_id"]
                    verdict = state.get("candidate_verdicts", {}).get(scheme_id, {})
                    package = rule_packages.get(scheme_id)
                    if (
                        not state.get("typed_facts")
                        or package is None
                        or verdict.get("result") != "eligible"
                    ):
                        return fail("This scheme has no current eligible profile.")
                    saved_answers = confirmed_answers(state)
                    if record and (
                        record["draft"]["profile"] != saved_answers
                        or record["draft"]["rule_package_version"] != package.package_version
                    ):
                        return fail("Answers or scheme rules changed. Create a new draft.")
                    if task.operation != "edit_draft":
                        confirmed_facts = restore_typed_store(state["typed_facts"])
                        current_verdict = await eligibility_tool(
                            specialist_client("eligibility"),
                            scheme_id,
                            confirmed_facts,
                        )
                        if current_verdict.result != "eligible":
                            return fail(
                                "The current profile is no longer eligible under the mock rules.",
                            )
                    if task.operation == "create_draft":
                        arguments.update({
                            "profile": saved_answers,
                            "rule_package_version": package.package_version,
                            "deciding_rule_ids": current_verdict.deciding_rule_ids,
                            "checklist_fingerprint": assessment[
                                "checklist_fingerprint"
                            ],
                            "evidence_fingerprint": assessment[
                                "evidence_fingerprint"
                            ],
                            "active_checklist_fingerprint": assessment[
                                "active_fingerprint"
                            ],
                            "document_report_fingerprint": assessment[
                                "document_report_fingerprint"
                            ],
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
                            return fail("Recheck the documents from this exact draft.")
                if task.operation in {"approve", "reject"}:
                    await resume_application_approval(
                        application_gate,
                        state["conversation_id"],
                        record,
                        {
                            key: arguments[key]
                            for key in ("action", "draft_id", "revision", "fingerprint")
                        },
                    )
                actor: ToolActor = (
                    "human_approval" if task.operation in {"approve", "reject"}
                    else "session_cleanup" if task.operation == "delete_journey"
                    else "application"
                )
                if task.operation == "submit" and record is not None:
                    arguments["approval_token"] = record.get("approval_token")
                result = await application_tool(
                    specialist_client(actor, state["conversation_id"]),
                    "mock_portal",
                    arguments,
                )
                if task.operation in {"create_draft", "edit_draft"}:
                    await pause_for_application_approval(
                        application_gate, state["conversation_id"], result
                    )
                return result
            except MCPToolError:
                tool_failed = True
                raise

        try:
            if task.operation in {"create_draft", "edit_draft", "submit"}:
                record, budget, trace, react_status = await run_application_specialist(
                    model_provider,
                    task.operation,
                    arguments.get("draft_id"),
                    arguments.get("revision"),
                    state.get("locale", "en"),
                    state.get("agent_budget", {}),
                    execute,
                )
                if operation_failure is not None:
                    return operation_failure
                if record is None:
                    if tool_failed:
                        return task_failure(
                            "application", "The mock application service is unavailable.", 502
                        )
                    return task_failure(
                        "application", "The application specialist did not complete its action."
                    )
            else:
                record = await execute()
                budget = state.get("agent_budget", {})
                trace = []
                react_status = state.get("react_status", "deterministic")
                if operation_failure is not None:
                    return operation_failure
        except MCPToolError:
            return task_failure(
                "application", "The mock application service is unavailable.", 502
            )
        result = record
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
            "agent_budget": budget,
            "agent_trace": trace,
            "react_status": react_status,
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

        agent_budget = state.get("agent_budget", {})
        trace_events: list[dict[str, Any]] = []
        react_status = state.get("react_status", "deterministic")
        discovery_updates: dict[str, Any] = {}

        def model_state_updates() -> dict[str, Any]:
            """Persist the shared counters and scrubbed model metadata."""

            return {
                "agent_budget": agent_budget,
                "agent_trace": trace_events,
                "react_status": react_status,
                **discovery_updates,
            }

        # ---- Search path ----
        if state["action"] == "search":
            query = mask_sensitive_text(state.get("query", "").strip())
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
            normalized_query = query
            if not (
                query_rewriter is rewrite_scheme_query
                and model_provider is None
            ):
                (
                    rewritten_query,
                    agent_budget,
                    trace_events,
                    call_status,
                ) = await run_accounted_model_call(
                    agent="intake",
                    action="rewrite_scheme_query",
                    model=(
                        model_provider.model_name
                        if model_provider is not None
                        else DEFAULT_CHAT_MODEL
                    ),
                    input_text=query,
                    budget=agent_budget,
                    callback=lambda: query_rewriter(query),
                    failure_type=IntakeAgentError,
                )
                if isinstance(rewritten_query, str) and rewritten_query.strip():
                    normalized_query = mask_sensitive_text(rewritten_query)
                    react_status = call_status
                else:
                    react_status = "deterministic_fallback"
            return {
                "query": normalized_query,
                "status": "searching",
                "normalized_query": normalized_query,
                "passages": [],
                "eligibility_result": None,
                "agent_budget": agent_budget,
                "agent_trace": trace_events,
                "react_status": react_status,
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
            await bind_rules(state, scheme_id)
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
        if interview:
            return await registered_intake_result(state, packages)

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
        return registered_evaluation_input(scheme_id, dict(profile_data), packages)

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
        if not isinstance(reply, dict):
            raise ValueError("Registered answers must use the validated payload")
        answer = reply.get("answer")
        safe_text = reply.get("safe_text")
        if not isinstance(answer, dict) or not isinstance(safe_text, str):
            raise ValueError("Registered answer payload is invalid")
        return {
            "pending_registered_answer": answer,
            "pending_answer": None,
            "conversation": [
                {"role": "user", "content": safe_text}
            ],
        }

    async def eligibility_agent(state: JourneyState) -> dict[str, Any]:
        """Ask the MCP rule tool for a verdict and store it in the state."""

        scheme_id = state["scheme_id"]
        try:
            await bind_rules(state, scheme_id)
        except MCPToolError:
            return {
                "status": "tool_error",
                "message": discovery_message("tool_error", state.get("locale", "en")),
                "eligibility_result": None,
                "candidate_verdicts": {
                    **state.get("candidate_verdicts", {}),
                    scheme_id: CandidateVerdict(
                        scheme_id=scheme_id, result="tool_error",
                    ).model_dump(mode="json"),
                },
                "handoffs": _report_to_supervisor("eligibility", "tool_error"),
            }
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
        if True:
            try:
                profile = restore_typed_store(
                    state.get("typed_facts")
                )
            except (KeyError, TypeError, ValueError):
                return {
                    "status": "invalid_input",
                    "message": (
                        "Saved answers use a different fact definition. "
                        "Start a new conversation to review them."
                    ),
                    "eligibility_result": None,
                    "handoffs": _report_to_supervisor(
                        "eligibility", "invalid_input"
                    ),
                }
        # The rule engine runs in the MCP server; this node never reads
        # rule files itself (least privilege).
        history: list[dict[str, Any]] = []
        async def checked_verdict() -> EligibilityResponse:
            # Hand-written retry, not RetryPolicy: a failed attempt must leave a visible
            # history note and the final failure must become a calm reply, not an error.
            for attempt in (1, 2):
                try:
                    return await eligibility_tool(
                        specialist_client("eligibility"), scheme_id, profile
                    )
                except MCPToolError:
                    history.append(JourneyHistoryEvent(
                        event_type="tool_retry" if attempt == 1 else "tool_failed",
                        scheme_id=scheme_id, attempt=attempt,
                        reason=("Eligibility tool retry." if attempt == 1
                                else "Eligibility tool failed; no verdict."),
                    ).model_dump(mode="json"))
            raise MCPToolError("Eligibility tool failed twice.")
        provider = eligibility_model_provider
        result, budget, trace, react_status = await run_eligibility_specialist(
            provider, scheme_id, state.get("locale", "en"),
            state.get("agent_budget", {}), checked_verdict,
        )
        agent_updates = {
            "agent_budget": budget, "agent_trace": trace,
            "react_status": react_status if provider is not None
            else state.get("react_status", "deterministic"),
        }
        if result is None:
            verdict = CandidateVerdict(scheme_id=scheme_id, result="tool_error")
            # Say plainly when the stop came from a used-up allowance: retrying
            # later will not help, a new conversation will.
            stopped_by_budget = bool(trace) and trace[-1].get("status") == "budget_exhausted"
            return {
                "status": "tool_error",
                "message": discovery_message(
                    "allowance_used" if stopped_by_budget else "tool_error",
                    state.get("locale", "en"),
                ),
                "eligibility_result": None,
                "candidate_verdicts": {
                    **state.get("candidate_verdicts", {}),
                    scheme_id: verdict.model_dump(mode="json"),
                },
                "journey_history": history,
                "handoffs": _report_to_supervisor("eligibility", "tool_error"),
                **agent_updates,
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
            **agent_updates,
        }

    async def scheme_search_tool(state: JourneyState) -> dict[str, Any]:
        """Find cited scheme passages for the rewritten query."""

        history: list[dict[str, Any]] = []
        passages = None
        search_calls = durable_counters({"search_calls": state.get("search_calls", 0)})["search_calls"]
        # Hand-written retry, not RetryPolicy: a failed attempt must leave a visible
        # history note and the final failure must become a calm reply, not an error.
        for attempt in (1, 2):
            if search_calls >= MAX_DISCOVERY_CALLS:
                break
            search_calls += 1
            await reserve_counters({"search_calls": search_calls})
            try:
                passages = await search_tool(
                    specialist_client("eligibility"), state["query"]
                )
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
            message = discovery_message(
                "budget_exhausted" if search_calls >= MAX_DISCOVERY_CALLS else "tool_error",
                state.get("locale", "en"),
            )
            return {
                "status": "tool_error",
                "message": message,
                        "passages": [],
                "candidate_scheme_ids": [],
                "journey_history": history,
                "conversation": [{"role": "assistant", "content": message}],
                "handoffs": _report_to_supervisor("search", "tool_error"),
                "search_calls": search_calls,
                "discovery_events": [DiscoveryEvent(
                    code="budget_exhausted" if search_calls >= MAX_DISCOVERY_CALLS else "tool_error",
                    search_calls=search_calls,
                ).model_dump(mode="json")],
                "discovery_notices": (
                    ["budget_exhausted"] if search_calls >= MAX_DISCOVERY_CALLS
                    else ["tool_error"]
                ),
            }
        candidate_scheme_ids, excess = merge_candidates(
            [], [passage.scheme_id for passage in passages],
        )
        locale = state.get("locale", "en")
        if passages and locale == "hi":
            message = (
                f"{len(candidate_scheme_ids)} योजना(ओं) में {len(passages)} प्रासंगिक "
                f"स्रोत-सहित अंश मिले। अधिकतम {SEARCH_PASSAGE_LIMIT} अंश दिखाए जाते हैं; "
                "खोज हर उपयोगी योजना नहीं ढूँढ सकती।"
            )
        elif passages and locale == "mr":
            message = (
                f"{len(candidate_scheme_ids)} योजनांमध्ये {len(passages)} संबंधित "
                f"स्रोतासह उतारे सापडले. जास्तीत जास्त {SEARCH_PASSAGE_LIMIT} उतारे "
                "दाखवले जातात; शोधात प्रत्येक उपयुक्त योजना सापडेलच असे नाही."
            )
        elif passages:
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
            message = {
                "hi": "कोई मिलता-जुलता अंश नहीं मिला। दूसरे शब्दों में पूछें।",
                "mr": "जुळणारे उतारे सापडले नाहीत. वेगळ्या शब्दांत विचारा.",
            }.get(locale, "No matching passages were found. Try different wording.")
        return {
            "status": "search_results",
            "message": message,
            "passages": [
                passage.model_dump(mode="json") for passage in passages
            ],
            # Preserve retrieval order while grouping passages by scheme.
            "candidate_scheme_ids": candidate_scheme_ids,
            "unprocessed_candidate_ids": excess,
            "discovery_notices": ["candidate_limit"] if excess else [],
            "search_calls": search_calls,
            "discovery_events": [DiscoveryEvent(
                code="candidate_limit" if excess else "search_completed",
                search_calls=search_calls, candidate_ids=candidate_scheme_ids,
                unprocessed_candidate_ids=excess,
            ).model_dump(mode="json")],
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
    # The Store keeps per-conversation data (the budget) outside the checkpoints.
    compiled = graph.compile(checkpointer=checkpointer, store=store or InMemoryStore())
    compiled.dependency_action = dependency_action
    compiled.verify_dependencies = verify_dependencies
    compiled.journey_locks = {}
    compiled.registered_question_schemes = frozenset(rule_packages)
    compiled.fact_registry = fact_registry
    compiled.validate_registered_store = validate_registered_store
    compiled.registry_dependencies = registry_dependencies
    return compiled


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
        locale=values.get("locale", "en"),
        mode=values.get("mode", "citizen"),
        mode_acknowledgement=MODE_ACKNOWLEDGEMENTS[
            values.get("mode", "citizen")
        ][values.get("locale", "en")],
        react_status=values.get("react_status", "deterministic"),
        agent_budget=values.get("agent_budget", {}),
        agent_trace=[
            AgentTraceEvent.model_validate(event)
            for event in values.get("agent_trace", [])
        ],
        plan_detail=(
            Plan.model_validate(values["plan_detail"])
            if values.get("plan_detail")
            else None
        ),
        status=values["status"],
        message=values.get("message", ""),
        # Only show a question while the graph is actually waiting.
        question=values.get("question") if awaiting else None,
        question_definition=(
            QuestionPresentation.model_validate(values["question_definition"])
            if awaiting and values.get("question_definition")
            else None
        ),
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
            name for name, fact in (values.get("typed_facts") or {}).get("facts", {}).items()
            if fact.get("status") == "known"
        ],
        correctable_fact_names=[
            name for name, fact in (values.get("typed_facts") or {}).get("facts", {}).items()
            if fact.get("status") in {"known", "declined"}
        ],
        fact_questions=values.get("fact_questions", {}),
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
        dependency_version=values.get("dependency_version", 0),
        discovery_notices=values.get("discovery_notices", []),
        discovery_events=values.get("discovery_events", []),
        discovery_messages=[
            discovery_message(code, values.get("locale", "en"))
            for code in values.get("discovery_notices", [])
        ],
        return_code=values.get("return_code"),
        search_calls=values.get("search_calls", 0),
        unprocessed_candidate_ids=values.get("unprocessed_candidate_ids", []),
    )


def _serialize_journey(function: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Prevent same-process checkpoint and budget races for one conversation."""

    @wraps(function)
    async def serialized(graph: Any, *args: Any, **kwargs: Any) -> Any:
        identity = args[0] if args else kwargs.get("request", kwargs.get("conversation_id"))
        conversation_id = (
            identity.conversation_id if isinstance(identity, JourneyRequest) else identity
        )
        lock = graph.journey_locks.setdefault(str(conversation_id), asyncio.Lock())
        async with lock:
            ledger = ConversationBudget(graph.store)
            await ledger.load(str(conversation_id))
            token = CURRENT_BUDGET.set(ledger)
            try:
                return await function(graph, *args, **kwargs)
            finally:
                CURRENT_BUDGET.reset(token)
    return serialized


async def _begin_profile_change(
    graph: Any, config: dict[str, Any], conversation_id: UUID, version: int,
) -> int:
    """Block both persistence boundaries even if either transition fails."""

    try:
        await graph.aupdate_state(
            config, {"dependency_blocked": True, "dependency_version": version + 1},
        )
    finally:
        # If checkpointing fails, the portal must still revoke old approvals.
        new_version = await graph.dependency_action(
            str(conversation_id), "begin_profile_change", version + 1,
        )
    return new_version


def _replace_registered_fact(
    store: HouseholdProfile,
    registry: FactRegistry,
    fact_id: str,
    value: object,
    status: Literal["known", "declined"],
) -> HouseholdProfile:
    """Validate a proposed answer together with all previously confirmed facts."""

    facts = dict(store.facts)
    facts[fact_id] = FactState(
        status=status,
        value=value if status == "known" else None,
        provenance="user_reported" if status == "known" else None,
        definition_version=registry.get(fact_id).version,
    )
    return HouseholdProfile(
        registry_version=store.registry_version, facts=facts
    ).validate_against(registry)


async def _check_registry_dependencies(
    graph: Any,
    conversation_id: UUID,
    values: Mapping[str, Any],
) -> JourneyResponse | None:
    """Persist a monotonic review latch before exposing or reusing stale results."""

    current = graph.registry_dependencies()
    previous = values.get("registry_dependencies")
    incompatible = (
        previous is not None and previous != current
    ) or (
        previous is None and bool(values.get("typed_facts"))
    )
    if not values.get("dependency_review_required") and not incompatible:
        return None
    config = _thread_config(conversation_id)
    version = values.get("dependency_version", 0)
    messages = {
        "en": "Saved answers use a different fact definition or scheme dependency. Human review and reconfirmation in a new conversation are required.",
        "hi": "सहेजे गए उत्तरों की तथ्य परिभाषा या योजना का संस्करण बदल गया है। मानव समीक्षा के बाद नई बातचीत में फिर पुष्टि करें।",
        "mr": "जतन केलेल्या उत्तरांची तथ्य व्याख्या किंवा योजनेची आवृत्ती बदलली आहे. मानवी पुनरावलोकनानंतर नवीन संभाषणात पुन्हा पुष्टी करा.",
    }
    update = {
        "dependency_review_required": True,
        "dependency_blocked": True,
        "dependency_version": version,
        "status": "invalid_input",
        "message": messages[values.get("locale", "en")],
        "eligibility_result": None,
        "eligibility_results": {},
        "candidate_verdicts": {},
        "document_assessments": {},
        "pending_fact": None,
        "question": None,
        "question_definition": None,
        "pending_answer": None,
        "pending_registered_answer": None,
        "discovery_notices": ["correction_invalidated"],
    }
    if not values.get("dependency_review_required"):
        # Latch before external I/O, so a failed revocation cannot let A→B→A
        # reuse old answers or approve a stale form on a later request.
        try:
            await graph.aupdate_state(config, update)
        finally:
            version = await _begin_profile_change(
                graph, config, conversation_id, version
            )
        update["dependency_version"] = version
    await graph.aupdate_state(config, update)
    return _to_response(conversation_id, {**values, **update})


@_serialize_journey
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
    if operation != "delete_journey":
        refused = await _check_registry_dependencies(
            graph, conversation_id, snapshot.values or {}
        )
        if refused is not None:
            raise ApplicationTaskError(409, refused.message)
    if operation != "delete_journey":
        if not await graph.verify_dependencies(
            str(conversation_id), snapshot.values.get("dependency_version", 0),
        ):
            raise ApplicationTaskError(409, "Profile reconciliation is required before writes.")
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


@_serialize_journey
async def run_journey(
    graph: Any,
    request: JourneyRequest,
) -> JourneyResponse:
    """Start a new request in a conversation (search, evaluate or interview).

    Any question still waiting from an earlier request is dropped: new
    input always starts the graph again from START.
    """

    if any(is_prompt_injection(text or "") for text in (
        request.query, request.profile_description,
    )):
        return _guardrail_response(
            request.conversation_id, request.locale, request.mode
        )

    # Start state for this request. Keys from an earlier request in the same
    # conversation are saved in the checkpoint, so every per-request key is
    # reset here; otherwise an old plan, profile or answer could leak in.
    # Only "conversation" and "handoffs" keep growing as history.
    config = _thread_config(request.conversation_id)
    snapshot = await graph.aget_state(config)
    saved_values = snapshot.values or {}
    refused = await _check_registry_dependencies(
        graph, request.conversation_id, saved_values
    )
    if refused is not None:
        return refused
    dependency_version = saved_values.get("dependency_version", 0)
    profile_changed = (
        bool(saved_values.get("profile"))
        and saved_values.get("profile") != request.profile
    )
    if profile_changed:
        dependency_version = await _begin_profile_change(
            graph, config, request.conversation_id, dependency_version,
        )
    prior_budget = durable_counters(saved_values.get("agent_budget", {}))
    # Household memory: pre-fill facts from a return code when this
    # conversation has no facts of its own yet.
    return_code = saved_values.get("return_code") or request.return_code
    typed_facts_seed = saved_values.get("typed_facts")
    if (
        request.return_code
        and not typed_facts_seed
        and request.action == "interview"
    ):
        household = await load_household(
            graph.store, request.return_code, graph.fact_registry,
        )
        if household is not None:
            typed_facts_seed = household.to_wire(graph.fact_registry)
            return_code = normalize_return_code(request.return_code)
    initial_state: JourneyState = {
        "action": request.action,
        "application_task": None,
        "application_task_result": None,
        "application_task_error": None,
        "document_assessments": {},
        "conversation_id": str(request.conversation_id),
        "profile_description": (
            mask_sensitive_text(request.profile_description)
            if request.profile_description is not None
            else None
        ),
        "locale": request.locale,
        "mode": request.mode,
        "citizen_present": request.citizen_present,
        "scheme_id": request.scheme_id or "",
        "multi_scheme": bool(request.candidate_scheme_ids),
        "profile": request.profile,
        "typed_facts": typed_facts_seed,
        "registry_intake": True,
        "registry_dependencies": graph.registry_dependencies(),
        "dependency_review_required": False,
        "fact_questions": saved_values.get("fact_questions", {}),
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
        "passages": (
            saved_values.get("passages", []) if request.action == "interview" else []
        ),
        **NO_PENDING_QUESTION,
        # Interpretation attempts and agent counters belong to the conversation,
        # not to one request; a same-ID restart must not grant fresh calls.
        "llm_attempted_facts": list(
            saved_values.get("llm_attempted_facts", [])
        ),
        "interpreter_context": list(
            saved_values.get("interpreter_context", [])
        )[:MAX_INTERPRETER_CONTEXT],
        "profile_proposals": [],
        "initial_description_processed": False,
        "agent_budget": {
            key: value
            for key, value in prior_budget.items()
            if key in {
                "model_calls", "input_tokens", "output_tokens",
                "tool_calls", "agent_steps",
            }
            and type(value) is int
            and value >= 0
        },
        "react_status": "deterministic",
        "search_calls": durable_counters({
            "search_calls": saved_values.get("search_calls", 0),
        })["search_calls"],
        "discovery_signature": saved_values.get("discovery_signature", ""),
        "discovery_notices": (
            ["candidate_limit"] if saved_values.get("unprocessed_candidate_ids") else []
        ),
        "unprocessed_candidate_ids": saved_values.get("unprocessed_candidate_ids", []),
        "dependency_version": dependency_version,
        "dependency_blocked": profile_changed,
        "return_code": return_code,
        "skipped_facts": list(saved_values.get("skipped_facts", [])),
        "conversation": [],
    }
    if request.query is not None:
        safe_query = mask_sensitive_text(request.query)
        initial_state["query"] = safe_query
        initial_state["conversation"] = [
            {"role": "user", "content": safe_query}
        ]

    result = await graph.ainvoke(
        initial_state,
        config=config,
    )
    if profile_changed:
        await graph.dependency_action(
            str(request.conversation_id), "reconcile_profile", dependency_version,
        )
    return _to_response(request.conversation_id, result)


@_serialize_journey
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
    saved = snapshot.values or {}
    if is_prompt_injection(message):
        if not snapshot.interrupts:
            raise JourneyNotWaitingError(str(conversation_id))
        response = _to_response(conversation_id, saved)
        return response.model_copy(update={
            "status": "awaiting_answer",
            "message": INPUT_GUARDRAIL_MESSAGES[
                saved.get("locale", "en")
            ],
        })
    refused = await _check_registry_dependencies(
        graph, conversation_id, snapshot.values or {}
    )
    if refused is not None:
        return refused
    if not snapshot.interrupts:
        raise JourneyNotWaitingError(str(conversation_id))

    pending_fact = saved.get("pending_fact")
    registry = getattr(graph, "fact_registry", None)
    definition = registry.get(pending_fact)
    parsed = parse_registered_answer(
        definition, message, saved.get("locale", "en")
    )
    confirming = bool(saved.get("pending_confirmation"))
    if not confirming and parsed.kind in {"value", "unknown"}:
        try:
            proposed = _replace_registered_fact(
                HouseholdProfile.from_wire(saved.get("typed_facts"), registry),
                registry, pending_fact, parsed.value,
                "known" if parsed.kind == "value" else "declined",
            )
            graph.validate_registered_store(
                proposed, saved.get("candidate_scheme_ids", [])
            )
        except (KeyError, TypeError, ValueError) as error:
            parsed = ParsedAnswer(
                kind="invalid",
                error=(
                    str(error).replace("_", " ").capitalize() + "."
                    if "application_date" in str(error) and saved.get("locale", "en") == "en"
                    else discovery_message("invalid_input", saved.get("locale", "en"))
                ),
            )
    answer: dict[str, Any] = {"kind": parsed.kind}
    if parsed.kind == "value":
        answer["value"] = encode_wire_value(parsed.value)
    elif parsed.kind == "invalid":
        answer["error"] = parsed.error
        if saved.get("fact_intake_mode") != "deterministic_only":
            answer["reply"] = mask_sensitive_text(message)
    decision = None
    if confirming:
        decision = parse_confirmation(message, saved.get("locale", "en"))
        answer = {"kind": "confirmation", "decision": decision}
    resume_payload: object = {
        "answer": answer,
        # The buttons send the code "skip"; the chat shows what was chosen.
        "safe_text": (
            unknown_answer_label(saved.get("locale", "en"))
            if parsed.kind == "unknown" or decision == "unknown"
            else ""
            if parsed.kind == "invalid"
            and definition.privacy.sensitivity != "ordinary"
            else mask_sensitive_text(message)
        ),
    }

    result = await graph.ainvoke(
        Command(resume=resume_payload),
        config=config,
    )
    return _to_response(conversation_id, result)


@_serialize_journey
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
    refused = await _check_registry_dependencies(
        graph, conversation_id, values or {}
    )
    if refused is not None:
        return refused
    if not values or not (values.get("profile") or values.get("typed_facts")):
        raise JourneyNotWaitingError(str(conversation_id))

    locale = values.get("locale", "en")
    registry = getattr(graph, "fact_registry", None)
    typed_data = values.get("typed_facts")
    store = HouseholdProfile.from_wire(typed_data, registry)
    saved_fact = store.facts.get(correction.fact_name)
    if saved_fact is None or saved_fact.status not in {"known", "declined"}:
        raise ValueError("Only a previously answered fact can be corrected")
    definition = registry.get(correction.fact_name)
    parsed = parse_registered_answer(definition, correction.answer, locale)
    if parsed.kind not in {"value", "unknown"}:
        raise ValueError(
            parsed.error or "A correction must be a clear yes, no, or date"
        )
    proposed = _replace_registered_fact(
        store, registry, correction.fact_name, parsed.value,
        "known" if parsed.kind == "value" else "declined",
    )
    typed_data = graph.validate_registered_store(
        proposed, values.get("candidate_scheme_ids", [])
    ).to_wire(registry)
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
    dependency_version = await _begin_profile_change(
        graph, config, conversation_id, values.get("dependency_version", 0),
    )
    initial_state: JourneyState = {
        "action": "interview",
        "application_task": None,
        "application_task_result": None,
        "application_task_error": None,
        "document_assessments": {},
        "conversation_id": str(conversation_id),
        "scheme_id": values.get("scheme_id", "") if not values.get("multi_scheme") else "",
        "multi_scheme": values.get("multi_scheme", False),
        "candidate_scheme_ids": list(values["candidate_scheme_ids"]),
        "profile": {},
        "typed_facts": typed_data,
        "registry_intake": values.get("registry_intake", False),
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
            (set(values.get("skipped_facts", [])) | {correction.fact_name})
            if parsed.kind == "unknown"
            else (set(values.get("skipped_facts", [])) - {correction.fact_name})
        ),
        "llm_attempted_facts": list(
            values.get("llm_attempted_facts", [])
        ),
        "interpreter_context": list(
            values.get("interpreter_context", [])
        )[:MAX_INTERPRETER_CONTEXT],
        "return_code": values.get("return_code"),
        "agent_budget": durable_counters(values.get("agent_budget", {})),
        "search_calls": durable_counters({
            "search_calls": values.get("search_calls", 0),
        })["search_calls"],
        "discovery_signature": values.get("discovery_signature", ""),
        "discovery_notices": ["correction_invalidated"],
        "dependency_version": dependency_version,
        "dependency_blocked": True,
        "profile_proposals": [],
        "initial_description_processed": True,
        **NO_PENDING_QUESTION,
        "conversation": [{
            "role": "assistant",
            "content": discovery_message("corrected", locale),
        }],
        "journey_history": [event.model_dump(mode="json")],
    }
    result = await graph.ainvoke(initial_state, config=config)
    await graph.dependency_action(
        str(conversation_id), "reconcile_profile", dependency_version,
    )
    return _to_response(conversation_id, result)


@_serialize_journey
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
    refused = await _check_registry_dependencies(
        graph, conversation_id, snapshot.values
    )
    if refused is not None:
        return refused
    return _to_response(conversation_id, snapshot.values)
