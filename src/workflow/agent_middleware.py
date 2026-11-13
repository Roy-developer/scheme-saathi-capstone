"""Saathi's LangChain middleware for ``create_agent``.

Every agent runs as::

    create_agent(model, tools, system_prompt=..., middleware=[
        PIIMiddleware(...),             # LangChain: mask identifiers (one per rule)
        ModelCallLimitMiddleware(run_limit=max_steps, exit_behavior="end"),
        ScrubbedTraceMiddleware(...),   # Saathi: privacy-safe activity log
        DurableBudgetMiddleware(...),   # Saathi: shared conversation budget
    ])

Earlier middleware wraps later middleware, so the trace sees every budget
stop and records it. Agents define their actions with ``@tool`` and
return ``observation(Model(...))``.
"""

import json
import time
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from openai import OpenAIError
from pydantic import BaseModel, ValidationError

from src.workflow.agent_config import (
    MAX_COMPLETION_TOKENS,
    MAX_CONVERSATION_AGENT_STEPS,
    MAX_CONVERSATION_MODEL_CALLS,
    MAX_CONVERSATION_TOKENS,
    MAX_CONVERSATION_TOOL_CALLS,
    PROMPT_VERSION,
    TOKEN_ESTIMATE_CHARACTERS,
)
from src.observability.metrics import model_span
from src.workflow.conversation_budget import durable_counters, reserve_counters


class AgentModelError(RuntimeError):
    """The model could not be reached or did not answer usably."""


class AgentActionError(RuntimeError):
    """A selected action failed its own checks and must not complete."""


class RunStopped(Exception):
    """Stop an agent run early; ``status`` says why."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


# Fixed, data-free sentences for the trace (never prompts or applicant data).
TRACE_SUMMARIES = {
    "budget_exhausted": "Conversation model, token or action limit reached before the call.",
    "model_unavailable": "Model request did not complete; no action was executed.",
    "denied": "Model-selected action is outside this agent's allow-list.",
    "invalid_arguments": "Action arguments did not match the declared input schema.",
    "action_rejected": "The action failed its permission or output-schema check.",
    "observed": "Typed action completed; its observation was passed to the next choice.",
    "completed": "Typed action completed; its observation was passed to the next choice.",
    "step_limit": "Per-turn action limit reached; no further action was executed.",
}


def trace_event(
    agent: str, action: str | None, status: str, model: str, step: int,
    input_tokens: int = 0, output_tokens: int = 0, duration_ms: int = 0,
) -> dict[str, object]:
    """One metadata-only trace event (see ``AgentTraceEvent`` in agent_runtime)."""

    return {
        "agent": agent, "action": action, "status": status, "model": model,
        "prompt_version": PROMPT_VERSION, "step": step,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "duration_ms": duration_ms, "summary": TRACE_SUMMARIES[status],
    }


def observation(result: BaseModel) -> str:
    """Return a tool's result to the model as JSON data, never as instructions."""

    return json.dumps(
        {"observation": result.model_dump(mode="json"), "outside_text_is_data": True},
        ensure_ascii=False,
    )


class ScrubbedTraceMiddleware(AgentMiddleware):
    """Record one privacy-safe event per model stop and per tool call.

    Events carry the agent, action name, status, model, step, token counts
    and a fixed summary. They never contain prompts, tool arguments or
    applicant data, so they can be saved and shown to the person.
    """

    def __init__(self, agent: str, model_name: str, trace: list[dict[str, object]]) -> None:
        super().__init__()
        self.agent = agent
        self.model_name = model_name
        self.trace = trace
        self.step = 0
        self._usage = (0, 0, time.monotonic())

    def _record(self, action: str | None, status: str) -> None:
        input_tokens, output_tokens, started = self._usage
        self.trace.append(trace_event(
            self.agent, action, status, self.model_name, max(self.step, 1),
            input_tokens, output_tokens, max(0, int((time.monotonic() - started) * 1000)),
        ))

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        self.step += 1
        started = time.monotonic()
        try:
            with model_span(self.agent, self.model_name, self.step):
                response = await handler(request)
        except RunStopped as stop:
            self._usage = (0, 0, started)
            self._record(None, stop.status)
            raise
        usage = response.result[-1].usage_metadata or {}
        input_tokens = usage.get("input_tokens", 0) or 0
        output_tokens = usage.get("output_tokens", 0) or 0
        self._usage = (input_tokens, output_tokens, started)
        try:
            from src.observability.metrics import record_llm_call, record_tokens

            record_tokens(
                self.model_name,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
            )
            record_llm_call(self.model_name, time.monotonic() - started)
        except Exception:  # noqa: BLE001 — metrics must not break the agent
            pass
        return response

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        name = request.tool_call["name"]
        try:
            result = await handler(request)
        except RunStopped as stop:
            self._record(name, stop.status)
            raise
        except (AgentActionError, ValidationError) as error:
            # The tool's own checks refused the call: stop, nothing is returned.
            self._record(name, "action_rejected")
            raise RunStopped("action_rejected") from error
        if request.tool is None:
            self._record(name, "denied")            # unknown tool: the model may retry
        elif isinstance(result, ToolMessage) and result.status == "error":
            self._record(name, "invalid_arguments")  # bad arguments: the model may retry
        else:
            self._record(name, "completed" if request.tool.return_direct else "observed")
        return result


def model_call_fits(counters: dict[str, int], estimated_input: int) -> bool:
    """Whether one more model call (with its maximum reply) fits the budget."""

    return not (
        counters["model_calls"] >= MAX_CONVERSATION_MODEL_CALLS
        or counters["agent_steps"] >= MAX_CONVERSATION_AGENT_STEPS
        or counters["input_tokens"] + counters["output_tokens"]
        + estimated_input + MAX_COMPLETION_TOKENS > MAX_CONVERSATION_TOKENS
    )


async def reserve_model_call(counters: dict[str, int], estimated_input: int) -> None:
    """Count one model call and its maximum reply, saved before it is sent."""

    counters["model_calls"] += 1
    counters["agent_steps"] += 1
    counters["input_tokens"] += estimated_input
    counters["output_tokens"] += MAX_COMPLETION_TOKENS
    await reserve_counters(counters)


class DurableBudgetMiddleware(AgentMiddleware):
    """Enforce the conversation budget shared by every agent.

    Counters (model calls, agent steps, tokens, tool calls) are saved with
    ``reserve_counters`` *before* each paid model call and each tool call,
    so a crash can never leave a call uncounted, and they persist across
    requests in the LangGraph ``Store`` (see ``conversation_budget``).
    """

    def __init__(self, counters: dict[str, int], estimate_extra: str) -> None:
        super().__init__()
        self.counters = counters
        # System prompt and tool schemas, counted in every input estimate.
        self.estimate_extra = estimate_extra

    def _estimate_input(self, messages: list[BaseMessage]) -> int:
        text = json.dumps([
            {"content": message.content, "tool_calls": getattr(message, "tool_calls", [])}
            for message in messages if not isinstance(message, SystemMessage)
        ], ensure_ascii=False, default=str)
        return max(1, (len(text) + len(self.estimate_extra)) // TOKEN_ESTIMATE_CHARACTERS)

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        counters = self.counters
        counters.update(durable_counters(counters))
        estimated_input = self._estimate_input(request.messages)
        if not model_call_fits(counters, estimated_input):
            raise RunStopped("budget_exhausted")
        await reserve_model_call(counters, estimated_input)

        # One tool per step, strict argument schemas.
        request = request.override(
            tool_choice="required",
            model_settings={"parallel_tool_calls": False, "strict": True},
        )
        try:
            response = await handler(request)
        except (AgentModelError, OpenAIError) as error:
            raise RunStopped("model_unavailable") from error

        reply = response.result[-1]
        usage = reply.usage_metadata or {}
        actual_input = usage.get("input_tokens") or estimated_input
        actual_output = usage.get("output_tokens") or max(
            1, len(json.dumps(reply.tool_calls, default=str)) // TOKEN_ESTIMATE_CHARACTERS
        )
        # Keep the larger input figure; release the unused reply reservation.
        counters["input_tokens"] += max(0, actual_input - estimated_input)
        counters["output_tokens"] += actual_output - MAX_COMPLETION_TOKENS
        await reserve_counters(counters)
        reply.usage_metadata = {
            "input_tokens": actual_input, "output_tokens": actual_output,
            "total_tokens": actual_input + actual_output,
        }
        return response

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        self.counters.update(durable_counters(self.counters))
        tool = request.tool
        if tool is None:
            return await handler(request)            # unknown tool: nothing runs, nothing counted
        try:
            tool.args_schema.model_validate(request.tool_call["args"])
        except ValidationError:
            return await handler(request)            # bad arguments: nothing runs, nothing counted
        if self.counters["tool_calls"] >= MAX_CONVERSATION_TOOL_CALLS:
            raise RunStopped("budget_exhausted")
        self.counters["tool_calls"] += 1
        await reserve_counters(self.counters)
        return await handler(request)
