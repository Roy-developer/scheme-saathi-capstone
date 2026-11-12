"""Tests for the household memory module — return codes and cross-session fact persistence."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from langgraph.store.memory import InMemoryStore

from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactRegistry, FactState, HouseholdProfile
from src.workflow.household_memory import (
    CODE_ALPHABET,
    CODE_PREFIX,
    CODE_RANDOM_LENGTH,
    HOUSEHOLD_NAMESPACE,
    HOUSEHOLD_TTL_DAYS,
    MEMORY_POLICY_VERSION,
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
        asyncio.run(save_household(
            store, code, profile, REGISTRY, "hi", memory_consent=True,
        ))
        loaded = asyncio.run(load_household(store, code, REGISTRY))
        assert loaded is not None
        assert set(loaded.facts) == {
            "bpl_card_shown",
            "income_tax_paid_last_assessment_year",
        }
        for fact_id in loaded.facts:
            assert loaded.facts[fact_id].value == profile.facts[fact_id].value

    def test_load_preserves_locale(self, store, profile):
        code = generate_return_code()
        asyncio.run(save_household(
            store, code, profile, REGISTRY, "mr", memory_consent=True,
        ))
        locale = asyncio.run(load_household_locale(store, code))
        assert locale == "mr"

    def test_return_codes_are_isolated(self, store):
        first_code = "SAATHI-AB12"
        second_code = "SAATHI-CD34"
        asyncio.run(save_household(
            store,
            first_code,
            _build_profile({
                "bpl_card_shown": True,
                "income_tax_paid_last_assessment_year": False,
            }),
            REGISTRY,
            memory_consent=True,
        ))
        asyncio.run(save_household(
            store,
            second_code,
            _build_profile({
                "bpl_card_shown": False,
                "income_tax_paid_last_assessment_year": True,
            }),
            REGISTRY,
            memory_consent=True,
        ))

        first = asyncio.run(load_household(store, first_code, REGISTRY))
        second = asyncio.run(load_household(store, second_code, REGISTRY))

        assert first is not None and second is not None
        assert first.facts["bpl_card_shown"].value is True
        assert second.facts["bpl_card_shown"].value is False
        assert first.facts["income_tax_paid_last_assessment_year"].value is False
        assert second.facts["income_tax_paid_last_assessment_year"].value is True

    def test_load_unknown_code_returns_none(self, store):
        loaded = asyncio.run(load_household(store, "SAATHI-ZZZZ", REGISTRY))
        assert loaded is None

    def test_skip_save_when_too_few_facts(self, store):
        profile = _build_profile({"is_widow": True})
        code = generate_return_code()
        with pytest.raises(ValueError, match="privacy-approved"):
            asyncio.run(save_household(
                store, code, profile, REGISTRY, memory_consent=True,
            ))

    def test_update_existing_preserves_created_at(self, store, profile):
        code = generate_return_code()
        asyncio.run(save_household(
            store, code, profile, REGISTRY, memory_consent=True,
        ))
        item_before = asyncio.run(store.aget(HOUSEHOLD_NAMESPACE, code))
        created = item_before.value["created_at"]
        updated_profile = _build_profile({
            "is_widow": False,
            "bpl_card_shown": True,
            "income_tax_paid_last_assessment_year": True,
        })
        asyncio.run(save_household(
            store,
            code,
            updated_profile,
            REGISTRY,
            memory_consent=True,
        ))
        item_after = asyncio.run(store.aget(HOUSEHOLD_NAMESPACE, code))
        assert item_after.value["created_at"] == created
        assert item_after.value["updated_at"] >= created
        loaded = asyncio.run(load_household(store, code, REGISTRY))
        assert loaded is not None
        assert loaded.facts["bpl_card_shown"].value is True
        assert loaded.facts["income_tax_paid_last_assessment_year"].value is True

    def test_delete_household(self, store, profile):
        code = generate_return_code()
        asyncio.run(save_household(
            store, code, profile, REGISTRY, memory_consent=True,
        ))
        deleted = asyncio.run(delete_household(store, code))
        assert deleted is True
        loaded = asyncio.run(load_household(store, code, REGISTRY))
        assert loaded is None

    def test_delete_unknown_returns_false(self, store):
        deleted = asyncio.run(delete_household(store, "SAATHI-ZZZZ"))
        assert deleted is False

    def test_save_requires_explicit_consent(self, store, profile):
        with pytest.raises(ValueError, match="Explicit memory consent"):
            asyncio.run(save_household(
                store,
                generate_return_code(),
                profile,
                REGISTRY,
                memory_consent=False,
            ))

    def test_record_has_versioned_consent_fact_ids_and_expiry(self, store, profile):
        now = datetime(2026, 11, 12, tzinfo=timezone.utc)
        code = generate_return_code()
        asyncio.run(save_household(
            store,
            code,
            profile,
            REGISTRY,
            memory_consent=True,
            now=now,
        ))
        item = asyncio.run(store.aget(HOUSEHOLD_NAMESPACE, code))

        assert item.value["policy_version"] == MEMORY_POLICY_VERSION
        assert item.value["consent"] == {
            "granted": True,
            "granted_at": now.isoformat(),
            "policy_version": MEMORY_POLICY_VERSION,
        }
        assert item.value["fact_ids"] == [
            "bpl_card_shown",
            "income_tax_paid_last_assessment_year",
        ]
        assert datetime.fromisoformat(item.value["expires_at"]) == (
            now + timedelta(days=HOUSEHOLD_TTL_DAYS)
        )

    def test_expired_record_is_deleted_on_load(self, store, profile):
        now = datetime(2026, 11, 12, tzinfo=timezone.utc)
        code = generate_return_code()
        asyncio.run(save_household(
            store,
            code,
            profile,
            REGISTRY,
            memory_consent=True,
            now=now,
        ))

        loaded = asyncio.run(load_household(
            store,
            code,
            REGISTRY,
            now=now + timedelta(days=HOUSEHOLD_TTL_DAYS),
        ))

        assert loaded is None
        assert asyncio.run(store.aget(HOUSEHOLD_NAMESPACE, code)) is None

    def test_legacy_record_without_consent_or_expiry_is_deleted(self, store, profile):
        code = generate_return_code()
        asyncio.run(store.aput(
            HOUSEHOLD_NAMESPACE,
            code,
            {
                "typed_facts": profile.to_wire(REGISTRY),
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "locale": "en",
            },
        ))

        loaded = asyncio.run(load_household(store, code, REGISTRY))

        assert loaded is None
        assert asyncio.run(store.aget(HOUSEHOLD_NAMESPACE, code)) is None

    def test_unreviewed_facts_are_not_persisted(self, store):
        profile = _build_profile({
            "bpl_card_shown": True,
            "income_tax_paid_last_assessment_year": False,
            "apy_is_citizen_of_india": True,
        })
        code = generate_return_code()
        asyncio.run(save_household(
            store, code, profile, REGISTRY, memory_consent=True,
        ))

        loaded = asyncio.run(load_household(store, code, REGISTRY))

        assert loaded is not None
        assert set(loaded.facts) == {
            "bpl_card_shown",
            "income_tax_paid_last_assessment_year",
        }


class TestReturnCodeInJourneyRequest:
    """JourneyRequest accepts and passes the return_code field."""

    def test_request_accepts_return_code(self):
        from src.workflow.journey import JourneyRequest
        request = JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
            return_code="SAATHI-AB12",
            memory_consent=True,
        )
        assert request.return_code == "SAATHI-AB12"

    def test_request_rejects_return_code_without_memory_consent(self):
        from src.workflow.journey import JourneyRequest

        with pytest.raises(ValueError, match="Loading household memory"):
            JourneyRequest(
                action="interview",
                scheme_id="IGNWPS-MH",
                return_code="SAATHI-AB12",
            )

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
