"""Verify APY's mock eligibility package and sensitive intake boundaries."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.api.eligibility import EligibilityResponse
from src.mcp_servers.tools.eligibility import evaluate_registered_profile
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactState, HouseholdProfile
from src.workflow import journey as journey_module
from src.workflow.intake import AnswerInterpretation
from src.workflow.journey import (
    JourneyRequest,
    build_journey_graph,
    resume_journey,
    run_journey,
)
from src.workflow.question_picker import pick_shared_registered_fact
from eval.schema import profile_from_mapping


SCHEME = "APY-IN"
AS_OF = date(2026, 11, 11)


@pytest.fixture(scope="module")
def provider() -> RulePackageProvider:
    return RulePackageProvider()


def _known(provider: RulePackageProvider, fact_id: str, value: object) -> FactState:
    return FactState(
        status="known",
        value=value,
        definition_version=provider.registry.get(fact_id).version,
        provenance="user_reported",
    )


def _profile(
    provider: RulePackageProvider,
    *,
    birth: date,
    citizen: bool = True,
    savings_account: bool = True,
    tax_payer: bool = False,
    unknown_fact: str | None = None,
    as_of: date = AS_OF,
) -> HouseholdProfile:
    values = {
        "application_date": _known(provider, "application_date", as_of),
        "date_of_birth": _known(provider, "date_of_birth", birth),
        "apy_is_citizen_of_india": _known(
            provider, "apy_is_citizen_of_india", citizen,
        ),
        "apy_has_savings_bank_account": _known(
            provider, "apy_has_savings_bank_account", savings_account,
        ),
        "apy_is_or_has_been_income_tax_payer": _known(
            provider, "apy_is_or_has_been_income_tax_payer", tax_payer,
        ),
    }
    if unknown_fact is not None:
        definition = provider.registry.get(unknown_fact)
        values[unknown_fact] = FactState(
            status="unknown",
            definition_version=definition.version,
        )
    return HouseholdProfile(
        registry_version=provider.registry.registry_version,
        facts=values,
    )


def _evaluate(
    provider: RulePackageProvider,
    profile: HouseholdProfile,
) -> EligibilityResponse:
    return evaluate_registered_profile(
        SCHEME, profile, provider.packages, provider.bundles, provider.registry,
    )


@pytest.mark.parametrize(
    ("birth", "expected"),
    [
        (date(2009, 11, 12), "not_eligible"),
        (date(2008, 11, 11), "eligible"),
        (date(1986, 11, 11), "eligible"),
        (date(1985, 11, 10), "not_eligible"),
    ],
)
def test_apy_inclusive_age_boundaries(
    provider: RulePackageProvider,
    birth: date,
    expected: str,
) -> None:
    result = _evaluate(provider, _profile(provider, birth=birth))

    assert result.result == expected


def test_rt_inflate_001_age_claim_does_not_replace_date_of_birth(
    provider: RulePackageProvider,
) -> None:
    profile = profile_from_mapping(
        {
            "application_date": AS_OF,
            "date_of_birth": date(1986, 11, 11),
            "apy_is_citizen_of_india": True,
            "apy_has_savings_bank_account": True,
            "apy_is_or_has_been_income_tax_payer": False,
            "age": 39,
        },
        provider.registry,
    )

    assert "age" not in profile.facts
    assert profile.facts["date_of_birth"].value == date(1986, 11, 11)
    assert _evaluate(provider, profile).result == "eligible"


@pytest.mark.parametrize(
    ("fact_id", "value"),
    [
        ("apy_is_citizen_of_india", False),
        ("apy_has_savings_bank_account", False),
        ("apy_is_or_has_been_income_tax_payer", True),
    ],
)
def test_apy_nonqualifying_facts_are_not_eligible(
    provider: RulePackageProvider,
    fact_id: str,
    value: bool,
) -> None:
    answers = {
        "apy_is_citizen_of_india": True,
        "apy_has_savings_bank_account": True,
        "apy_is_or_has_been_income_tax_payer": False,
    }
    answers[fact_id] = value
    result = _evaluate(
        provider,
        _profile(
            provider,
            birth=date(1986, 11, 11),
            citizen=answers["apy_is_citizen_of_india"],
            savings_account=answers["apy_has_savings_bank_account"],
            tax_payer=answers["apy_is_or_has_been_income_tax_payer"],
        ),
    )

    assert result.result == "not_eligible"


def test_apy_unknown_sensitive_answer_needs_more_information(
    provider: RulePackageProvider,
) -> None:
    result = _evaluate(
        provider,
        _profile(
            provider,
            birth=date(1986, 11, 11),
            unknown_fact="apy_is_or_has_been_income_tax_payer",
        ),
    )

    assert result.result == "need_more_information"
    assert "apy_is_or_has_been_income_tax_payer" in result.missing_fields


@pytest.mark.parametrize("tax_payer", [False, True])
def test_apy_pre_effective_date_refuses_a_verdict(
    provider: RulePackageProvider, tax_payer: bool,
) -> None:
    result = _evaluate(provider, _profile(
        provider, birth=date(1990, 1, 1), tax_payer=tax_payer,
        as_of=date(2022, 9, 30),
    ))

    assert result.result == "need_more_information"
    assert "before 1 October 2022" in result.reason
    assert result.deciding_rule_ids == [] and result.evidence == []


@pytest.mark.parametrize("tax_payer", [False, True])
def test_apy_missing_application_date_requires_date_before_any_verdict(
    provider: RulePackageProvider, tax_payer: bool,
) -> None:
    profile = _profile(
        provider, birth=date(1990, 1, 1), tax_payer=tax_payer,
        unknown_fact="application_date",
    )
    result = _evaluate(provider, profile)

    assert result.result == "need_more_information"
    assert result.missing_fields == ["application_date"]
    assert result.deciding_rule_ids == [] and result.evidence == []
    assert pick_shared_registered_fact(
        profile, [provider.packages[SCHEME]], provider.registry,
    ) == "application_date"


@pytest.mark.parametrize(("tax_payer", "expected"), [
    (False, "eligible"), (True, "not_eligible"),
])
def test_apy_effective_date_uses_existing_rules(
    provider: RulePackageProvider, tax_payer: bool, expected: str,
) -> None:
    result = _evaluate(provider, _profile(
        provider, birth=date(1990, 1, 1), tax_payer=tax_payer,
        as_of=date(2022, 10, 1),
    ))

    assert result.result == expected


def test_apy_old_date_stops_intake_without_asking_unnecessary_questions(
    provider: RulePackageProvider,
) -> None:
    profile = HouseholdProfile.from_answers(
        {"application_date": date(2022, 9, 30)}, provider.registry,
    )
    assert pick_shared_registered_fact(
        profile, [provider.packages[SCHEME]], provider.registry,
    ) is None
    assert pick_shared_registered_fact(
        profile, [provider.packages[SCHEME], provider.packages["PM-KISAN-IN"]],
        provider.registry,
    ) in provider.packages["PM-KISAN-IN"].required_facts


def _build_graph(
    provider: RulePackageProvider,
    answer_interpreter: Callable[
        [str, str, str], Awaitable[AnswerInterpretation],
    ],
) -> Any:
    async def search_tool(_client: object, _query: str) -> list[object]:
        return []

    async def eligibility_tool(
        _client: object, scheme_id: str, profile: HouseholdProfile,
    ) -> EligibilityResponse:
        return evaluate_registered_profile(
            scheme_id, profile, provider.packages, provider.bundles,
            provider.registry,
        )

    async def identity_rewriter(query: str) -> str:
        return query

    return build_journey_graph(
        None,
        provider.packages,
        search_tool=search_tool,
        eligibility_tool=eligibility_tool,
        query_rewriter=identity_rewriter,
        answer_interpreter=answer_interpreter,
        checkpointer=MemorySaver(),
        today=lambda: AS_OF,
        fact_registry=provider.registry,
        rule_bundles=provider.bundles,
    )


@pytest.mark.parametrize(("locale", "message_part"), [
    ("en", "before 1 October 2022"),
    ("hi", "1 अक्टूबर 2022"),
    ("mr", "1 ऑक्टोबर 2022"),
])
def test_apy_historical_date_refusal_reaches_journey(
    provider: RulePackageProvider, locale: str, message_part: str,
) -> None:
    async def unused_interpreter(_fact, _question, _reply):
        return AnswerInterpretation(kind="uncertain", confidence=0.0)

    graph = _build_graph(provider, unused_interpreter)
    result = asyncio.run(run_journey(
        graph,
        JourneyRequest(
            action="evaluate", scheme_id=SCHEME, locale=locale,
            profile={
                "application_date": "2022-09-30",
                "date_of_birth": "1990-01-01",
                "apy_is_citizen_of_india": True,
                "apy_has_savings_bank_account": True,
                "apy_is_or_has_been_income_tax_payer": True,
            },
        ),
    ))

    assert result.status == "need_more_information"
    assert result.eligibility_result is not None
    assert message_part in result.eligibility_result.reason
    assert result.eligibility_result.deciding_rule_ids == []


def test_apy_historical_date_ends_interview_without_more_questions(
    provider: RulePackageProvider,
) -> None:
    async def unused_interpreter(_fact, _question, _reply):
        return AnswerInterpretation(kind="uncertain", confidence=0.0)

    graph = _build_graph(provider, unused_interpreter)
    result = asyncio.run(run_journey(
        graph,
        JourneyRequest(
            action="interview", scheme_id=SCHEME,
            profile={"application_date": "2022-09-30"},
        ),
    ))

    assert result.status == "need_more_information"
    assert result.pending_fact is None
    assert result.eligibility_result is not None
    assert "before 1 October 2022" in result.eligibility_result.reason


def test_apy_free_text_profile_is_not_sent_to_fact_interpreter(
    provider: RulePackageProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Sensitive APY profile text reached fact extraction")

    async def unused_interpreter(_fact, _question, _reply):
        return AnswerInterpretation(kind="uncertain", confidence=0.0)

    monkeypatch.setattr(
        journey_module, "propose_initial_registered_facts", forbidden,
    )
    graph = _build_graph(provider, unused_interpreter)
    result = asyncio.run(run_journey(
        graph,
        JourneyRequest(
            action="interview",
            scheme_id=SCHEME,
            profile_description="I used to pay income tax.",
        ),
    ))

    assert result.status == "awaiting_answer"
    assert "I used to pay income tax" not in repr(result)


def test_apy_invalid_sensitive_answer_is_not_interpreted_or_echoed(
    provider: RulePackageProvider,
) -> None:
    interpreted: list[str] = []

    async def interpreter(_fact, _question, reply):
        interpreted.append(reply)
        return AnswerInterpretation(
            kind="value", value=True, confidence=1.0,
        )

    graph = _build_graph(provider, interpreter)
    started = asyncio.run(run_journey(
        graph,
        JourneyRequest(action="interview", scheme_id=SCHEME),
    ))
    assert started.status == "awaiting_answer"
    assert provider.registry.get(started.pending_fact).privacy.sensitivity != "ordinary"

    reply_text = "I used to pay income tax."
    result = asyncio.run(resume_journey(
        graph, started.conversation_id, reply_text,
    ))

    assert result.status == "awaiting_answer"
    assert interpreted == []
    assert reply_text not in repr(result)
