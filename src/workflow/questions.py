"""Deterministic reading of answers to registered fact questions."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

from src.rules.facts import FactDefinition, FactRegistry


YES_NO_HINTS = {
    "en": 'Please answer "yes", "no" or "I don\'t know".',
    "hi": 'कृपया "हाँ", "नहीं" या "मुझे नहीं पता" में उत्तर दें।',
    "mr": 'कृपया "होय", "नाही" किंवा "माहित नाही" असे उत्तर द्या.',
}
DATE_HINTS = {
    "en": 'Please give a date like 12 March 1981 or 12/03/1981, or say "I don\'t know".',
    "hi": 'कृपया 12/03/1981 जैसी तारीख दें या "मुझे नहीं पता" कहें।',
    "mr": 'कृपया 12/03/1981 अशी तारीख द्या किंवा "माहित नाही" असे सांगा.',
}
UNCLEAR_REPLY_PREFIX = {
    "en": "I could not understand that.",
    "hi": "मुझे समझ नहीं आया।",
    "mr": "मला समजले नाही.",
}
INTEGER_REPLY_PATTERN = re.compile(r"[+-]?[0-9]+")
DECIMAL_REPLY_PATTERN = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
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
LOCALIZED_YES_WORDS: dict[str, frozenset[str]] = {
    "hi": frozenset({"हाँ", "हां", "जी", "जी हाँ", "सही"}),
    "mr": frozenset({"होय", "हो", "बरोबर", "होय आहे"}),
}
LOCALIZED_NO_WORDS: dict[str, frozenset[str]] = {
    "hi": frozenset({"नहीं", "नही", "जी नहीं"}),
    "mr": frozenset({"नाही", "न", "नसते"}),
}
LOCALIZED_UNKNOWN_WORDS: dict[str, frozenset[str]] = {
    "hi": frozenset({"मुझे नहीं पता", "पता नहीं", "मालूम नहीं", "अनिश्चित"}),
    "mr": frozenset({"माहित नाही", "माहीत नाही", "ठाऊक नाही", "निश्चित नाही"}),
}

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

# Hindi and Marathi month names (with common spelling variants), mapped to the
# English names DATE_FORMATS understands. Longer names come first so a
# replacement never cuts a longer name ("फ़रवरी" before shorter forms).
DEVANAGARI_MONTHS = {
    name: english
    for english, names in (
        ("january", ("जनवरी", "जानेवारी")),
        # "फ़" may be typed as one character (U+095E) or as फ + nukta.
        ("february", ("फ़रवरी", "फ़रवरी", "फरवरी", "फेब्रुवारी")),
        ("march", ("मार्च",)),
        ("april", ("अप्रैल", "एप्रिल")),
        ("may", ("मई", "मे")),
        ("june", ("जून",)),
        ("july", ("जुलाई", "जुलै")),
        ("august", ("अगस्त", "ऑगस्ट")),
        ("september", ("सितंबर", "सितम्बर", "सप्टेंबर")),
        ("october", ("अक्टूबर", "अक्तूबर", "ऑक्टोबर")),
        ("november", ("नवंबर", "नवम्बर", "नोव्हेंबर")),
        ("december", ("दिसंबर", "दिसम्बर", "डिसेंबर")),
    )
    for name in names
}
DEVANAGARI_MONTHS = dict(sorted(DEVANAGARI_MONTHS.items(), key=lambda item: -len(item[0])))


@dataclass(frozen=True)
class ParsedAnswer:
    """What a reply meant for one fact.

    kind:
        "value"   - a usable answer; ``value`` holds it.
        "unknown" - the person does not know; do not ask again.
        "invalid" - not understood; ``error`` says how to answer.
    """

    kind: Literal["value", "unknown", "invalid"]
    value: object | None = None
    error: str | None = None


def registry_question_for(
    definition: FactDefinition,
    locale: str = "en",
) -> str:
    """Return reviewed question copy for a registry-backed fact."""

    question = definition.questions.get(locale) or definition.questions["en"]
    return question.text


def registered_question_details(
    definition: FactDefinition,
    locale: str = "en",
) -> dict[str, object]:
    """Build the data-driven answer widget contract for one registered fact."""

    question = definition.questions.get(locale) or definition.questions["en"]
    labels = definition.choice_labels.get(locale, {})
    return {
        "fact_id": definition.fact_id,
        "value_type": definition.value_type,
        "unit": definition.unit,
        "minimum": definition.minimum,
        "maximum": definition.maximum,
        "max_length": definition.max_length,
        "choices": [
            {"code": choice, "label": labels.get(choice, choice)}
            for choice in definition.choices
        ],
        "help_text": question.help_text,
    }


def parse_registered_answer(
    definition: FactDefinition,
    reply: str,
    locale: str = "en",
) -> ParsedAnswer:
    """Parse a reply strictly using its registered type, bounds, and choices."""

    text = _normalise(reply, locale)
    if (
        text in DONT_KNOW_WORDS
        or text in LOCALIZED_UNKNOWN_WORDS.get(locale, frozenset())
    ):
        return ParsedAnswer(kind="unknown")

    try:
        if definition.value_type == "boolean":
            if text in YES_WORDS | LOCALIZED_YES_WORDS.get(locale, frozenset()):
                value: object = True
            elif text in NO_WORDS | LOCALIZED_NO_WORDS.get(locale, frozenset()):
                value = False
            else:
                raise ValueError
        elif definition.value_type == "date":
            parsed_date = _parse_date(text)
            if parsed_date is None:
                raise ValueError
            value = parsed_date
        elif definition.value_type == "integer":
            if INTEGER_REPLY_PATTERN.fullmatch(text) is None:
                raise ValueError
            value = int(text)
        elif definition.value_type == "decimal":
            if DECIMAL_REPLY_PATTERN.fullmatch(text) is None:
                raise ValueError
            try:
                value = Decimal(text)
            except InvalidOperation as error:
                raise ValueError from error
            if not value.is_finite():
                raise ValueError
        elif definition.value_type == "choice":
            labels = definition.choice_labels.get(locale, {})
            value = next(
                choice
                for choice in definition.choices
                if text == _normalise(choice, locale)
                or (
                    labels.get(choice)
                    and text == _normalise(labels[choice], locale)
                )
            )
        elif definition.value_type == "text":
            value = reply.strip()
            if not value:
                raise ValueError
        else:
            raise ValueError
        normalized = definition.validate_value(value)
    except (ValueError, StopIteration, TypeError):
        return ParsedAnswer(
            kind="invalid",
            error=_registered_answer_hint(definition, locale),
        )
    return ParsedAnswer(kind="value", value=normalized)


def _registered_answer_hint(
    definition: FactDefinition,
    locale: str,
) -> str:
    """Explain a registered answer constraint without changing its meaning."""

    if definition.value_type == "boolean":
        return YES_NO_HINTS.get(locale, YES_NO_HINTS["en"])
    if definition.value_type == "date":
        return DATE_HINTS.get(locale, DATE_HINTS["en"])
    if definition.value_type in {"integer", "decimal"}:
        bounds = []
        if definition.minimum is not None:
            bounds.append(
                f"{_bound_label('minimum', locale)} {definition.minimum}"
            )
        if definition.maximum is not None:
            bounds.append(
                f"{_bound_label('maximum', locale)} {definition.maximum}"
            )
        unit = f" {definition.unit}" if definition.unit else ""
        if locale == "hi":
            return f"कृपया मान{unit} दें" + (
                f" ({', '.join(bounds)})" if bounds else ""
            ) + ' या "मुझे नहीं पता" कहें।'
        if locale == "mr":
            return f"कृपया मूल्य{unit} द्या" + (
                f" ({', '.join(bounds)})" if bounds else ""
            ) + ' किंवा "माहित नाही" असे सांगा.'
        return f"Enter a valid number{unit}" + (
            f" ({', '.join(bounds)})" if bounds else ""
        ) + ' or say "I don\'t know".'
    if definition.value_type == "text":
        if locale == "hi":
            return (
                f"कृपया {definition.max_length} अक्षरों तक का पाठ दें "
                'या "मुझे नहीं पता" कहें।'
            )
        if locale == "mr":
            return (
                f"कृपया {definition.max_length} अक्षरांपर्यंत मजकूर द्या "
                'किंवा "माहित नाही" असे सांगा.'
            )
        return (
            f"Enter text up to {definition.max_length} characters "
            'or say "I don\'t know".'
        )
    labels = definition.choice_labels.get(locale, {})
    options = ", ".join(labels.get(code, code) for code in definition.choices)
    if locale == "hi":
        return f"कृपया इनमें से चुनें: {options} या कहें “मुझे नहीं पता”।"
    if locale == "mr":
        return f"कृपया यापैकी निवडा: {options} किंवा “माहित नाही” असे सांगा."
    return f"Choose one of: {options}, or say “I don't know”."


def _bound_label(bound: str, locale: str) -> str:
    """Localize numeric-bound labels used in invalid-answer hints."""

    labels = {
        "minimum": {"en": "minimum", "hi": "न्यूनतम", "mr": "किमान"},
        "maximum": {"en": "maximum", "hi": "अधिकतम", "mr": "कमाल"},
    }
    return labels[bound].get(locale, labels[bound]["en"])


def registered_fact_confirmation(
    definition: FactDefinition,
    value: bool | str,
    locale: str = "en",
) -> str:
    """Render a proposal for a registry-backed fact for explicit confirmation."""

    return _confirmation_text(registry_question_for(definition, locale), value, locale)


def registered_confirmation_details(definition: FactDefinition) -> dict[str, object]:
    """Build the yes/no answer widget used to confirm a proposed value."""

    return {
        "fact_id": definition.fact_id,
        "value_type": "boolean",
        "choices": [],
        "confirming": True,
    }


def _confirmation_text(question: str, value: bool | str, locale: str) -> str:
    """Ask whether a proposed value is what the person meant."""

    display = (
        ("हाँ" if value else "नहीं") if locale == "hi" and isinstance(value, bool)
        else ("होय" if value else "नाही")
        if locale == "mr" and isinstance(value, bool)
        else "yes" if value is True
        else "no" if value is False
        else str(value)
    )
    if locale == "hi":
        return (
            f'{question} आपके उत्तर को "{display}" समझा। '
            "क्या यह सही है? "
            '"हाँ" या "नहीं" में उत्तर दें।'
        )
    if locale == "mr":
        return (
            f'{question} तुमचे उत्तर "{display}" असे समजले. '
            "हे बरोबर आहे का? "
            '"होय" किंवा "नाही" असे उत्तर द्या.'
        )
    return (
        f'{question} I understood your answer as "{display}". '
        "Is that correct? "
        "Please answer yes or no."
    )


def localized_unknown_message(locale: str) -> str:
    """Return a short localized acknowledgement when a person skips a fact."""

    return {
        "hi": "ठीक है। इस जानकारी को अभी अज्ञात मानेंगे।",
        "mr": "ठीक आहे. ही माहिती सध्या अज्ञात मानू.",
    }.get(locale, "Okay. We will leave this information unknown for now.")


def unknown_answer_label(locale: str) -> str:
    """Return the "I don't know" choice as the person sees it."""

    return {"hi": "मुझे नहीं पता", "mr": "माहित नाही"}.get(locale, "I don't know")


def _normalise(reply: str, locale: str = "en") -> str:
    """Lower-case a reply and drop extra spaces and trailing punctuation.

    The curly apostrophe (’) from phone keyboards becomes a straight one, so
    "don’t know" matches "don't know".
    """

    cleaned = reply.replace("\u2019", "'").strip().lower().rstrip(".!?")
    if locale in {"hi", "mr"}:
        cleaned = cleaned.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    # Collapse repeated spaces: "12   March  1981" -> "12 March 1981".
    return " ".join(cleaned.split())


def _parse_date(text: str) -> date | None:
    """Try each known date format; return None if none match."""

    # Hindi/Marathi month names -> English, so "12 मार्च 1981" (the example the
    # hi/mr questions show) parses like "12 March 1981".
    for local_name, english_name in DEVANAGARI_MONTHS.items():
        text = text.replace(local_name, english_name)
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


def parse_interpreted_registered_answer(
    definition: FactDefinition, value: bool | str, locale: str = "en",
) -> ParsedAnswer:
    """Validate a model's proposal against a registered fact's type."""

    if definition.value_type == "boolean" and isinstance(value, bool):
        return ParsedAnswer(kind="value", value=definition.validate_value(value))
    if definition.value_type == "date" and isinstance(value, str):
        return parse_registered_answer(definition, value, locale)
    return ParsedAnswer(kind="invalid", error=_registered_answer_hint(definition, locale))


def parse_confirmation(reply: str, locale: str = "en") -> str:
    """Read a reply to "is that correct?" as yes, no, unknown or unclear."""

    text = _normalise(reply, locale)
    if text in DONT_KNOW_WORDS or text in LOCALIZED_UNKNOWN_WORDS.get(locale, frozenset()):
        return "unknown"
    if text in YES_WORDS | LOCALIZED_YES_WORDS.get(locale, frozenset()):
        return "yes"
    if text in NO_WORDS | LOCALIZED_NO_WORDS.get(locale, frozenset()):
        return "no"
    return "unclear"


def registered_direct_answer_question(
    definition: FactDefinition, locale: str = "en",
) -> str:
    """Ask for a registered fact directly after a proposed value was declined."""

    prompt = {
        "hi": "ठीक है। कृपया सीधे उत्तर दें:",
        "mr": "ठीक आहे. कृपया थेट उत्तर द्या:",
    }.get(locale, "Okay. Please answer directly:")
    return f"{prompt} {registry_question_for(definition, locale)}"


def confirm_yes_or_no_question(locale: str = "en") -> str:
    """Ask again when a confirmation reply was neither yes nor no."""

    return {
        "hi": '"हाँ" या "नहीं" में उत्तर दें। क्या यह समझ सही है?',
        "mr": '"होय" किंवा "नाही" असे उत्तर द्या. हे समजणे बरोबर आहे का?',
    }.get(
        locale,
        'Please confirm with "yes" or "no". Is my interpretation correct?',
    )
