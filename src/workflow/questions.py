"""Question text for each profile fact, and plain-code answer reading.

Phase 2 uses fixed English questions and simple rules to read answers, so the
chat costs nothing to run and behaves the same every time. An LLM can later
rephrase questions or read free-form answers, but the rules here stay the
safety net.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from src.rules.models import BOOL_FACTS


# One question per HouseholdProfile field. The picker returns a field name,
# and intake looks up its question here.
QUESTIONS: dict[str, str] = {
    "date_of_birth": (
        "What is your date of birth? For example 12 March 1981 or "
        "12/03/1981."
    ),
    "application_date": (
        "On what date are you applying? For example 30 October 2026."
    ),
    "is_widow": "Are you a widow?",
    "bpl_card_shown": "Can you show a government BPL (Below Poverty Line) card?",
    "landholding_family_in_state_records": (
        "Does the farmer family have cultivable land in State/UT records?"
    ),
    "institutional_landholder": "Is the land held by an institution?",
    "listed_public_office_member": (
        "Does a family member hold or has held a listed public office, "
        "such as minister, MP, MLA or mayor?"
    ),
    "excluded_government_employee_member": (
        "Is a family member a serving or retired government employee "
        "(other than the stated lower-grade exceptions)?"
    ),
    "pension_at_least_10000_excluding_stated_grades": (
        "Does a family member receive a pension of Rs. 10,000 or more "
        "per month?"
    ),
    "income_tax_paid_last_assessment_year": (
        "Did a family member pay income tax in the last assessment year?"
    ),
    "registered_practicing_professional_member": (
        "Is a family member a registered, practicing professional, such as "
        "a doctor, engineer, lawyer or chartered accountant?"
    ),
    "nri_new_beneficiary": (
        "Is this a new application from a farmer family that is NRI "
        "(Non-Resident Indian)?"
    ),
}

# Hint added before a question when the reply could not be understood.
YES_NO_HINT = 'Please answer "yes", "no" or "I don\'t know".'
DATE_HINT = (
    'Please give a date like 12 March 1981 or 12/03/1981, or say '
    '"I don\'t know".'
)

# Accepted replies, compared after trimming, lower-casing and removing
# punctuation at the end (so "Yes." and " YES " both count as "yes").
YES_WORDS = frozenset({"yes", "y", "yeah", "yep", "true", "correct"})
NO_WORDS = frozenset({"no", "n", "nope", "false"})
DONT_KNOW_WORDS = frozenset(
    {
        "i don't know",
        "i dont know",
        "don't know",
        "dont know",
        "not sure",
        "unknown",
        "idk",
        "skip",
    }
)

# Date formats tried in order. %d = day, %m = month number, %B = full month
# name, %b = short month name, %Y = 4-digit year.
DATE_FORMATS = (
    "%Y-%m-%d",  # 1981-03-12
    "%d/%m/%Y",  # 12/03/1981 (Indian day-first order)
    "%d-%m-%Y",  # 12-03-1981
    "%d.%m.%Y",  # 12.03.1981
    "%d %B %Y",  # 12 March 1981
    "%d %b %Y",  # 12 Mar 1981
    "%B %d %Y",  # March 12 1981
    "%b %d %Y",  # Mar 12 1981
)


@dataclass(frozen=True)
class ParsedAnswer:
    """What a reply meant for one fact.

    kind:
        "value"   - a usable answer; ``value`` holds it.
        "unknown" - the person does not know; do not ask again.
        "invalid" - not understood; ``error`` says how to answer.
    """

    kind: Literal["value", "unknown", "invalid"]
    value: bool | date | None = None
    error: str | None = None


def question_for(fact: str) -> str:
    """Return the question to ask for a profile fact."""

    return QUESTIONS[fact]


def _normalise(reply: str) -> str:
    """Lower-case a reply and drop extra spaces and trailing punctuation.

    The curly apostrophe (’) from phone keyboards becomes a straight one, so
    "don’t know" matches "don't know".
    """

    cleaned = reply.replace("\u2019", "'").strip().lower().rstrip(".!?")
    # Collapse repeated spaces: "12   March  1981" -> "12 March 1981".
    return " ".join(cleaned.split())


def _parse_date(text: str) -> date | None:
    """Try each known date format; return None if none match."""

    # Commas are optional: "March 12, 1981" -> "march 12 1981".
    text = text.replace(",", " ")
    text = " ".join(text.split())
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            # This format did not match; try the next one.
            continue
    return None


def parse_answer(fact: str, reply: str) -> ParsedAnswer:
    """Turn a chat reply into a value for ``fact``.

    Examples:
        parse_answer("is_widow", "Yes")              -> value True
        parse_answer("is_widow", "not sure")         -> unknown
        parse_answer("is_widow", "maybe")            -> invalid
        parse_answer("date_of_birth", "12/03/1981")  -> value 1981-03-12
    """

    text = _normalise(reply)

    # "I don't know" works for every kind of question.
    if text in DONT_KNOW_WORDS:
        return ParsedAnswer(kind="unknown")

    if fact in BOOL_FACTS:
        if text in YES_WORDS:
            return ParsedAnswer(kind="value", value=True)
        if text in NO_WORDS:
            return ParsedAnswer(kind="value", value=False)
        return ParsedAnswer(kind="invalid", error=YES_NO_HINT)

    # The only non-yes/no facts are dates.
    parsed_date = _parse_date(text)
    if parsed_date is None:
        return ParsedAnswer(kind="invalid", error=DATE_HINT)
    return ParsedAnswer(kind="value", value=parsed_date)
