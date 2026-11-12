"""Refuse requests to misstate household facts so a scheme looks eligible.

Policy: docs/POLICY.md section 1, item 2 ("Inflate eligibility"). Saathi
must not accept false facts or help anyone hide or change facts (age,
income, widow status, BPL status) to qualify. True facts win.

This is a plain-code check that runs on the citizen's text before any model
reads it. When it matches, the text is not used to set any fact; the citizen
sees a short refusal that says why, and the same question is asked again.

Like ``injection_guard``, it is kept narrow and literal: it looks for an
explicit request to misstate (lie, hide, fake, pretend, show income lower),
not for ordinary answers such as "my income is low" or "I am not a widow".
It is a first filter, not proof of honesty: someone who simply types a false
answer is not caught here. The rule engine, the confirmation step and the
human approval of every draft remain the backstop.
"""

import re
from dataclasses import dataclass
from typing import Literal

Locale = Literal["en", "hi", "mr"]

_FACT_WORDS = r"(income|salary|earnings|age|land|landholding|marriage|remarriage|status)"

_MISSTATEMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # English: explicit requests to lower, hide or fake a fact.
    re.compile(r"\bunder-?\s?(report|state|declare)", re.IGNORECASE),
    re.compile(
        r"\b(show|put|write|enter|say|mark|record|declare|tell them)\b[^.?!]{0,30}"
        r"\b(income|salary|earnings)\b[^.?!]{0,20}\b(lower|less|smaller|below)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(lower|reduce|decrease|cut|hide|change|fake|fudge)\b[^.?!]{0,15}"
        rf"\b(my|our|the)\b[^.?!]{{0,15}}\b{_FACT_WORDS}\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bhide (that|the fact|my|our)\b", re.IGNORECASE),
    re.compile(r"\b(don'?t|do not|never) (mention|tell|say|report|disclose)\b", re.IGNORECASE),
    re.compile(r"\blie (about|on|to)\b", re.IGNORECASE),
    re.compile(r"\bpretend\b", re.IGNORECASE),
    re.compile(r"\b(fake|false|forged)\b[^.?!]{0,20}\b(income|certificate|age|document|details|answer)", re.IGNORECASE),
    re.compile(r"\bmake (me|us|it) (look |seem |appear )?eligible\b", re.IGNORECASE),
    re.compile(r"\beven though (i|we) (am|are|'m|'re)? ?not\b", re.IGNORECASE),
    # Hindi (Devanagari and common romanised forms).
    re.compile(r"(आय|आमदनी|इनकम|कमाई)\s*कम\s*(बता|दिखा|लिख)"),
    re.compile(r"कम\s*(आय|आमदनी|इनकम|कमाई)\s*(बता|दिखा|लिख)"),
    re.compile(r"झूठ|छुपा|छिपा|फ़र्ज़ी|फर्जी|नकली"),
    re.compile(r"\b(income|aamdani|kamai)\s+kam\s+(batao|bata|dikhao|dikha|likho|likh)", re.IGNORECASE),
    re.compile(r"\b(jhooth|jhoot|chupao|chhupao|farzi)\b", re.IGNORECASE),
    # Marathi.
    re.compile(r"(उत्पन्न|कमाई)\s*कमी\s*(दाखव|सांग|लिह)"),
    re.compile(r"खोटे|खोटं|खोटी|लपव|बनावट"),
)

_REFUSALS: dict[str, str] = {
    "en": (
        "I can't do that. Saathi only checks eligibility using true facts, and "
        "I can't change, lower or hide a fact to make a scheme look eligible. "
        "A wrong answer could get the application rejected or the benefit "
        "taken back later. Please answer with the real facts. If you are "
        "unsure, say \"I don't know\" and a caseworker can help."
    ),
    "hi": (
        "मैं ऐसा नहीं कर सकता। साथी केवल सच्ची जानकारी से पात्रता जाँचता है, और "
        "किसी योजना में पात्र दिखाने के लिए कोई जानकारी बदल, कम या छिपा नहीं सकता। "
        "गलत उत्तर से आवेदन रद्द हो सकता है या बाद में लाभ वापस लिया जा सकता है। "
        "कृपया सही जानकारी दें। यदि आप निश्चित नहीं हैं, तो \"पता नहीं\" कहें, "
        "एक कार्यकर्ता मदद करेगा।"
    ),
    "mr": (
        "मी हे करू शकत नाही. साथी फक्त खऱ्या माहितीवरून पात्रता तपासतो, आणि "
        "योजनेसाठी पात्र दिसावे म्हणून कोणतीही माहिती बदलू, कमी करू किंवा लपवू "
        "शकत नाही. चुकीच्या उत्तरामुळे अर्ज नाकारला जाऊ शकतो किंवा नंतर लाभ परत "
        "घेतला जाऊ शकतो. कृपया खरी माहिती द्या. खात्री नसल्यास \"माहित नाही\" "
        "म्हणा, कार्यकर्ता मदत करेल."
    ),
}


@dataclass(frozen=True)
class HonestyCheck:
    """Whether the citizen asked Saathi to misstate a fact."""

    flagged: bool
    matched_patterns: tuple[str, ...]


def check_for_misstatement(raw: str) -> HonestyCheck:
    """Return whether ``raw`` asks Saathi to lower, hide or fake a fact."""

    matched = tuple(
        pattern.pattern for pattern in _MISSTATEMENT_PATTERNS if pattern.search(raw)
    )
    return HonestyCheck(flagged=bool(matched), matched_patterns=matched)


def misstatement_refusal(locale: str = "en") -> str:
    """The refusal shown to the citizen, in their language."""

    return _REFUSALS.get(locale, _REFUSALS["en"])
