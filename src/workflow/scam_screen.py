"""Flag scheme-like scam lures before they are treated as official guidance.

Complements ``injection_guard``. Patterns require *scam context* (fee, OTP,
approval channel, fake portal) so ordinary citizen replies such as
``I get my pension by UPI`` or ``Can I ask on WhatsApp?`` are not blocked.

Wired into intake free-text description and journey interview replies. Role 5
E2 also probes this helper offline, including clean-case false-positive checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Contextual patterns: keep fee/OTP/QR/fake-portal; require lure context for
# UPI / WhatsApp / Paytm so legitimate payment-method mentions stay clean.
_SCAM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bprocessing fee\b", re.IGNORECASE),
    re.compile(r"\bKYC fee\b", re.IGNORECASE),
    re.compile(r"\benter your OTP\b", re.IGNORECASE),
    re.compile(r"\bscan this QR\b", re.IGNORECASE),
    re.compile(r"https?://\S*(gov-in|verify\.example)\S*", re.IGNORECASE),
    # UPI only with pay/fee/transfer/collection context or a handle.
    re.compile(
        r"(?is)(?:\b(?:pay|paid|paying|fee|fees|send|transfer|processing)\b"
        r".{0,48}\bUPI\b|\bUPI\b.{0,48}\b(?:pay|paid|fee|fees|id|transfer)\b"
        r"|@paytm\b|\bUPI\s*ID\b)"
    ),
    # WhatsApp only with pay/fee/approval or a phone+message lure.
    re.compile(
        r"(?is)(?:\bwhats?app\b.{0,64}\b(?:pay|paid|fee|fees|approv\w*|₹|rs\.?\s*\d)"
        r"|\b(?:pay|paid|fee|fees|approv\w*|message\s+\+?\d).{0,64}\bwhats?app\b)"
    ),
)

_SCAM_WARNINGS: dict[str, str] = {
    "en": (
        "That message looks like a payment or unofficial-channel request. "
        "Saathi never asks you to pay a fee, share an OTP, scan a QR, or "
        "message a personal WhatsApp/UPI for scheme approval. Please answer "
        "only the question asked — do not treat those channels as official."
    ),
    "hi": (
        "यह संदेश भुगतान या अनौपचारिक चैनल जैसा लगता है। साथी कभी शुल्क माँगने, "
        "OTP माँगने, QR स्कैन कराने, या व्यक्तिगत WhatsApp/UPI पर योजना मंजूरी के "
        "लिए संदेश भेजने को नहीं कहता। केवल पूछे गए प्रश्न का उत्तर दें — इन्हें "
        "आधिकारिक न मानें।"
    ),
    "mr": (
        "हा संदेश पेमेंट किंवा अनधिकृत चॅनेलसारखा वाटतो. साथी कधीही फी, OTP, "
        "QR स्कॅन, किंवा वैयक्तिक WhatsApp/UPI वर योजना मंजुरीसाठी संदेश पाठवण्यास "
        "सांगत नाही. फक्त विचारलेल्या प्रश्नाचे उत्तर द्या — हे अधिकृत समजू नका."
    ),
}


@dataclass(frozen=True)
class ScamScreenResult:
    text: str
    flagged: bool
    matched_patterns: tuple[str, ...]


def screen_scam_text(raw: str) -> ScamScreenResult:
    """Return whether ``raw`` looks like a fee/OTP/phishing lure."""

    matched = [pattern.pattern for pattern in _SCAM_PATTERNS if pattern.search(raw)]
    return ScamScreenResult(
        text=raw,
        flagged=bool(matched),
        matched_patterns=tuple(matched),
    )


def scam_warning_for_locale(locale: Literal["en", "hi", "mr"] | str = "en") -> str:
    """Citizen-facing warning when a scam lure is rejected."""

    return _SCAM_WARNINGS.get(locale, _SCAM_WARNINGS["en"])


def apply_scam_screen(raw: str) -> ScamScreenResult:
    """Screen text and, when flagged, increment the guardrail metric."""

    result = screen_scam_text(raw)
    if result.flagged:
        from src.observability.metrics import record_guardrail_block

        record_guardrail_block("scam_screen", "flagged")
    return result


# Legitimate messages that must stay unflagged (E2 false-positive probes).
CLEAN_SCAM_SCREEN_CASES: tuple[str, ...] = (
    "I get my pension by UPI",
    "Can I ask on WhatsApp?",
    "My neighbour said WhatsApp is useful for CSC timings",
    "Do I need OTP for my bank login later?",
    "KYC is already done at the bank",
    "I use Paytm for groceries sometimes",
)
