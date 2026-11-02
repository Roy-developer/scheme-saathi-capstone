"""Tests for question text and plain-code answer reading."""

from datetime import date

import pytest

from src.rules.models import HouseholdProfile
from src.workflow.questions import QUESTIONS, parse_answer


def test_every_profile_fact_has_a_question():
    assert set(QUESTIONS) == set(HouseholdProfile.model_fields)


@pytest.mark.parametrize(
    ("reply", "kind", "value"),
    [
        ("Yes", "value", True),
        (" YES. ", "value", True),
        ("y", "value", True),
        ("no", "value", False),
        ("Nope!", "value", False),
        ("I don't know", "unknown", None),
        ("I don\u2019t know", "unknown", None),  # phone keyboard apostrophe
        ("not sure", "unknown", None),
        ("maybe", "invalid", None),
        ("12/03/1981", "invalid", None),  # a date is not a yes/no answer
    ],
)
def test_yes_no_answers(reply, kind, value):
    parsed = parse_answer("is_widow", reply)

    assert (parsed.kind, parsed.value) == (kind, value)


@pytest.mark.parametrize(
    "reply",
    [
        "1981-03-12",
        "12/03/1981",
        "12-03-1981",
        "12.03.1981",
        "12 March 1981",
        "12 mar 1981",
        "March 12, 1981",
        "  12   March   1981 ",
    ],
)
def test_date_formats(reply):
    assert parse_answer("date_of_birth", reply).value == date(1981, 3, 12)


@pytest.mark.parametrize("reply", ["yes", "31/02/1981", "last year"])
def test_bad_dates_ask_again(reply):
    parsed = parse_answer("date_of_birth", reply)

    assert parsed.kind == "invalid"
    assert parsed.error


def test_dont_know_works_for_dates():
    assert parse_answer("date_of_birth", "skip").kind == "unknown"
