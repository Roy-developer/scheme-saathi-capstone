"""Verify personal identifiers are masked before any agent's model sees them.

Every specialist (supervisor, intake, eligibility, documents, application)
runs through ``run_agent``, which attaches one ``PIIMiddleware`` per rule in
``PII_RULES``. These tests run that real ``create_agent`` loop with a fake
model that records the exact messages it was sent, then check two things
for each identifier type:

* the raw value never reaches the model, and the redaction placeholder does;
* the raw value never appears in the scrubbed trace.

Cases that are known to get through are marked ``xfail(strict=True)`` with
the reason, so they stay visible and the suite tells us if one gets fixed.
"""

import asyncio
import json

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.tools import tool

from fake_chat_model import FakeChatModel, ModelDecision
from src.workflow.agent_config import AGENT_PROMPTS
from src.workflow.agent_runtime import AgentSchema, observation, run_agent


AGENTS = ["supervisor", "intake", "eligibility", "documents", "application"]

# (label, raw value as a person might type it, expected placeholder)
PII_SAMPLES = [
    ("aadhaar", "234567890123", "[REDACTED_AADHAAR]"),
    ("phone", "9876543210", "[REDACTED_PHONE]"),
    ("email", "asha.devi@example.invalid", "[REDACTED_EMAIL]"),
    ("bank_account", "123456789012345", "[REDACTED_ACCOUNT]"),
]


class Finish(AgentSchema):
    confirm: bool


class LookUp(AgentSchema):
    query: str


class Done(AgentSchema):
    finished: bool = True


@tool(args_schema=Finish, return_direct=True)
async def finish(confirm: bool) -> str:
    """End the run."""
    return observation(Done())


class RecordingModel(FakeChatModel):
    """Record every message the model receives, then follow a fixed script."""

    model_name: str = "offline-pii-recorder"

    def __init__(self, script: list[ModelDecision]) -> None:
        super().__init__()
        self.script = list(script)
        self.received: list[BaseMessage] = []

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.extend(messages)
        return await super()._agenerate(messages, stop, run_manager, **kwargs)

    async def choose(self, _agent, _locale, _messages, _tools):
        if not self.script:
            raise AssertionError("Unexpected extra model call")
        return self.script.pop(0)

    def seen_text(self) -> str:
        return "\n".join(
            message.content if isinstance(message.content, str)
            else json.dumps(message.content, ensure_ascii=False)
            for message in self.received
        )


def _run(model: RecordingModel, agent: str, context: dict, tools: list, locale="en"):
    return asyncio.run(run_agent(model, agent, locale, context, tools, max_steps=3))


def _context_with(raw: str) -> dict[str, object]:
    # Free text and a nested field, as an applicant description might arrive.
    return {
        "description": f"I am a widow. My number is {raw}, please help.",
        "profile": {"contact": raw},
    }


def _finish_only() -> list[ModelDecision]:
    return [ModelDecision(action="finish", arguments={"confirm": True})]


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def test_every_prompted_agent_is_covered():
    """If a new agent gains a prompt, it must be added to this file too."""

    assert set(AGENT_PROMPTS) == set(AGENTS)


@pytest.mark.parametrize("agent", AGENTS)
@pytest.mark.parametrize(("label", "raw", "placeholder"), PII_SAMPLES,
                         ids=[sample[0] for sample in PII_SAMPLES])
def test_pii_is_masked_before_model_and_absent_from_trace(agent, label, raw, placeholder):
    model = RecordingModel(_finish_only())

    run = _run(model, agent, _context_with(raw), [finish])

    assert run.status == "completed"
    seen = model.seen_text()
    assert model.received, "the model was never called"
    assert raw not in seen
    assert seen.count(placeholder) == 2      # free text and nested field
    trace_text = json.dumps(run.trace)
    assert raw not in trace_text
    assert placeholder not in trace_text     # the trace holds no content at all


@pytest.mark.parametrize("agent", AGENTS)
def test_all_pii_types_in_one_message_are_masked_together(agent):
    """Rules run in order; one rule must not leave fragments for another."""

    values = {label: raw for label, raw, _ in PII_SAMPLES}
    model = RecordingModel(_finish_only())

    run = _run(model, agent, {"description": " / ".join(values.values())}, [finish])

    seen = model.seen_text()
    for label, raw, placeholder in PII_SAMPLES:
        assert raw not in seen, label
        assert placeholder in seen, label
        assert raw not in json.dumps(run.trace), label


@pytest.mark.parametrize("raw", [
    "2345 6789 0123",       # printed on the card
    "2345-6789-0123",
    "+91 98765 43210",      # phone with country code and a space
    "२३४५ ६७८९ ०१२३",        # Devanagari digits (hi / mr users)
])
def test_spaced_hyphenated_and_devanagari_identifiers_are_masked(raw):
    model = RecordingModel(_finish_only())

    run = _run(model, "intake", _context_with(raw), [finish], locale="mr")

    seen = model.seen_text()
    assert raw not in seen
    assert _digits(raw) not in seen
    assert "[REDACTED_" in seen
    assert raw not in json.dumps(run.trace)


@pytest.mark.xfail(strict=True, reason=(
    "FINDING: PII_RULES allow only a single space or hyphen between digits, "
    "so an Aadhaar written with dots or double spaces reaches the model unmasked."
))
@pytest.mark.parametrize("raw", ["2345.6789.0123", "2345  6789  0123"])
def test_aadhaar_with_dots_or_double_spaces_is_masked(raw):
    model = RecordingModel(_finish_only())

    _run(model, "intake", _context_with(raw), [finish])

    assert raw not in model.seen_text()


def _tool_result_run(raw: str) -> RecordingModel:
    """A tool returns PII to the model; the model's next call sees the result."""

    @tool(args_schema=LookUp)
    async def look_up(query: str) -> str:
        """Return a record that happens to contain an identifier."""
        return json.dumps({"observation": {"record": f"contact {raw}"}})

    model = RecordingModel([
        ModelDecision(action="look_up", arguments={"query": "record"}),
        ModelDecision(action="finish", arguments={"confirm": True}),
    ])
    run = _run(model, "eligibility", {"task": "check"}, [look_up, finish])
    assert run.status == "completed"
    assert raw not in json.dumps(run.trace)   # the trace is clean either way
    return model


@pytest.mark.xfail(strict=True, reason=(
    "FINDING: run_agent builds PIIMiddleware with the default "
    "apply_to_tool_results=False, so PII inside a tool result is passed "
    "to the model unmasked. Today's tools return typed, value-free "
    "observations, so nothing leaks in practice; a future tool could."
))
@pytest.mark.parametrize(("label", "raw", "placeholder"), PII_SAMPLES,
                         ids=[sample[0] for sample in PII_SAMPLES])
def test_pii_inside_tool_result_is_masked_before_next_model_call(label, raw, placeholder):
    model = _tool_result_run(raw)

    assert raw not in model.seen_text()
