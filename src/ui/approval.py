"""Bind frontend approval to the exact synthetic application draft shown."""

import hashlib
import json

from src.ui.models import ApplicationDraft


def draft_fingerprint(draft: ApplicationDraft) -> str:
    """Return a stable SHA-256 digest for all validated draft fields."""

    payload = draft.model_dump(mode="json")
    # Canonical JSON prevents ordering and whitespace from changing the digest.
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def approval_matches(
    approved_fingerprint: str | None,
    current_draft: ApplicationDraft,
) -> bool:
    """Check whether the recorded approval still belongs to the current draft."""

    if approved_fingerprint is None:
        return False
    return approved_fingerprint == draft_fingerprint(current_draft)
