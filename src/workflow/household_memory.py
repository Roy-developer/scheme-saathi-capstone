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
from datetime import datetime, timezone

from langgraph.store.base import BaseStore

from src.rules.facts import FactRegistry, HouseholdProfile

logger = logging.getLogger(__name__)

HOUSEHOLD_NAMESPACE = ("household",)

CODE_PREFIX = "SAATHI"
CODE_RANDOM_LENGTH = 4
CODE_ALPHABET = string.ascii_uppercase + string.digits
MIN_FACTS_TO_SAVE = 2


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
) -> None:
    """Persist the household's typed facts under their return code.

    Only saves when the profile has at least ``MIN_FACTS_TO_SAVE`` known facts,
    to avoid storing nearly empty profiles.
    """

    known_count = sum(
        1 for state in profile.facts.values() if state.status == "known"
    )
    if known_count < MIN_FACTS_TO_SAVE:
        logger.debug(
            "Skipping household save: only %d known fact(s)", known_count,
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    existing = await store.aget(HOUSEHOLD_NAMESPACE, return_code)
    record: dict[str, object] = {
        "typed_facts": profile.to_wire(registry),
        "created_at": existing.value["created_at"] if existing else now,
        "updated_at": now,
        "locale": locale,
    }
    await store.aput(HOUSEHOLD_NAMESPACE, return_code, record)
    logger.info("Saved household profile under %s (%d facts)", return_code, known_count)


async def load_household(
    store: BaseStore,
    return_code: str,
    registry: FactRegistry,
) -> HouseholdProfile | None:
    """Load a saved household profile by return code.

    Returns:
        The validated profile, or ``None`` when the code is unknown or the
        saved data cannot be loaded against the current registry (e.g. after
        a registry upgrade that removed a fact).
    """

    code = normalize_return_code(return_code)
    item = await store.aget(HOUSEHOLD_NAMESPACE, code)
    if item is None:
        return None
    try:
        wire_data = item.value.get("typed_facts")
        if wire_data is None:
            return None
        return HouseholdProfile.from_wire(wire_data, registry)
    except (KeyError, TypeError, ValueError) as error:
        logger.warning(
            "Could not restore household %s: %s", code, error,
        )
        return None


async def load_household_locale(
    store: BaseStore,
    return_code: str,
) -> str | None:
    """Read the locale saved alongside a household profile."""

    code = normalize_return_code(return_code)
    item = await store.aget(HOUSEHOLD_NAMESPACE, code)
    if item is None:
        return None
    return item.value.get("locale")


async def delete_household(store: BaseStore, return_code: str) -> bool:
    """Remove a household record.  Returns whether one existed."""

    code = normalize_return_code(return_code)
    existing = await store.aget(HOUSEHOLD_NAMESPACE, code)
    if existing is None:
        return False
    await store.adelete(HOUSEHOLD_NAMESPACE, code)
    return True
