"""Rule-engine checks for the IGNDPS-MH mock package (synthetic personas only).

Covers the three outcomes the onboarding guide requires: eligible,
not_eligible and need_more_information. The official page sets an age range
of 18 to 79 for a disabled person, and encodes no income or percentage limit.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from eval.schema import profile_from_mapping

APPLICATION_DATE = date(2026, 11, 12)


@pytest.fixture(scope="module")
def provider() -> RulePackageProvider:
    return RulePackageProvider()


def _verdict(provider: RulePackageProvider, age: int, has_disability: bool | None) -> str:
    """Build a synthetic profile with the given age and disability answer."""

    birth_year = APPLICATION_DATE.year - age
    mapping: dict[str, object] = {
        "date_of_birth": f"{birth_year}-01-01",
        "application_date": APPLICATION_DATE.isoformat(),
    }
    if has_disability is not None:
        mapping["has_disability"] = has_disability
    profile = profile_from_mapping(mapping, provider.registry)
    return evaluate_mock_eligibility(
        profile, provider.get("IGNDPS-MH"), registry=provider.registry
    ).result


@pytest.mark.parametrize("age", [18, 40, 79])
def test_disabled_person_in_the_age_range_is_eligible(provider, age: int) -> None:
    assert _verdict(provider, age, True) == "eligible"


@pytest.mark.parametrize("age", [17, 80])
def test_disabled_person_outside_the_age_range_is_not_eligible(provider, age: int) -> None:
    assert _verdict(provider, age, True) == "not_eligible"


def test_not_disabled_person_is_not_eligible(provider) -> None:
    assert _verdict(provider, 40, False) == "not_eligible"


def test_unanswered_disability_question_needs_more_information(provider) -> None:
    assert _verdict(provider, 40, None) == "need_more_information"
