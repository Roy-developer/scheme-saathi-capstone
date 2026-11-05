"""Run bounded model-selected actions behind typed permissions and budgets."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import json
import re
import time
from typing import TypeVar

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict

from src.llm_client import DEFAULT_CHAT_MODEL
from src.workflow.agent_middleware import (
    AgentActionError,
    AgentModelError,
    DurableBudgetMiddleware,
    RunStopped,
    ScrubbedTraceMiddleware,
    as_tool,
    trace_event,
)
from src.workflow.conversation_budget import durable_counters, reserve_counters
from src.workflow.agent_config import (
    MAX_AGENT_STEPS_PER_TURN,
    MAX_COMPLETION_TOKENS,
    MAX_CONVERSATION_AGENT_STEPS,
    MAX_CONVERSATION_MODEL_CALLS,
    MAX_CONVERSATION_TOKENS,
    MAX_CONVERSATION_TOOL_CALLS,
    AUXILIARY_PROMPT_TOKEN_RESERVE,
    PROMPT_VERSION,
    TOKEN_ESTIMATE_CHARACTERS,
    prompt_for,
)


_CallResult = TypeVar("_CallResult")
AGENT_ACTION_ALLOWLIST: dict[str, frozenset[str]] = {
    "eligibility": frozenset({
        "check_candidate", "handoff_verdict", "request_clarification", "refer_for_help",
    }),
    "supervisor": frozenset({"propose_plan", "finish_plan"}),
    "intake": frozenset({
        "read_required_facts",
        "propose_profile_facts",
        "finish_intake",
    }),
    "documents": frozenset({
        "inspect_document_metadata", "handoff_documents",
    }),
    "application": frozenset({
        "prepare_draft", "edit_draft", "submit_draft",
        "read_application_status", "handoff_application",
    }),
}
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_AADHAAR_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){11}\d(?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)")
_LONG_NUMBER_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){8,17}\d(?!\d)")


class AgentSchema(BaseModel):
    """Strict JSON schema base used at model action boundaries."""

    model_config = ConfigDict(extra="forbid")


class AgentTraceEvent(AgentSchema):
    """Scrubbed metadata about one model decision or action boundary."""

    agent: str
    action: str | None = None
    status: str
    model: str
    prompt_version: str
    step: int
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    summary: str


class AgentAction:
    """A named, validated operation an agent may request."""

    def __init__(
        self,
        name: str,
        description: str,
        actor: str,
        arguments_model: type[AgentSchema],
        output_model: type[AgentSchema],
        executor: Callable[[AgentSchema], Awaitable[AgentSchema]],
        *,
        terminal: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.actor = actor
        self.arguments_model = arguments_model
        self.output_model = output_model
        self.executor = executor
        self.terminal = terminal


@dataclass
class AgentRunResult:
    """Outcome and updated durable counters from one bounded ReAct turn."""

    status: str
    action_results: list[dict[str, object]]
    budget: dict[str, int]
    trace: list[dict[str, object]]


async def run_accounted_model_call(
    *,
    agent: str,
    action: str,
    model: str,
    input_text: str,
    budget: Mapping[str, int] | None,
    callback: Callable[[], Awaitable[_CallResult]],
    failure_type: type[Exception],
) -> tuple[
    _CallResult | None,
    dict[str, int],
    list[dict[str, object]],
    str,
]:
    """Run one non-ReAct chat call under the same durable conversation limits.

    The helper reserves a conservative input allowance and the maximum
    completion before invoking the callback. Counters therefore remain safe
    even when the legacy adapter does not report provider usage.
    """

    counters = _read_budget(budget)
    estimated_input = (
        max(1, len(input_text) // TOKEN_ESTIMATE_CHARACTERS)
        + AUXILIARY_PROMPT_TOKEN_RESERVE
    )
    step = counters["agent_steps"] + 1
    if (
        counters["model_calls"] >= MAX_CONVERSATION_MODEL_CALLS
        or counters["agent_steps"] >= MAX_CONVERSATION_AGENT_STEPS
        or (
            counters["input_tokens"]
            + counters["output_tokens"]
            + estimated_input
            + MAX_COMPLETION_TOKENS
            > MAX_CONVERSATION_TOKENS
        )
    ):
        return (
            None,
            counters,
            [_trace(
                agent, action, "budget_exhausted", model, step,
                "Conversation model or token limit reached before a model call.",
                estimated_input,
            )],
            "budget_exhausted",
        )

    counters["model_calls"] += 1
    counters["agent_steps"] += 1
    counters["input_tokens"] += estimated_input
    counters["output_tokens"] += MAX_COMPLETION_TOKENS
    await reserve_counters(counters)
    started = time.monotonic()
    try:
        result = await callback()
    except failure_type:
        return (
            None,
            counters,
            [_trace(
                agent, action, "model_unavailable", model, step,
                "Model request did not complete; deterministic handling continues.",
                estimated_input, 0, _elapsed_ms(started),
            )],
            "model_unavailable",
        )
    return (
        result,
        counters,
        [_trace(
            agent, action, "completed", model, step,
            "Bounded helper call completed; maximum output tokens reserved.",
            estimated_input, MAX_COMPLETION_TOKENS, _elapsed_ms(started),
        )],
        "model_assisted",
    )


async def run_react_loop(
    agent: str,
    actor: str,
    locale: str,
    context: Mapping[str, object],
    actions: list[AgentAction],
    provider: BaseChatModel,
    budget: Mapping[str, int] | None = None,
    *,
    max_steps: int = MAX_AGENT_STEPS_PER_TURN,
) -> AgentRunResult:
    """Run one agent with LangChain ``create_agent`` and Saathi's middleware.

    Args:
        agent: Prompt identity, such as ``intake`` or ``supervisor``.
        actor: Trusted code-owned action identity; never read from model data.
        locale: Supported prompt language.
        context: Minimal task data. Sensitive identifiers are masked first.
        actions: Typed actions available to this agent.
        provider: The chat model (ChatOpenAI in production, a fake in tests).
        budget: Conversation-level counters loaded from the checkpoint.
        max_steps: A per-turn limit independent of the conversation ceiling.
    """

    counters = _read_budget(budget)
    trace: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    # Only allow-listed actions owned by this agent are offered as tools.
    allowed = [
        action for action in actions
        if action.actor == actor
        and action.name in AGENT_ACTION_ALLOWLIST.get(agent, frozenset())
    ]
    tools = [
        as_tool(
            action.name, action.description, action.arguments_model,
            action.output_model, action.executor,
            terminal=action.terminal, results=results,
        )
        for action in allowed
    ]
    system_prompt = prompt_for(agent, locale)  # type: ignore[arg-type]
    graph = create_agent(
        provider,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[
            ModelCallLimitMiddleware(run_limit=max_steps, exit_behavior="end"),
            ScrubbedTraceMiddleware(agent, provider.model_name, trace),
            DurableBudgetMiddleware(counters, estimate_extra=system_prompt + json.dumps(
                [action.arguments_model.model_json_schema() for action in allowed]
            )),
        ],
    )
    context = mask_sensitive_text(json.dumps(dict(context), ensure_ascii=False, default=str))
    try:
        await graph.ainvoke({"messages": [HumanMessage(content=context)]})
    except RunStopped as stop:
        return AgentRunResult(stop.status, results, counters, trace)
    if any(event["status"] == "completed" for event in trace):
        return AgentRunResult("completed", results, counters, trace)
    trace.append(trace_event(agent, None, "step_limit", provider.model_name, max_steps))
    return AgentRunResult("step_limit", results, counters, trace)


async def recover_authorized_action(
    run: AgentRunResult,
    execute: Callable[[], Awaitable[dict[str, object]]],
) -> dict[str, object] | None:
    """Run the code-selected task once if only model availability blocks it."""

    if (
        run.status not in {"budget_exhausted", "model_unavailable"}
        or run.budget.get("tool_calls", 0) >= MAX_CONVERSATION_TOOL_CALLS
    ):
        return None
    run.budget["tool_calls"] = run.budget.get("tool_calls", 0) + 1
    await reserve_counters(run.budget)
    return await execute()


def mask_sensitive_text(text: str) -> str:
    """Mask common identifiers before free text reaches a model or trace."""

    masked = _EMAIL_PATTERN.sub("[masked-email]", text)
    masked = _AADHAAR_PATTERN.sub("[masked-id]", masked)
    masked = _PHONE_PATTERN.sub("[masked-phone]", masked)
    return _LONG_NUMBER_PATTERN.sub("[masked-account]", masked)


def copy_agent_budget(budget: Mapping[str, int] | None) -> dict[str, int]:
    """Copy known counters into a JSON-safe checkpoint value."""

    keys = (
        "model_calls", "input_tokens", "output_tokens", "tool_calls",
        "agent_steps",
    )
    return {
        key: max(0, value) if type(value := (budget or {}).get(key, 0)) is int else 0
        for key in keys
    }


def _read_budget(budget: Mapping[str, int] | None) -> dict[str, int]:
    """Load known nonnegative counters and ignore malformed checkpoint values."""

    names = (
        "model_calls", "input_tokens", "output_tokens", "tool_calls",
        "agent_steps",
    )
    reserved = durable_counters(dict(budget or {}))
    return {
        name: max(0, value) if type(value := reserved.get(name, 0)) is int else 0
        for name in names
    }


def _trace(
    agent: str,
    action: str | None,
    status: str,
    model: str,
    step: int,
    summary: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
) -> dict[str, object]:
    """Build a bounded metadata-only event with no prompts or applicant facts."""

    return AgentTraceEvent(
        agent=agent,
        action=action,
        status=status,
        model=model,
        prompt_version=PROMPT_VERSION,
        step=step,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        summary=summary,
    ).model_dump(mode="json")


def _elapsed_ms(started: float) -> int:
    """Return a nonnegative elapsed duration in milliseconds."""

    return max(0, int((time.monotonic() - started) * 1000))
