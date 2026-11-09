"""Screen a citizen's free-typed text before it reaches any agent's context.

See docs/THREAT_MODEL.md. Saathi already keeps scheme and document text out
of every model's context, and per-turn free-text replies already go through
a quarantined, tool-free reader (``intake.interpret_free_text_answer``). The
one remaining gap is ``initial_description``: it reaches the full
tool-calling intake agent (``intake_agent.propose_initial_profile_facts``),
which has more reasoning surface than a quarantined reader.

This module is not a replacement for that reader pattern — it is an
additive, lower-risk reduction of what the intake agent's reasoning ever
sees, while the existing schema-constrained ``propose_profile_facts`` tool
and the citizen-only confirmation step remain the real backstop.
"""

import re
from dataclasses import dataclass

# Patterns drawn from documented indirect-injection cases (L15): fake
# system/policy markers, fake authority figures, and explicit override
# requests. Kept deliberately narrow and literal to avoid flagging ordinary
# descriptions that happen to mention "system" or "policy".
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\[\s*SYSTEM\s*\]", re.IGNORECASE),
    re.compile(r"\bSYSTEM\s*:", re.IGNORECASE),
    re.compile(r"\bignore (all |any )?(the )?(previous|prior|above) instructions\b", re.IGNORECASE),
    re.compile(r"\bdisregard (the )?(above|previous|prior)\b", re.IGNORECASE),
    re.compile(r"\byou are now\b", re.IGNORECASE),
    re.compile(r"\bnew instructions?\s*:", re.IGNORECASE),
    re.compile(r"\bupdated polic(y|ies)\b", re.IGNORECASE),
    re.compile(r"\bauditor instruction\b", re.IGNORECASE),
    re.compile(r"\bautomated review(er)?s?\b", re.IGNORECASE),
    re.compile(r"\bpre-?approved\b", re.IGNORECASE),
    re.compile(r"\bcorrect (amount|value|answer) for this\b", re.IGNORECASE),
)

REDACTION_MARK = "[removed: looked like an embedded instruction, not a fact about the household]"


@dataclass(frozen=True)
class ScreenedText:
    """A citizen's text, with suspected embedded instructions neutralised."""

    text: str
    flagged: bool
    matched_patterns: tuple[str, ...]


def screen_free_text(raw: str) -> ScreenedText:
    """Return ``raw`` with suspected injected instructions replaced.

    A guardrail, not a guarantee: it reduces how much attacker-controlled
    text the intake agent's reasoning ever sees. It does not replace the
    schema-constrained proposal step or the citizen-only confirmation step,
    which remain the actual backstop against a bad fact being saved.
    """

    matched: list[str] = []
    cleaned = raw
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            matched.append(pattern.pattern)
            cleaned = pattern.sub(REDACTION_MARK, cleaned)
    return ScreenedText(
        text=cleaned, flagged=bool(matched), matched_patterns=tuple(matched)
    )
