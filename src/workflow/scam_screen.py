"""Flag scheme-like scam lures before they are treated as official guidance.

Complements injection_guard.py. Narrow literal patterns for processing fees,
UPI collection, OTP phishing, and unofficial WhatsApp "approval" channels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SCAM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bprocessing fee\b", re.IGNORECASE),
    re.compile(r"\bUPI\b", re.IGNORECASE),
    re.compile(r"@paytm\b", re.IGNORECASE),
    re.compile(r"\benter your OTP\b", re.IGNORECASE),
    re.compile(r"\bwhats?app\b", re.IGNORECASE),
    re.compile(r"\bscan this QR\b", re.IGNORECASE),
    re.compile(r"\bKYC fee\b", re.IGNORECASE),
    re.compile(r"https?://\S*(gov-in|verify\.example)\S*", re.IGNORECASE),
)


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
