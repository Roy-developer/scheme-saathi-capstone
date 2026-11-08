"""Run each specialist as a LangChain ``create_agent`` with Saathi's middleware."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import json
import time
from typing import TypeVar

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, PIIMiddleware, RedactionRule
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from src.llm_client import DEFAULT_CHAT_MODEL
from src.workflow.agent_middleware import (
    model_call_fits,
    reserve_model_call,
    AgentActionError,
    AgentModelError,
    DurableBudgetMiddleware,
    RunStopped,
    ScrubbedTraceMiddleware,
    observation,
    trace_event,
)
from src.workflow.conversation_budget import durable_counters, reserve_counters
from src.workflow.agent_config import (
    MAX_AGENT_STEPS_PER_TURN,
    MAX_COMPLETION_TOKENS,
    MAX_CONVERSATION_TOOL_CALLS,
    AUXILIARY_PROMPT_TOKEN_RESERVE,
    PROMPT_VERSION,
    TOKEN_ESTIMATE_CHARACTERS,
    prompt_for,
)


_CallResult = TypeVar("_CallResult")
# Personal identifiers, masked in this order (an Aadhaar number must be
# caught before the shorter phone and account patterns see part of it).
# The same rules feed PIIMiddleware for agents and mask_sensitive_text for
# everything else (traces, intake text, search queries).
PII_RULES = (
    RedactionRule("email"),
    RedactionRule("aadhaar", detector=r"(?<!\d)(?:\d[ -]?){11}\d(?!\d)"),
    RedactionRule("phone", detector=r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)"),
    RedactionRule("account", detector=r"(?<!\d)(?:\d[ -]?){8,17}\d(?!\d)"),
)
_RESOLVED_PII_RULES = tuple(rule.resolve() for rule in PII_RULES)


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


@dataclass
class AgentRunResult:
    """Outcome, updated counters and trace from one agent run."""

    status: str
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
    """Run one non-agent chat call under the same durable conversation limits.

    Intake's one-off calls (reading a free-text answer, rewriting a search
    query) do not run inside ``create_agent``, so agent middleware cannot wrap
    them. They use the same ``model_call_fits`` / ``reserve_model_call`` rules
    as ``DurableBudgetMiddleware``: the call and its maximum reply are saved
    before the request is sent.
    """

    counters = _read_budget(budget)
    estimated_input = (
        max(1, len(input_text) // TOKEN_ESTIMATE_CHARACTERS)
        + AUXILIARY_PROMPT_TOKEN_RESERVE
    )
    step = counters["agent_steps"] + 1
    if not model_call_fits(counters, estimated_input):
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

    await reserve_model_call(counters, estimated_input)
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


async def run_agent(
    model: BaseChatModel,
    agent: str,
    locale: str,
    context: Mapping[str, object],
    tools: list[BaseTool],
    budget: Mapping[str, int] | None = None,
    *,
    max_steps: int = MAX_AGENT_STEPS_PER_TURN,
) -> AgentRunResult:
    """Run one specialist as a LangChain agent with Saathi's middleware.

    Args:
        model: The chat model (ChatOpenAI in production, a fake in tests).
        agent: Prompt identity, such as ``intake`` or ``supervisor``.
        locale: Supported prompt language.
        context: Minimal task data. PIIMiddleware masks identifiers before
            the model sees it.
        tools: The only actions this agent may take (its allow-list).
        budget: Conversation counters from the graph state; ``_read_budget``
            merges in reservations saved in the LangGraph Store.
        max_steps: Model calls allowed in this run.
    """

    counters = _read_budget(budget)
    trace: list[dict[str, object]] = []
    system_prompt = prompt_for(agent, locale)  # type: ignore[arg-type]
    graph = create_agent(
        model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[
            *(
                PIIMiddleware(rule.pii_type, detector=rule.detector, strategy="redact")
                for rule in PII_RULES
            ),
            ModelCallLimitMiddleware(run_limit=max_steps, exit_behavior="end"),
            ScrubbedTraceMiddleware(agent, model.model_name, trace),
            DurableBudgetMiddleware(counters, estimate_extra=system_prompt + json.dumps(
                [tool.args_schema.model_json_schema() for tool in tools]
            )),
        ],
    )
    message = json.dumps(dict(context), ensure_ascii=False, default=str)
    try:
        await graph.ainvoke({"messages": [HumanMessage(content=message)]})
    except RunStopped as stop:
        return AgentRunResult(stop.status, counters, trace)
    if any(event["status"] == "completed" for event in trace):
        return AgentRunResult("completed", counters, trace)
    trace.append(trace_event(agent, None, "step_limit", model.model_name, max_steps))
    return AgentRunResult("step_limit", counters, trace)


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

    for rule in _RESOLVED_PII_RULES:
        text, _matches = rule.apply(text)
    return text


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
