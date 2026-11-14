"""Run each specialist as a LangChain ``create_agent`` with Saathi's middleware."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import json
import re
import time
from typing import TypeVar

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware, PIIMiddleware, RedactionRule
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
#
# Digits may be grouped by up to three spaces, dots, colons or hyphens
# ("2345.6789.0123", "2345 - 6789 - 0123"). A number glued to a letter,
# underscore or hyphen is part of an ID (draft UUIDs, hex fingerprints,
# rule IDs), and a number starting with a date (12.05.2024, 2024-05-12) is
# a date, so neither is masked: agents must pass IDs back verbatim.
# Exception: a number glued to a known label ("Aadhaar-234567890123",
# "आधार234567890123") is masked. Labels are whole words with letters that
# never appear in hex IDs, so draft UUIDs and fingerprints stay intact.
_PII_LABELS = (
    "aadhaar", "aadhar", "uid", "account", "acct", "mobile", "phone",
    "आधार", "खाता", "मोबाइल", "फोन", "फ़ोन",
)
_AFTER_LABEL = "|".join(
    rf"(?<=(?<![\w-])(?i:{re.escape(label)}){sep})"
    for label in _PII_LABELS
    for sep in ("", "-", "_", ":")
)
_NOT_INSIDE_ID = rf"(?:(?<![\w-])|{_AFTER_LABEL})"
_NOT_A_DATE = (
    r"(?!(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})(?!\d))"
    r"(?!(?<=\d[./-])(?:\d{1,2}[./-])?\d{1,4}(?!\d))"   # nor the rest of one
)
_DIGIT_GAP = r"[\s.:\-]{0,3}"
_ID_END = r"(?![\w-])"
# Exactly 12 digits make an Aadhaar. A longer grouped number (a 16-digit
# card or account, "0012 3456 7890 1234") is left to the account rule so
# no group of it stays visible.
_NOT_PART_OF_LONGER_NUMBER = (
    rf"(?<!\d)(?<!\d[\s.:\-])(?<!\d[\s.:\-]{{2}})(?<!\d[\s.:\-]{{3}})"
)
PII_RULES = (
    RedactionRule("email"),
    RedactionRule("pan", detector=(
        _NOT_INSIDE_ID + r"[A-Za-z]{5}[0-9]{4}[A-Za-z]" + _ID_END
    )),
    RedactionRule("aadhaar", detector=(
        _NOT_PART_OF_LONGER_NUMBER + _NOT_INSIDE_ID + _NOT_A_DATE
        + rf"(?:\d{_DIGIT_GAP}){{11}}\d" + _ID_END + rf"(?!{_DIGIT_GAP}\d)"
    )),
    RedactionRule("phone", detector=(
        _NOT_INSIDE_ID + r"(?:\+?91[ -]?)?[6-9]\d{9}" + _ID_END
    )),
    RedactionRule("account", detector=(
        _NOT_INSIDE_ID + _NOT_A_DATE + rf"(?:\d{_DIGIT_GAP}){{8,17}}\d" + _ID_END
    )),
)
_RESOLVED_PII_RULES = tuple(rule.resolve() for rule in PII_RULES)


class IdentifierHitCounter(AgentMiddleware):
    """Count identifier hits in agent messages without changing them.

    Runs before PIIMiddleware, so it sees the original text. Each message is
    counted once (by message id) even though the agent loop revisits it on
    later model calls. Redaction still happens in PIIMiddleware.
    """

    def __init__(self) -> None:
        super().__init__()
        self._counted: set[object] = set()

    def before_model(self, state, runtime):  # noqa: ANN001 - LangChain hook signature
        from src.observability.metrics import record_masked_id_hits

        for message in state.get("messages", []):
            key = getattr(message, "id", None) or id(message)
            if key in self._counted:
                continue
            self._counted.add(key)
            content = message.content
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
            for rule in _RESOLVED_PII_RULES:
                _, matches = rule.apply(text)
                if matches:
                    record_masked_id_hits(len(matches), field_type=str(rule.pii_type))
        return None


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
        context: Minimal task data. PIIMiddleware masks identifiers in it,
            and in every tool result, before the model sees them.
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
            # Count identifier hits first, on the original text (counting only).
            IdentifierHitCounter(),
            *(
                # Mask the task message and every tool result before the model.
                PIIMiddleware(
                    rule.pii_type, detector=rule.detector, strategy="redact",
                    apply_to_tool_results=True,
                )
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

    from src.observability.metrics import record_masked_id_hits

    for rule in _RESOLVED_PII_RULES:
        text, matches = rule.apply(text)
        if matches:
            record_masked_id_hits(len(matches), field_type=str(rule.pii_type))
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
