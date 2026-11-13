"""Cross-session household memory backed by the LangGraph Store.

A returning person enters a short return code (e.g. ``SAATHI-7K3M``) to reload
the profile facts they gave in an earlier conversation.  The code is generated
once, after the first interview collects enough facts, and the person writes it
down.  On their next visit they enter it, the API loads the saved facts, and
the interview skips every question that is already answered.

Storage layout (LangGraph ``BaseStore``)::

    namespace = ("household",)
    key       = return code  (e.g. "SAATHI-7K3M")
    value     = {
        "typed_facts": <HouseholdProfile.to_wire() dict>,
        "created_at": "2026-11-09T...",
        "updated_at": "2026-11-09T...",
        "locale":     "en",
    }

The same SQLite file that holds checkpoints and budgets is reused, so backups
already cover it.
"""

import logging
import secrets
import string
from datetime import datetime, timedelta, timezone

from langgraph.store.base import BaseStore, Item

from src.rules.facts import (
    SUPPORTED_LOCALES,
    FactRegistry,
    FactState,
    HouseholdProfile,
)

logger = logging.getLogger(__name__)

HOUSEHOLD_NAMESPACE = ("household",)

CODE_PREFIX = "SAATHI"
CODE_RANDOM_LENGTH = 4
CODE_ALPHABET = string.ascii_uppercase + string.digits
MIN_FACTS_TO_SAVE = 2
MEMORY_POLICY_VERSION = "1.0.0"
HOUSEHOLD_TTL_DAYS = 90


def generate_return_code() -> str:
    """Create a short, human-friendly return code.

    Format: ``SAATHI-XXXX`` where X is uppercase alphanumeric.
    Collision probability is negligible at the expected scale.
    """

    random_part = "".join(
        secrets.choice(CODE_ALPHABET) for _ in range(CODE_RANDOM_LENGTH)
    )
    return f"{CODE_PREFIX}-{random_part}"


def normalize_return_code(raw: str) -> str:
    """Strip whitespace and normalize case so entry is forgiving.

    Raises:
        ValueError: The input does not look like a return code.
    """

    cleaned = raw.strip().upper().replace("—", "-").replace("–", "-")
    if not cleaned.startswith(f"{CODE_PREFIX}-") or len(cleaned) != len(CODE_PREFIX) + 1 + CODE_RANDOM_LENGTH:
        raise ValueError("Return code must be in the format SAATHI-XXXX")
    suffix = cleaned[len(CODE_PREFIX) + 1:]
    if not all(character in CODE_ALPHABET for character in suffix):
        raise ValueError("Return code contains invalid characters")
    return cleaned


async def save_household(
    store: BaseStore,
    return_code: str,
    profile: HouseholdProfile,
    registry: FactRegistry,
    locale: str = "en",
    *,
    memory_consent: bool,
    now: datetime | None = None,
) -> None:
    """Persist consented, reviewed, non-highly-sensitive facts.

    Legacy or unreviewed facts are excluded. ``now`` is injectable for expiry
    tests and must be timezone-aware.
    """

    if memory_consent is not True:
        raise ValueError("Explicit memory consent is required.")
    code = normalize_return_code(return_code)
    current_time = _utc_now(now)
    profile = _persistent_profile(profile, registry)
    if len(profile.facts) < MIN_FACTS_TO_SAVE:
        raise ValueError(
            "At least two privacy-approved known facts are required to save."
        )

    existing = await store.aget(HOUSEHOLD_NAMESPACE, code)
    created_at = current_time.isoformat()
    if existing is not None and isinstance(existing.value, dict):
        stored_created_at = existing.value.get("created_at")
        if isinstance(stored_created_at, str):
            created_at = stored_created_at
    record: dict[str, object] = {
        "typed_facts": profile.to_wire(registry),
        "fact_ids": sorted(profile.facts),
        "created_at": created_at,
        "updated_at": current_time.isoformat(),
        "expires_at": (
            current_time + timedelta(days=HOUSEHOLD_TTL_DAYS)
        ).isoformat(),
        "locale": locale if locale in SUPPORTED_LOCALES else "en",
        "policy_version": MEMORY_POLICY_VERSION,
        "consent": {
            "granted": True,
            "granted_at": current_time.isoformat(),
            "policy_version": MEMORY_POLICY_VERSION,
        },
    }
    await store.aput(HOUSEHOLD_NAMESPACE, code, record)
    logger.info("Saved household memory (%d approved facts)", len(profile.facts))


def _utc_now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Memory timestamps must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _persistent_profile(
    profile: HouseholdProfile,
    registry: FactRegistry,
) -> HouseholdProfile:
    """Keep only known facts with approved, non-highly-sensitive policies."""

    facts: dict[str, FactState] = {}
    for fact_id, state in profile.facts.items():
        definition = registry.get(fact_id)
        privacy = definition.privacy
        if (
            state.status == "known"
            and definition.definition_review_status == "approved"
            and privacy.review_status == "approved"
            and privacy.sensitivity != "highly_sensitive"
        ):
            facts[fact_id] = state
    return HouseholdProfile(
        registry_version=registry.registry_version,
        facts=facts,
    ).validate_against(registry)


def _record_is_active(record: object, now: datetime) -> bool:
    if not isinstance(record, dict):
        return False
    consent = record.get("consent")
    if (
        record.get("policy_version") != MEMORY_POLICY_VERSION
        or not isinstance(consent, dict)
        or consent.get("granted") is not True
        or consent.get("policy_version") != MEMORY_POLICY_VERSION
    ):
        return False
    expires_at = record.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        return False
    return expiry.astimezone(timezone.utc) > now


async def _active_record(
    store: BaseStore,
    return_code: str,
    now: datetime,
) -> Item | None:
    item = await store.aget(HOUSEHOLD_NAMESPACE, return_code)
    if item is None:
        return None
    if not _record_is_active(item.value, now):
        await store.adelete(HOUSEHOLD_NAMESPACE, return_code)
        return None
    return item


async def load_household(
    store: BaseStore,
    return_code: str,
    registry: FactRegistry,
    *,
    now: datetime | None = None,
) -> HouseholdProfile | None:
    """Load a saved household profile by return code.

    Returns:
        The validated profile, or ``None`` when the code is unknown or the
        saved data cannot be loaded against the current registry (e.g. after
        a registry upgrade that removed a fact).
    """

    code = normalize_return_code(return_code)
    item = await _active_record(store, code, _utc_now(now))
    if item is None:
        return None
    try:
        wire_data = item.value.get("typed_facts")
        if wire_data is None:
            raise ValueError("Saved profile has no fact payload.")
        profile = HouseholdProfile.from_wire(wire_data, registry)
        fact_ids = item.value.get("fact_ids")
        if not isinstance(fact_ids, list) or fact_ids != sorted(profile.facts):
            raise ValueError("Saved profile fact IDs do not match its payload.")
        if set(_persistent_profile(profile, registry).facts) != set(profile.facts):
            raise ValueError("Saved profile contains disallowed facts.")
        return profile
    except (KeyError, TypeError, ValueError) as error:
        await store.adelete(HOUSEHOLD_NAMESPACE, code)
        logger.warning("Discarded an invalid household memory record: %s", error)
        return None


async def load_household_locale(
    store: BaseStore,
    return_code: str,
    *,
    now: datetime | None = None,
) -> str | None:
    """Read the locale saved alongside a household profile."""

    code = normalize_return_code(return_code)
    item = await _active_record(store, code, _utc_now(now))
    if item is None:
        return None
    locale = item.value.get("locale")
    return locale if locale in SUPPORTED_LOCALES else "en"


async def delete_household(store: BaseStore, return_code: str) -> bool:
    """Remove a household record.  Returns whether one existed."""

    code = normalize_return_code(return_code)
    existing = await store.aget(HOUSEHOLD_NAMESPACE, code)
    if existing is None:
        return False
    await store.adelete(HOUSEHOLD_NAMESPACE, code)
    return True
