import hashlib
import json

from src.ui.models import ApplicationDraft


def draft_fingerprint(draft: ApplicationDraft) -> str:
    payload = draft.model_dump(mode="json")
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
    if approved_fingerprint is None:
        return False
    return approved_fingerprint == draft_fingerprint(current_draft)
