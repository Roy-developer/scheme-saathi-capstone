"""Tests for question text and plain-code answer reading."""

from datetime import date

import pytest

from src.rules.models import HouseholdProfile
from src.workflow.questions import (
    QUESTIONS,
    fact_confirmation,
    parse_answer,
    parse_interpreted_answer,
    question_for,
)


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


def test_interpreted_answers_must_match_the_fact_type():
    assert parse_interpreted_answer("is_widow", True).value is True
    assert parse_interpreted_answer("is_widow", "yes").kind == "invalid"
    assert parse_interpreted_answer(
        "date_of_birth", "1981-03-12"
    ).value == date(1981, 3, 12)
    assert parse_interpreted_answer("date_of_birth", True).kind == "invalid"


@pytest.mark.parametrize(
    ("locale", "yes", "no", "unknown", "date_reply"),
    [
        ("hi", "हाँ", "नहीं", "मुझे नहीं पता", "१२/०३/१९८१"),
        ("mr", "होय", "नाही", "माहित नाही", "१२/०३/१९८१"),
    ],
)
def test_localized_answers_questions_and_confirmations(
    locale, yes, no, unknown, date_reply
):
    assert parse_answer("is_widow", yes, locale).value is True
    assert parse_answer("is_widow", no, locale).value is False
    assert parse_answer("is_widow", unknown, locale).kind == "unknown"
    assert parse_answer("date_of_birth", date_reply, locale).value == date(1981, 3, 12)
    assert question_for("is_widow", locale) != question_for("is_widow")
    assert yes in fact_confirmation("is_widow", True, locale)


@pytest.mark.parametrize(
    ("locale", "reply", "expected"),
    [
        ("hi", "12 मार्च 1958", date(1958, 3, 12)),
        ("hi", "१२ मार्च १९५८", date(1958, 3, 12)),
        ("hi", "5 फ़रवरी 1960", date(1960, 2, 5)),
        ("hi", "5 \u092b\u093cरवरी 1960", date(1960, 2, 5)),
        ("hi", "1 सितम्बर 1970", date(1970, 9, 1)),
        ("mr", "12 मार्च 1958", date(1958, 3, 12)),
        ("mr", "3 मे 1965", date(1965, 5, 3)),
        ("mr", "30 डिसेंबर 1959", date(1959, 12, 30)),
    ],
)
def test_hindi_and_marathi_month_names_are_read(locale, reply, expected):
    """The hi/mr date questions show "12 मार्च 1981" as their own example."""

    parsed = parse_answer("date_of_birth", reply, locale)
    assert parsed.kind == "value"
    assert parsed.value == expected
