"""Run bounded model-selected actions behind typed permissions and budgets."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import json
import re
import time
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from src.config import openrouter_chat_settings
from src.llm_client import DEFAULT_CHAT_MODEL, ChatRequestError, OpenRouterChatClient
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


class AgentModelError(RuntimeError):
    """A model response was unavailable or did not match its tool schema."""


class AgentActionError(RuntimeError):
    """A selected action could not safely complete."""


class ModelDecision(AgentSchema):
    """One tool choice returned by a provider, including optional usage data."""

    action: str
    arguments: dict[str, object]
    input_tokens: int = 0
    output_tokens: int = 0


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


class ToolChoiceProvider(Protocol):
    """Provider interface used by production and deterministic fake models."""

    model_name: str

    async def choose(
        self,
        agent: str,
        locale: str,
        messages: list[dict[str, str]],
        actions: list[AgentAction],
    ) -> ModelDecision:
        """Return one schema-constrained action choice."""


class OpenRouterToolChoiceProvider:
    """OpenRouter chat-completions adapter for model-selected function tools."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
    ) -> None:
        configured_key, configured_model = openrouter_chat_settings(
            DEFAULT_CHAT_MODEL
        )
        self.api_key = api_key if api_key is not None else configured_key
        self.model_name = model_name or configured_model
        # One reusable connection for the provider's lifetime (the API creates
        # one provider at startup and closes it at shutdown).
        self._chat = OpenRouterChatClient(self.api_key) if self.api_key else None

    @property
    def configured(self) -> bool:
        """Whether production has an API credential for model-assisted actions."""

        return bool(self.api_key)

    async def aclose(self) -> None:
        """Close the reusable model connection."""

        if self._chat is not None:
            await self._chat.aclose()

    async def choose(
        self,
        agent: str,
        locale: str,
        messages: list[dict[str, str]],
        actions: list[AgentAction],
    ) -> ModelDecision:
        """Ask the configured model to select exactly one allowed tool."""

        if self._chat is None:
            raise AgentModelError("The configured model is unavailable.")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": action.name,
                    "description": action.description,
                    "parameters": action.arguments_model.model_json_schema(),
                    "strict": True,
                },
            }
            for action in actions
        ]
        try:
            reply = await self._chat.complete({
                "model": self.model_name,
                "temperature": 0,
                "max_tokens": MAX_COMPLETION_TOKENS,
                "messages": [
                    {
                        "role": "system",
                        "content": prompt_for(agent, locale),  # type: ignore[arg-type]
                    },
                    *messages,
                ],
                "tools": tools,
                "tool_choice": "required",
                "parallel_tool_calls": False,
            })
        except ChatRequestError as error:
            raise AgentModelError("The configured model is unavailable.") from error

        try:
            function = reply.choices[0].message.tool_calls[0].function
            arguments = json.loads(function.arguments)
            if not isinstance(function.name, str) or not isinstance(arguments, dict):
                raise TypeError("Invalid tool choice.")
            usage = reply.usage
            return ModelDecision(
                action=function.name,
                arguments=arguments,
                input_tokens=_nonnegative_int(getattr(usage, "prompt_tokens", None)),
                output_tokens=_nonnegative_int(getattr(usage, "completion_tokens", None)),
            )
        except (AttributeError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise AgentModelError("The model returned an invalid tool choice.") from error


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
    provider: ToolChoiceProvider,
    budget: Mapping[str, int] | None = None,
    *,
    max_steps: int = MAX_AGENT_STEPS_PER_TURN,
) -> AgentRunResult:
    """Let a model choose bounded actions, validate each, and return a typed stop.

    Args:
        agent: Prompt identity, such as ``intake`` or ``supervisor``.
        actor: Trusted code-owned action identity; never read from model data.
        locale: Supported prompt language.
        context: Minimal task data. Sensitive identifiers are masked first.
        actions: Typed actions available to this agent.
        provider: Production model adapter or an offline fake.
        budget: Conversation-level counters loaded from the checkpoint.
        max_steps: A per-turn limit independent of the conversation ceiling.
    """

    counters = _read_budget(budget)
    action_map = {action.name: action for action in actions}
    safe_context = mask_sensitive_text(
        json.dumps(dict(context), ensure_ascii=False, default=str)
    )
    messages = [{"role": "user", "content": safe_context}]
    trace: list[dict[str, object]] = []
    results: list[dict[str, object]] = []

    for step in range(1, max_steps + 1):
        if not _can_call_model(counters, messages, actions, agent, locale):
            trace.append(_trace(
                agent, None, "budget_exhausted", provider.model_name, step,
                "Conversation model or token limit reached before a model call.",
            ))
            return AgentRunResult("budget_exhausted", results, counters, trace)

        estimated_input = _estimate_tokens(messages, actions, agent, locale)
        counters["model_calls"] += 1
        counters["agent_steps"] += 1
        counters["input_tokens"] += estimated_input
        # Reserve the configured maximum completion before sending a paid call.
        counters["output_tokens"] += MAX_COMPLETION_TOKENS
        await reserve_counters(counters)
        started = time.monotonic()
        try:
            decision = await provider.choose(agent, locale, messages, actions)
        except AgentModelError:
            trace.append(_trace(
                agent, None, "model_unavailable", provider.model_name, step,
                "Model request did not complete; no action was executed.",
                estimated_input, 0, _elapsed_ms(started),
            ))
            return AgentRunResult("model_unavailable", results, counters, trace)

        actual_input = decision.input_tokens or estimated_input
        actual_output = decision.output_tokens or _estimate_tokens(
            [{"role": "assistant", "content": json.dumps({
                "action": decision.action,
                "arguments": decision.arguments,
            })}],
            [],
        )
        # Keep the larger of measured and estimated input, and release unused
        # completion reservation only after the provider returns successfully.
        counters["input_tokens"] += max(0, actual_input - estimated_input)
        counters["output_tokens"] -= MAX_COMPLETION_TOKENS
        counters["output_tokens"] += actual_output
        await reserve_counters(counters)

        action = action_map.get(decision.action)
        if (
            action is None
            or decision.action not in AGENT_ACTION_ALLOWLIST.get(agent, frozenset())
        ):
            trace.append(_trace(
                agent, decision.action, "denied", provider.model_name, step,
                "Model-selected action is outside this agent's allow-list.",
                actual_input, actual_output, _elapsed_ms(started),
            ))
            return AgentRunResult("action_denied", results, counters, trace)
        if action.actor != actor:
            trace.append(_trace(
                agent, action.name, "denied", provider.model_name, step,
                "Trusted actor does not match the selected action.",
                actual_input, actual_output, _elapsed_ms(started),
            ))
            return AgentRunResult("action_denied", results, counters, trace)
        if counters["tool_calls"] >= MAX_CONVERSATION_TOOL_CALLS:
            trace.append(_trace(
                agent, action.name, "budget_exhausted", provider.model_name, step,
                "Conversation action limit reached before tool execution.",
                actual_input, actual_output, _elapsed_ms(started),
            ))
            return AgentRunResult("budget_exhausted", results, counters, trace)
        try:
            arguments = action.arguments_model.model_validate(decision.arguments)
        except ValidationError:
            trace.append(_trace(
                agent, action.name, "invalid_arguments", provider.model_name, step,
                "Action arguments did not match the declared input schema.",
                actual_input, actual_output, _elapsed_ms(started),
            ))
            return AgentRunResult("invalid_arguments", results, counters, trace)

        counters["tool_calls"] += 1
        await reserve_counters(counters)
        try:
            raw_output = await action.executor(arguments)
            output = action.output_model.model_validate(raw_output)
        except (AgentActionError, ValidationError):
            trace.append(_trace(
                agent, action.name, "action_rejected", provider.model_name, step,
                "The action failed its permission or output-schema check.",
                actual_input, actual_output, _elapsed_ms(started),
            ))
            return AgentRunResult("action_rejected", results, counters, trace)

        serialized_output = output.model_dump(mode="json")
        results.append(serialized_output)
        trace.append(_trace(
            agent, action.name,
            "completed" if action.terminal else "observed",
            provider.model_name, step,
            "Typed action completed; its observation was passed to the next choice.",
            actual_input, actual_output, _elapsed_ms(started),
        ))
        messages.append({
            "role": "assistant",
            "content": json.dumps({
                "tool": action.name,
                "arguments": arguments.model_dump(mode="json"),
            }, ensure_ascii=False),
        })
        messages.append({
            "role": "user",
            "content": json.dumps({
                "observation": serialized_output,
                "outside_text_is_data": True,
            }, ensure_ascii=False),
        })
        if action.terminal:
            return AgentRunResult("completed", results, counters, trace)

    trace.append(_trace(
        agent, None, "step_limit", provider.model_name, max_steps,
        "Per-turn action limit reached; no further action was executed.",
    ))
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


def _estimate_tokens(
    messages: list[dict[str, str]],
    actions: list[AgentAction],
    agent: str | None = None,
    locale: str = "en",
) -> int:
    """Conservatively estimate token use from request text and schemas."""

    request_text = json.dumps(
        {
            "system": prompt_for(agent, locale) if agent else "",
            "messages": messages,
            "actions": [
                action.arguments_model.model_json_schema()
                for action in actions
            ],
        },
        ensure_ascii=False,
    )
    return max(1, len(request_text) // TOKEN_ESTIMATE_CHARACTERS)


def _can_call_model(
    budget: Mapping[str, int],
    messages: list[dict[str, str]],
    actions: list[AgentAction],
    agent: str,
    locale: str,
) -> bool:
    """Reserve input and maximum output before a model request begins."""

    return (
        budget["model_calls"] < MAX_CONVERSATION_MODEL_CALLS
        and budget["agent_steps"] < MAX_CONVERSATION_AGENT_STEPS
        and budget["input_tokens"]
        + budget["output_tokens"]
        + _estimate_tokens(messages, actions, agent, locale)
        + MAX_COMPLETION_TOKENS
        <= MAX_CONVERSATION_TOKENS
    )


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


def _nonnegative_int(value: object) -> int:
    """Read an integer model-usage field without accepting booleans."""

    if type(value) is int and value >= 0:
        return value
    return 0
