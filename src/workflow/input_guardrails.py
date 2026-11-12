"""Deterministic checks for explicit attempts to override agent instructions."""

import re
import unicodedata


_INJECTION_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\bignore\b.{0,40}\b(?:previous|prior|above|system|developer)\b.{0,30}"
    r"\b(?:instructions?|prompts?|rules?)\b",
    r"\b(?:disregard|override|forget)\b.{0,40}"
    r"\b(?:previous|prior|above|system|developer)\b.{0,30}"
    r"\b(?:instructions?|prompts?|rules?)\b",
    r"\b(?:reveal|show|print|repeat|output|leak)\b.{0,20}"
    r"\b(?:system|developer)\b.{0,15}\b(?:prompt|instructions?)\b",
    r"\b(?:jailbreak|dan mode)\b",
    r"(?:पिछले|पूर्व|ऊपर के|सभी)\s*(?:निर्देश|नियम).{0,30}"
    r"(?:अनदेखा|भूल|नज़रअंदाज़)",
    r"(?:सिस्टम|डेवलपर)\s*(?:प्रॉम्प्ट|निर्देश).{0,20}"
    r"(?:दिखाओ|बताओ|उजागर)",
    r"(?:मागील|आधीच्या|सर्व)\s*(?:सूचना|नियम).{0,30}"
    r"(?:दुर्लक्ष|विसरा|अनदेखा)",
    r"(?:सिस्टम|डेव्हलपर)\s*(?:प्रॉम्प्ट|सूचना).{0,20}"
    r"(?:दाखवा|सांगा|उघड)",
))


def is_prompt_injection(text: str) -> bool:
    """Return true for a narrow set of explicit instruction-override attempts."""

    normalized = " ".join(unicodedata.normalize("NFKC", text).split())
    return any(pattern.search(normalized) for pattern in _INJECTION_PATTERNS)
