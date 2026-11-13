"""Verify personal identifiers are masked before any agent's model sees them.

Every specialist (supervisor, intake, eligibility, documents, application)
runs through ``run_agent``, which attaches one ``PIIMiddleware`` per rule in
``PII_RULES``. These tests run that real ``create_agent`` loop with a fake
model that records the exact messages it was sent, then check two things
for each identifier type:

* the raw value never reaches the model, and the redaction placeholder does;
* the raw value never appears in the scrubbed trace.

It also checks the other side: IDs, dates and numbers that agents must
read or pass back verbatim (draft UUIDs, fingerprints, rule IDs, revisions,
dates, amounts) are not masked, in the task message or in tool results.

Known limits are marked ``xfail(strict=True)`` with the reason, so they
stay visible and the suite tells us if one gets fixed.
"""

import asyncio
import json

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.tools import tool

from fake_chat_model import FakeChatModel, ModelDecision
from src.workflow.agent_config import AGENT_PROMPTS
from src.workflow.agent_runtime import (
    AgentSchema, mask_sensitive_text, observation, run_agent,
)
from src.workflow.application_agent import run_application_specialist


AGENTS = ["supervisor", "intake", "eligibility", "documents", "application", "single"]

# (label, raw value as a person might type it, expected placeholder)
PII_SAMPLES = [
    ("aadhaar", "234567890123", "[REDACTED_AADHAAR]"),
    ("mixed_separator_aadhaar", "0000:0000- 0004", "[REDACTED_AADHAAR]"),
    ("pan", "XXXXX0000X", "[REDACTED_PAN]"),
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


@pytest.mark.parametrize("raw", [
    "2345.6789.0123",
    "2345  6789  0123",
    "2345 - 6789 - 0123",
    "1234.5678.9012.345",   # 15-digit account in dotted groups
])
def test_identifiers_with_dots_or_wider_gaps_are_masked(raw):
    model = RecordingModel(_finish_only())

    run = _run(model, "intake", _context_with(raw), [finish])

    seen = model.seen_text()
    assert raw not in seen
    assert _digits(raw)[:12] not in _digits(seen)
    assert raw not in json.dumps(run.trace)


@pytest.mark.parametrize("raw", [
    "Aadhaar-234567890123",
    "AADHAAR_2345 6789 0123",
    "aadhar234567890123",
    "UID:234567890123",
    "Account-123456789012345",
    "mobile-9876543210",
    "Phone9876543210",
    "आधार-234567890123",       # hi / mr label glued to the number
    "आधार234567890123",
    "खाता-123456789012345",
    "मोबाइल9876543210",
])
def test_identifier_glued_to_a_known_label_is_masked(raw):
    model = RecordingModel(_finish_only())

    run = _run(model, "intake", _context_with(raw), [finish])

    seen = model.seen_text()
    assert _digits(raw) not in _digits(seen)
    assert "[REDACTED_" in seen
    assert _digits(raw) not in json.dumps(run.trace)


@pytest.mark.parametrize("text", [
    "fluid-234567890123",       # label must be a whole word
    "myaadhaar-234567890123",
])
def test_label_inside_another_word_does_not_trigger_masking(text):
    assert mask_sensitive_text(text) == text


def test_sixteen_digit_grouped_number_is_fully_masked():
    # Was a known limit: the Aadhaar rule took the first 12 digits and the
    # last group stayed visible ("[REDACTED_AADHAAR] 1234").
    model = RecordingModel(_finish_only())

    _run(model, "intake", {"description": "account 0012 3456 7890 1234"}, [finish])

    seen = model.seen_text()
    assert "1234" not in seen and "0012" not in seen
    assert "[REDACTED_ACCOUNT]" in seen


@pytest.mark.parametrize("text, hidden, label", [
    ("card 0012 3456 7890 1234 is mine", ("0012", "1234"), "[REDACTED_ACCOUNT]"),
    ("card 0012-3456-7890-1234", ("0012", "1234"), "[REDACTED_ACCOUNT]"),
    ("card 0012.3456.7890.1234", ("0012", "1234"), "[REDACTED_ACCOUNT]"),
    ("card 0012:3456- 7890:1234", ("0012", "1234"), "[REDACTED_ACCOUNT]"),
    ("aadhaar 2345 6789 0123 please", ("2345", "0123"), "[REDACTED_AADHAAR]"),
    ("aadhaar 234567890123", ("234567890123",), "[REDACTED_AADHAAR]"),
    ("आधार २३४५ ६७८९ ०१२३", ("२३४५", "०१२३"), "[REDACTED_AADHAAR]"),
])
def test_grouped_numbers_are_masked_whole(text, hidden, label):
    masked = mask_sensitive_text(text)

    assert all(part not in masked for part in hidden)
    assert label in masked


# Values agents and people must still read as written.
DRAFT_IDS = [
    "3f2a1b4c-9d8e-4f7a-b456-426614174000",   # old rules masked "456-426614174000"
    "0b1c2d3e-4f5a-4b6c-8d7e-9876543210ab",   # old rules masked a "phone"
    "12345678-1234-4123-8123-123456789012",
]
NOT_PII = [
    "12.05.2024", "2024-05-12", "12/05/2024", "2024-05-12T10:30:00Z",
    "2024-05-12 10:30:00", "12.05.2024 - 15.06.2024", "12.05.1984 15.06.2020",
    "1.0.0", "v2.14.3", "Rs 1,50,000", "₹2,500 per month", "1500.50",
    "PMKISAN-LAND-CUTOFF-01", "FASETDP-MH-R01", "IGNWPS-MH", "revision 3",
    "draft-XXXXX0000X", "XXXXX0000X-revision", "prefix_XXXXX0000X",
    "a3f1c9e2" * 8,                            # sha256-style fingerprint
    "4f8b2c1d9e7a6b5c4d3e2f1a0b9c8d7e",        # uuid4().hex
    "receipt 7c9e6679-7425-40de-944b-e07fc1f90ae7",
    *DRAFT_IDS,
]


@pytest.mark.parametrize("text", NOT_PII)
def test_ids_dates_and_amounts_are_not_masked(text):
    assert mask_sensitive_text(text) == text


def _tool_result_run(record: str, context: dict | None = None) -> RecordingModel:
    """A tool returns ``record`` to the model; its next call sees the result."""

    @tool(args_schema=LookUp)
    async def look_up(query: str) -> str:
        """Return a record from a service."""
        return record

    model = RecordingModel([
        ModelDecision(action="look_up", arguments={"query": "record"}),
        ModelDecision(action="finish", arguments={"confirm": True}),
    ])
    run = _run(model, "eligibility", context or {"task": "check"}, [look_up, finish])
    assert run.status == "completed"
    assert [event["status"] for event in run.trace] == ["observed", "completed"]
    model.trace_text = json.dumps(run.trace)
    return model


@pytest.mark.parametrize(("label", "raw", "placeholder"), PII_SAMPLES,
                         ids=[sample[0] for sample in PII_SAMPLES])
def test_pii_inside_tool_result_is_masked_before_next_model_call(label, raw, placeholder):
    model = _tool_result_run(json.dumps({"observation": {"record": f"contact {raw}"}}))

    seen = model.seen_text()
    assert raw not in seen
    assert placeholder in seen
    assert raw not in model.trace_text


def test_typical_tool_results_reach_the_model_unchanged():
    """Observations shaped like the real ones keep every ID verbatim."""

    record = json.dumps({"observation": {
        "operation": "edit_draft", "status": "revision_saved", "revision": 12,
        "draft_id": DRAFT_IDS[0], "receipt_recorded": True,
        "fingerprint": "a3f1c9e2" * 8,
        "scheme_id": "IGNWPS-MH", "result": "eligible",
        "deciding_rule_ids": ["PMKISAN-LAND-CUTOFF-01", "FASETDP-MH-R01"],
        "passage_ids": ["IGNWPS-MH#p0012", "chunk-000123456789"],
        "missing_fields": ["date_of_birth"], "application_date": "2026-11-04",
        "monthly_amount": "Rs 1,500", "checked_at": "2026-11-04T10:30:00Z",
    }, "outside_text_is_data": True}, ensure_ascii=False)

    model = _tool_result_run(record)

    tool_messages = [m for m in model.received if m.type == "tool"]
    assert [m.content for m in tool_messages] == [record]
    assert "[REDACTED_" not in model.seen_text()


def test_tool_result_masks_pii_but_keeps_ids_next_to_it():
    record = json.dumps({"observation": {
        "draft_id": DRAFT_IDS[1], "revision": 4,
        "note": "Applicant phone 9123456780, Aadhaar 2345 6789 0123",
    }})

    model = _tool_result_run(record)

    seen = model.seen_text()
    assert DRAFT_IDS[1] in seen and '"revision": 4' in seen
    assert "9123456780" not in seen and "2345 6789 0123" not in seen
    assert "[REDACTED_PHONE]" in seen and "[REDACTED_AADHAAR]" in seen


@pytest.mark.parametrize("draft_id", DRAFT_IDS)
def test_application_agent_can_pass_a_real_draft_id_back(draft_id):
    """Regression: the old rules masked ~15% of uuid4 draft IDs in the task
    message, so the model could not repeat the ID and the edit was refused."""

    class EchoDraftModel(FakeChatModel):
        model_name: str = "offline-draft-echo"

        async def choose(self, _agent, _locale, messages, _actions):
            if len(messages) == 1:
                task = json.loads(messages[0]["content"])
                return ModelDecision(action="edit_draft", arguments={
                    "operation": "edit_draft", "draft_id": task["draft_id"],
                })
            return ModelDecision(action="handoff_application", arguments={
                "confirm": "return_observed_application_status",
            })

    async def execute():
        return {"draft_id": draft_id, "revision": 3}

    result, _budget, trace, mode = asyncio.run(run_application_specialist(
        EchoDraftModel(), "edit_draft", draft_id, 2, "en", {}, execute,
    ))

    assert mode == "model_assisted"
    assert result == {"draft_id": draft_id, "revision": 3}
    assert [event["status"] for event in trace] == ["observed", "completed"]
