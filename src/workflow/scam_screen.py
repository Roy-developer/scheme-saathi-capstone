"""Flag scheme-like scam lures before they are treated as official guidance.

Complements injection_guard.py. Literal patterns for processing fees, UPI
collection, OTP phishing, and unofficial WhatsApp "approval" channels.

Used today by Role 5 offline E2 / red-team harnesses and unit tests only — the
live journey does not call this yet. Several patterns (bare ``UPI``,
``whatsapp``) would false-positive on ordinary citizen messages; tighten them
before wiring into intake/journey.
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
