"""The registry path's own intake abilities, on the real IGNOAPS rule data.

These are the abilities that first existed only on the legacy path: reading
free-text replies, reading a description, and not asking for the application
date. Models are faked; a proposal only counts after the person confirms it.
"""

import asyncio
from datetime import date

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.mcp_servers.tools.eligibility import evaluate_registered_profile
from src.rules.data_provider import RulePackageProvider
from src.workflow import journey as journey_module
from src.workflow.intake import AnswerInterpretation
from src.workflow.journey import (
    JourneyRequest,
    build_journey_graph,
    resume_journey,
    run_journey,
)

SCHEME = "IGNOAPS-MH"
PACKAGE_DOB = "1950-03-03"


@pytest.fixture(scope="module")
def provider() -> RulePackageProvider:
    return RulePackageProvider()


def _graph(provider: RulePackageProvider, interpreter=None):
    registry = provider.registry

    async def evaluate(_client, scheme_id, store):
        return evaluate_registered_profile(
            scheme_id, store, provider.packages, provider.bundles, registry,
        )

    extra = {"answer_interpreter": interpreter} if interpreter else {}
    return build_journey_graph(
        object(),
        provider.packages,
        eligibility_tool=evaluate,
        checkpointer=MemorySaver(),
        fact_registry=registry,
        rule_bundles=provider.bundles,
        today=lambda: date(2026, 11, 8),
        **extra,
    )


def _interpreter(answer: AnswerInterpretation):
    seen: list[tuple[str, str, str]] = []

    async def interpret(fact: str, question: str, reply: str) -> AnswerInterpretation:
        seen.append((fact, question, reply))
        return answer

    interpret.seen = seen
    return interpret


def _start(graph, description: str | None = None):
    return asyncio.run(run_journey(graph, JourneyRequest(
        action="interview", scheme_id=SCHEME, profile_description=description,
    )))


def _reply(graph, journey, text: str):
    return asyncio.run(resume_journey(graph, journey.conversation_id, text))


def _to_bpl_question(graph):
    started = _start(graph)
    assert started.pending_fact == "date_of_birth"
    waiting = _reply(graph, started, PACKAGE_DOB)
    assert waiting.pending_fact == "name_on_bpl_list"
    return waiting


def test_a_proposal_that_fails_the_cross_fact_check_is_not_offered(provider) -> None:
    """A birth date after the application date cannot be confirmed."""

    interpreter = _interpreter(AnswerInterpretation(kind="value", value="2030-01-01", confidence=0.95))
    graph = _graph(provider, interpreter)

    again = _reply(graph, _start(graph), "the first of january twenty thirty")

    assert again.pending_fact == "date_of_birth"
    assert again.question_definition.confirming is False


def test_application_date_defaults_to_today_and_is_never_asked(provider) -> None:
    graph = _graph(provider)

    waiting = _to_bpl_question(graph)
    finished = _reply(graph, waiting, "yes")

    assert finished.status == "eligible"


def test_free_text_reply_is_understood_then_confirmed(provider) -> None:
    interpreter = _interpreter(AnswerInterpretation(kind="value", value=True, confidence=0.95))
    graph = _graph(provider, interpreter)
    waiting = _to_bpl_question(graph)

    confirming = _reply(graph, waiting, "my name was added to that list last year")

    assert confirming.status == "awaiting_answer"
    assert confirming.pending_fact == "name_on_bpl_list"
    assert 'I understood your answer as "yes"' in confirming.question
    assert confirming.question_definition.confirming is True
    assert confirming.question_definition.value_type == "boolean"
    assert interpreter.seen[0][2] == "my name was added to that list last year"

    assert _reply(graph, confirming, "yes").status == "eligible"


def test_nothing_is_saved_until_the_person_confirms(provider) -> None:
    interpreter = _interpreter(AnswerInterpretation(kind="value", value=True, confidence=0.95))
    graph = _graph(provider, interpreter)
    waiting = _to_bpl_question(graph)

    confirming = _reply(graph, waiting, "my name was added last year")
    declined = _reply(graph, confirming, "no")

    assert declined.status == "awaiting_answer"
    assert declined.pending_fact == "name_on_bpl_list"
    assert declined.question.startswith("Okay. Please answer directly:")
    assert declined.question_definition.confirming is False
    assert _reply(graph, declined, "no").status == "not_eligible"


def test_date_written_in_words_is_understood_for_a_date_fact(provider) -> None:
    interpreter = _interpreter(AnswerInterpretation(kind="value", value="1950-03-03", confidence=0.9))
    graph = _graph(provider, interpreter)
    started = _start(graph)

    confirming = _reply(graph, started, "third of march nineteen fifty")

    assert confirming.pending_fact == "date_of_birth"
    assert '"1950-03-03"' in confirming.question
    assert _reply(graph, confirming, "yes").pending_fact == "name_on_bpl_list"


def test_model_gets_one_attempt_per_fact(provider) -> None:
    interpreter = _interpreter(AnswerInterpretation(kind="uncertain", confidence=0.2))
    graph = _graph(provider, interpreter)
    waiting = _to_bpl_question(graph)

    again = _reply(graph, waiting, "hmm, it is complicated")
    still = _reply(graph, again, "still complicated")

    assert again.pending_fact == still.pending_fact == "name_on_bpl_list"
    assert again.question_definition.confirming is False
    assert len(interpreter.seen) == 1


def test_low_confidence_value_is_not_proposed(provider) -> None:
    interpreter = _interpreter(AnswerInterpretation(kind="value", value=True, confidence=0.5))
    graph = _graph(provider, interpreter)

    again = _reply(graph, _to_bpl_question(graph), "probably on it")

    assert again.question_definition.confirming is False


def test_model_saying_the_person_does_not_know_keeps_it_unknown(provider) -> None:
    interpreter = _interpreter(AnswerInterpretation(kind="unknown", confidence=0.95))
    graph = _graph(provider, interpreter)

    finished = _reply(graph, _to_bpl_question(graph), "no idea about any list honestly")

    assert finished.status == "need_more_information"


def test_identifier_in_a_free_text_reply_is_masked_before_the_model(provider) -> None:
    interpreter = _interpreter(AnswerInterpretation(kind="uncertain", confidence=0.1))
    graph = _graph(provider, interpreter)

    _reply(graph, _to_bpl_question(graph), "my aadhaar is 1234 5678 9012 check it")

    assert "1234 5678 9012" not in interpreter.seen[0][2]


def test_unclear_confirmation_asks_again(provider) -> None:
    interpreter = _interpreter(AnswerInterpretation(kind="value", value=True, confidence=0.95))
    graph = _graph(provider, interpreter)
    confirming = _reply(graph, _to_bpl_question(graph), "it was added")

    again = _reply(graph, confirming, "what do you mean")

    assert again.question_definition.confirming is True
    assert _reply(graph, again, "yes").status == "eligible"


def test_without_a_model_an_unreadable_reply_only_gets_a_hint(provider) -> None:
    graph = _graph(provider)

    again = _reply(graph, _to_bpl_question(graph), "it is complicated")

    assert again.pending_fact == "name_on_bpl_list"
    assert again.question_definition.confirming is False


def _fake_description(monkeypatch, proposals: list[dict[str, object]]) -> list[str]:
    seen: list[str] = []

    async def propose(_provider, _client, _actor, _scheme, description, _store, _registry,
                      _facts, _locale, budget, discovery_facts=()):
        seen.append(description)
        return list(proposals), dict(budget or {}), [], "model_assisted"

    monkeypatch.setattr(journey_module, "propose_initial_registered_facts", propose)
    return seen


def test_description_proposes_facts_that_are_confirmed_one_by_one(provider, monkeypatch) -> None:
    seen = _fake_description(monkeypatch, [
        {"fact_name": "date_of_birth", "value": PACKAGE_DOB},
        {"fact_name": "name_on_bpl_list", "value": True},
    ])
    graph = _graph(provider)

    first = _start(graph, "I was born in 1950 and my name is on the BPL list.")
    assert seen == ["I was born in 1950 and my name is on the BPL list."]
    assert first.pending_fact == "date_of_birth"
    assert first.question_definition.confirming is True

    second = _reply(graph, first, "yes")
    assert second.pending_fact == "name_on_bpl_list"
    assert second.question_definition.confirming is True

    assert _reply(graph, second, "yes").status == "eligible"


def test_declined_description_fact_is_asked_directly_later(provider, monkeypatch) -> None:
    _fake_description(monkeypatch, [
        {"fact_name": "date_of_birth", "value": PACKAGE_DOB},
        {"fact_name": "name_on_bpl_list", "value": True},
    ])
    graph = _graph(provider)

    first = _start(graph, "Some description.")
    second = _reply(graph, first, "no")
    assert second.pending_fact == "name_on_bpl_list"

    asked = _reply(graph, second, "no")
    assert asked.pending_fact == "name_on_bpl_list"
    assert asked.question_definition.confirming is False


def test_typed_and_widget_answers_still_work_together(provider) -> None:
    graph = _graph(provider)
    started = _start(graph)

    # A date typed in words the code understands needs no model at all.
    waiting = _reply(graph, started, "3 March 1950")

    assert waiting.pending_fact == "name_on_bpl_list"
