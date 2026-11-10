"""IGNOAPS-MH, the first scheme activated through the "approved" gate.

Uses the live data (src/rules), the real loader and the real rule engine.
Cases follow the provisional development tests in
docs/IGNOAPS_MH_RULE_REVIEW_2026-11-08.md: age on the application date, 65
included, no upper limit; "no" to the BPL list means not eligible, and "don't
know" stays unknown.
"""

from datetime import date

import pytest

from src.mcp_servers.tools.eligibility import evaluate_registered_profile
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactState, HouseholdProfile

SCHEME = "IGNOAPS-MH"
APPLICATION_DATE = date(2026, 11, 8)


@pytest.fixture(scope="module")
def provider() -> RulePackageProvider:
    return RulePackageProvider()


def _known(value: object) -> FactState:
    return FactState(status="known", value=value, definition_version="1.0.0",
                     provenance="user_reported")


def _store(*, birth: date | None, on_list: bool | None, list_status: str = "known") -> HouseholdProfile:
    facts = {"application_date": _known(APPLICATION_DATE)}
    if birth is not None:
        facts["date_of_birth"] = _known(birth)
    if on_list is not None or list_status != "known":
        facts["name_on_bpl_list"] = (
            _known(on_list) if list_status == "known"
            else FactState(status=list_status, definition_version="1.0.0")
        )
    return HouseholdProfile(registry_version="1.0.0", facts=facts)


def _evaluate(provider: RulePackageProvider, store: HouseholdProfile):
    return evaluate_registered_profile(
        SCHEME, store, provider.packages, provider.bundles, provider.registry,
    )


def test_ignoaps_is_live_through_the_approved_gate(provider: RulePackageProvider) -> None:
    bundle = provider.bundles[SCHEME]

    assert bundle.activation_state == "approved"
    assert provider.packages[SCHEME].approval_status == "approved_for_mock_portal"
    assert {f.fact_id for f in provider.registry.definitions if f.fact_id in bundle.fact_ids} == {
        "age", "application_date", "date_of_birth", "name_on_bpl_list",
    }


@pytest.mark.parametrize(
    ("case", "birth", "on_list", "expected"),
    [
        ("DEV-IGNOAPS-AGE-64", date(1962, 11, 9), True, "not_eligible"),   # turns 65 the day after
        ("DEV-IGNOAPS-AGE-65", date(1961, 11, 8), True, "eligible"),       # 65th birthday: included
        ("DEV-IGNOAPS-AGE-85", date(1941, 1, 1), True, "eligible"),        # no upper age limit
        ("DEV-IGNOAPS-NOT-ON-LIST", date(1956, 6, 1), False, "not_eligible"),
    ],
)
def test_ignoaps_provisional_development_cases(
    provider: RulePackageProvider, case: str, birth: date, on_list: bool, expected: str,
) -> None:
    result = _evaluate(provider, _store(birth=birth, on_list=on_list))

    assert result.result == expected, case


def test_ignoaps_dont_know_about_the_bpl_list_needs_more_information(
    provider: RulePackageProvider,
) -> None:
    """DEV-IGNOAPS-LIST-UNKNOWN: 'don't know' is not treated as 'no'."""
    result = _evaluate(provider, _store(birth=date(1956, 6, 1), on_list=None, list_status="unknown"))

    assert result.result == "need_more_information"
    assert "name_on_bpl_list" in result.missing_fields
    assert "date of birth" not in result.reason.lower()  # it was given


def test_ignoaps_missing_date_of_birth_needs_more_information(
    provider: RulePackageProvider,
) -> None:
    result = _evaluate(provider, _store(birth=None, on_list=True))

    assert result.result == "need_more_information"


def test_ignoaps_eligible_result_cites_the_official_clause(provider: RulePackageProvider) -> None:
    result = _evaluate(provider, _store(birth=date(1950, 3, 3), on_list=True))

    assert result.result == "eligible"
    assert {item.source_clause_id for item in result.evidence} == {"IGNOAPS-MH-ELIGIBILITY-01"}
    assert all("aged 65 and above" in item.source_text for item in result.evidence)


def test_ignoaps_notice_is_written_for_users(provider: RulePackageProvider) -> None:
    """The app shows this text; it once carried internal development notes."""
    notice = provider.packages[SCHEME].notice

    assert "not a government decision" in notice
    assert not any(word in notice for word in ("Reflexion", "docs/", "src/", "answer key"))
