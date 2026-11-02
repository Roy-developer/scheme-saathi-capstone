"""Tests for the Phase 2 question picker."""

from datetime import date

import pytest

from src.rules.data_provider import RulePackageProvider
from src.rules.models import HouseholdProfile
from src.workflow.question_picker import pick_next_fact

APPLICATION_DATE = date(2026, 10, 30)
packages = RulePackageProvider()
WIDOW = packages.get("IGNWPS-MH")
PMKISAN = packages.get("PM-KISAN-IN")


def widow_profile(**facts) -> HouseholdProfile:
    """Build a widow-pension profile with the fixed application date."""

    return HouseholdProfile(application_date=APPLICATION_DATE, **facts)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        # Nothing known: ask the first rule's fact.
        ({}, "is_widow"),
        # Widow known: the age rule needs date_of_birth, not "age".
        ({"is_widow": True}, "date_of_birth"),
        # Age known: only the BPL card is left.
        ({"is_widow": True, "date_of_birth": date(1976, 10, 30)}, "bpl_card_shown"),
    ],
)
def test_asks_first_unknown_fact_in_rule_order(facts, expected):
    assert pick_next_fact(widow_profile(**facts), WIDOW) == expected


@pytest.mark.parametrize(
    "facts",
    [
        # Sunita: eligible, so nothing to ask.
        {"is_widow": True, "date_of_birth": date(1976, 10, 30), "bpl_card_shown": True},
        # Meera: too young, a failed rule wins.
        {"is_widow": True, "date_of_birth": date(1986, 10, 31)},
        # Lata: already said "No" to the card; she must show it, not be re-asked.
        {"is_widow": True, "date_of_birth": date(1976, 10, 30), "bpl_card_shown": False},
    ],
)
def test_stops_when_nothing_useful_to_ask(facts):
    assert pick_next_fact(widow_profile(**facts), WIDOW) is None


def test_skips_facts_the_person_does_not_know():
    profile = widow_profile()

    assert pick_next_fact(profile, WIDOW, frozenset({"is_widow"})) == "date_of_birth"


def test_stops_when_every_unknown_fact_was_skipped():
    profile = widow_profile(is_widow=True)
    skipped = frozenset({"date_of_birth", "bpl_card_shown"})

    assert pick_next_fact(profile, WIDOW, skipped) is None


def test_pmkisan_stops_after_income_tax_fails():
    ramesh = HouseholdProfile(
        landholding_family_in_state_records=True,
        income_tax_paid_last_assessment_year=True,
    )

    assert pick_next_fact(ramesh, PMKISAN) is None


def test_pmkisan_asks_land_first():
    assert pick_next_fact(HouseholdProfile(), PMKISAN) == "landholding_family_in_state_records"
