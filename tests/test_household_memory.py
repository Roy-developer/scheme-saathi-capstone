"""Tests for the household memory module — return codes and cross-session fact persistence."""

import asyncio

import pytest
from langgraph.store.memory import InMemoryStore

from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactRegistry, FactState, HouseholdProfile
from src.workflow.household_memory import (
    CODE_ALPHABET,
    CODE_PREFIX,
    CODE_RANDOM_LENGTH,
    HOUSEHOLD_NAMESPACE,
    MIN_FACTS_TO_SAVE,
    delete_household,
    generate_return_code,
    load_household,
    load_household_locale,
    normalize_return_code,
    save_household,
)


REGISTRY = RulePackageProvider().registry


def _build_profile(known_facts: dict[str, object]) -> HouseholdProfile:
    """Build a minimal profile with the given known facts."""

    facts = {}
    for fact_id, value in known_facts.items():
        definition = REGISTRY.get(fact_id)
        facts[fact_id] = FactState(
            status="known",
            value=definition.validate_value(value),
            definition_version=definition.version,
            provenance="user_reported",
        )
    return HouseholdProfile(
        registry_version=REGISTRY.registry_version, facts=facts,
    )


class TestReturnCodeGeneration:
    """Return codes are short, human-friendly, and collision-resistant."""

    def test_format(self):
        code = generate_return_code()
        assert code.startswith(f"{CODE_PREFIX}-")
        suffix = code[len(CODE_PREFIX) + 1:]
        assert len(suffix) == CODE_RANDOM_LENGTH
        assert all(character in CODE_ALPHABET for character in suffix)

    def test_uniqueness(self):
        codes = {generate_return_code() for _ in range(100)}
        assert len(codes) == 100

    def test_normalize_valid(self):
        assert normalize_return_code("saathi-ab12") == "SAATHI-AB12"
        assert normalize_return_code("  SAATHI-XY9Z  ") == "SAATHI-XY9Z"

    def test_normalize_rejects_bad_format(self):
        with pytest.raises(ValueError, match="format"):
            normalize_return_code("WRONG-CODE")

    def test_normalize_rejects_bad_characters(self):
        with pytest.raises(ValueError, match="invalid characters"):
            normalize_return_code("SAATHI-AB!@")

    def test_normalize_rejects_wrong_length(self):
        with pytest.raises(ValueError, match="format"):
            normalize_return_code("SAATHI-ABCDE")


class TestSaveAndLoad:
    """Household profiles round-trip through the store."""

    @pytest.fixture
    def store(self):
        return InMemoryStore()

    @pytest.fixture
    def profile(self):
        return _build_profile({
            "is_widow": True,
            "bpl_card_shown": True,
            "income_tax_paid_last_assessment_year": False,
        })

    def test_save_and_load_round_trip(self, store, profile):
        code = generate_return_code()
        asyncio.run(save_household(store, code, profile, REGISTRY, "hi"))
        loaded = asyncio.run(load_household(store, code, REGISTRY))
        assert loaded is not None
        assert set(loaded.facts.keys()) == set(profile.facts.keys())
        for fact_id in profile.facts:
            assert loaded.facts[fact_id].value == profile.facts[fact_id].value

    def test_load_preserves_locale(self, store, profile):
        code = generate_return_code()
        asyncio.run(save_household(store, code, profile, REGISTRY, "mr"))
        locale = asyncio.run(load_household_locale(store, code))
        assert locale == "mr"

    def test_load_unknown_code_returns_none(self, store):
        loaded = asyncio.run(load_household(store, "SAATHI-ZZZZ", REGISTRY))
        assert loaded is None

    def test_skip_save_when_too_few_facts(self, store):
        profile = _build_profile({"is_widow": True})
        code = generate_return_code()
        asyncio.run(save_household(store, code, profile, REGISTRY))
        loaded = asyncio.run(load_household(store, code, REGISTRY))
        assert loaded is None

    def test_update_existing_preserves_created_at(self, store, profile):
        code = generate_return_code()
        asyncio.run(save_household(store, code, profile, REGISTRY))
        item_before = asyncio.run(store.aget(HOUSEHOLD_NAMESPACE, code))
        created = item_before.value["created_at"]
        updated_profile = _build_profile({
            "is_widow": False,
            "bpl_card_shown": True,
            "income_tax_paid_last_assessment_year": False,
        })
        asyncio.run(save_household(store, code, updated_profile, REGISTRY))
        item_after = asyncio.run(store.aget(HOUSEHOLD_NAMESPACE, code))
        assert item_after.value["created_at"] == created
        assert item_after.value["updated_at"] >= created

    def test_delete_household(self, store, profile):
        code = generate_return_code()
        asyncio.run(save_household(store, code, profile, REGISTRY))
        deleted = asyncio.run(delete_household(store, code))
        assert deleted is True
        loaded = asyncio.run(load_household(store, code, REGISTRY))
        assert loaded is None

    def test_delete_unknown_returns_false(self, store):
        deleted = asyncio.run(delete_household(store, "SAATHI-ZZZZ"))
        assert deleted is False


class TestReturnCodeInJourneyRequest:
    """JourneyRequest accepts and passes the return_code field."""

    def test_request_accepts_return_code(self):
        from src.workflow.journey import JourneyRequest
        request = JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
            return_code="SAATHI-AB12",
        )
        assert request.return_code == "SAATHI-AB12"

    def test_request_default_none(self):
        from src.workflow.journey import JourneyRequest
        request = JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
        )
        assert request.return_code is None


class TestReturnCodeInJourneyResponse:
    """JourneyResponse includes the return_code field."""

    def test_response_accepts_return_code(self):
        from src.workflow.journey import JourneyResponse
        response = JourneyResponse(
            conversation_id="00000000-0000-0000-0000-000000000000",
            plan="",
            status="awaiting_answer",
            message="",
            return_code="SAATHI-XY9Z",
        )
        assert response.return_code == "SAATHI-XY9Z"

    def test_response_default_none(self):
        from src.workflow.journey import JourneyResponse
        response = JourneyResponse(
            conversation_id="00000000-0000-0000-0000-000000000000",
            plan="",
            status="awaiting_answer",
            message="",
        )
        assert response.return_code is None
