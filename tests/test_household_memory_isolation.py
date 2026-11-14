"""Offline cross-household isolation tests for household memory (synthetic data only)."""

import asyncio
from datetime import datetime, timedelta, timezone

from langgraph.store.memory import InMemoryStore

from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactState, HouseholdProfile
from src.workflow.household_memory import (
    HOUSEHOLD_TTL_DAYS,
    delete_household,
    load_household,
    save_household,
)

REGISTRY = RulePackageProvider().registry
CODE_A = "SAATHI-AB12CD34EF"
CODE_B = "SAATHI-CD34GH56JK"
NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


def _profile(bpl: bool, income_tax: bool) -> HouseholdProfile:
    facts = {}
    for fact_id, value in {
        "bpl_card_shown": bpl,
        "income_tax_paid_last_assessment_year": income_tax,
    }.items():
        definition = REGISTRY.get(fact_id)
        facts[fact_id] = FactState(
            status="known",
            value=definition.validate_value(value),
            definition_version=definition.version,
            provenance="user_reported",
        )
    return HouseholdProfile(registry_version=REGISTRY.registry_version, facts=facts)


def _save(store, code, profile, now=NOW):
    asyncio.run(save_household(
        store, code, profile, REGISTRY, memory_consent=True, now=now,
    ))


def _load(store, code, now=NOW):
    return asyncio.run(load_household(store, code, REGISTRY, now=now))


def _values(profile):
    return {fid: state.value for fid, state in profile.facts.items()}


def test_consented_memory_is_not_returned_for_a_different_return_code():
    store = InMemoryStore()
    _save(store, CODE_A, _profile(bpl=True, income_tax=False))

    assert _load(store, CODE_B) is None
    assert _load(store, CODE_A) is not None


def test_correction_for_household_a_never_changes_household_b():
    store = InMemoryStore()
    original_b = _profile(bpl=False, income_tax=True)
    _save(store, CODE_A, _profile(bpl=True, income_tax=False))
    _save(store, CODE_B, original_b)

    # Correct household A's income-tax answer (False -> True).
    _save(store, CODE_A, _profile(bpl=True, income_tax=True))

    loaded_a = _load(store, CODE_A)
    loaded_b = _load(store, CODE_B)
    assert _values(loaded_a)["income_tax_paid_last_assessment_year"] is True
    assert _values(loaded_b) == _values(original_b)


def test_forget_for_household_a_leaves_household_b_intact():
    store = InMemoryStore()
    profile_b = _profile(bpl=False, income_tax=True)
    _save(store, CODE_A, _profile(bpl=True, income_tax=False))
    _save(store, CODE_B, profile_b)

    assert asyncio.run(delete_household(store, CODE_A)) is True

    assert _load(store, CODE_A) is None
    loaded_b = _load(store, CODE_B)
    assert loaded_b is not None
    assert _values(loaded_b) == _values(profile_b)


def test_expired_record_for_household_a_is_not_reused():
    store = InMemoryStore()
    _save(store, CODE_A, _profile(bpl=True, income_tax=False), now=NOW)
    _save(store, CODE_B, _profile(bpl=False, income_tax=True), now=NOW + timedelta(days=HOUSEHOLD_TTL_DAYS - 1))

    after_expiry = NOW + timedelta(days=HOUSEHOLD_TTL_DAYS)
    assert _load(store, CODE_A, now=after_expiry) is None
    # Household B, saved one day later, is still active at the same instant.
    assert _load(store, CODE_B, now=after_expiry) is not None
