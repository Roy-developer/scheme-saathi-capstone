"""ASI06: a saved household profile cannot be guessed, hijacked or scanned for.

Synthetic data only. Routes are called directly with a stand-in request so the
tests stay offline.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from langgraph.store.memory import InMemoryStore

import src.api.app as api
from src.api.rate_limit import (
    SlidingWindowLimiter,
    household_failures,
    household_requests,
)
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactState, HouseholdProfile
from src.workflow.household_memory import (
    CODE_ALPHABET,
    CODE_PREFIX,
    CODE_RANDOM_LENGTH,
    HOUSEHOLD_NAMESPACE,
    delete_household,
    generate_return_code,
    load_household,
    normalize_return_code,
    save_household,
)

REGISTRY = RulePackageProvider().registry
OWNER = "00000000-0000-0000-0000-00000000000a"
STRANGER = "00000000-0000-0000-0000-00000000000b"
RETURNING = "00000000-0000-0000-0000-00000000000c"


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


class _Graph:
    """Stands in for the journey graph: one saved state per conversation."""

    def __init__(self, states: dict[str, dict]) -> None:
        self.states = states

    async def aget_state(self, config: dict) -> SimpleNamespace:
        return SimpleNamespace(
            values=self.states.get(config["configurable"]["thread_id"], {}),
        )


def _request(store: InMemoryStore, states: dict[str, dict], host: str = "203.0.113.7"):
    return SimpleNamespace(
        client=SimpleNamespace(host=host),
        app=SimpleNamespace(state=SimpleNamespace(
            journey_store=store,
            journey_graph=_Graph(states),
            fact_registry=REGISTRY,
        )),
    )


def _state(profile: HouseholdProfile, return_code: str | None = None) -> dict:
    state = {"typed_facts": profile.to_wire(REGISTRY), "locale": "en"}
    if return_code:
        state["return_code"] = return_code
    return state


def _save(request, conversation_id: str, return_code: str | None = None) -> dict:
    body = {"conversation_id": conversation_id, "memory_consent": True}
    if return_code:
        body["return_code"] = return_code
    return asyncio.run(api.save_household_profile(body, request))


def _status(call) -> int:
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code


def _stored_values(store, code) -> dict:
    profile = asyncio.run(load_household(store, code, REGISTRY))
    return {fact_id: state.value for fact_id, state in profile.facts.items()}


# -- Codes cannot practically be guessed ---------------------------------------


def test_generated_codes_have_ten_random_characters() -> None:
    codes = {generate_return_code() for _ in range(200)}

    assert len(codes) == 200
    for code in codes:
        prefix, suffix = code.split("-")
        assert prefix == CODE_PREFIX
        assert len(suffix) == CODE_RANDOM_LENGTH == 10
        assert set(suffix) <= set(CODE_ALPHABET)
    assert len(CODE_ALPHABET) ** CODE_RANDOM_LENGTH > 10**15


def test_old_four_character_codes_can_be_forgotten_but_not_loaded_or_saved() -> None:
    legacy = "SAATHI-AB12"
    store = InMemoryStore()
    asyncio.run(store.aput(HOUSEHOLD_NAMESPACE, legacy, {"synthetic": True}))

    with pytest.raises(ValueError):
        normalize_return_code(legacy)
    with pytest.raises(ValueError):
        asyncio.run(load_household(store, legacy, REGISTRY))
    with pytest.raises(ValueError):
        asyncio.run(save_household(
            store, legacy, _profile(True, False), REGISTRY, memory_consent=True,
        ))
    assert asyncio.run(delete_household(store, legacy)) is True
    assert asyncio.run(store.aget(HOUSEHOLD_NAMESPACE, legacy)) is None


# -- Only the server creates a code ---------------------------------------------


def test_a_new_save_gets_a_server_generated_code() -> None:
    store = InMemoryStore()
    request = _request(store, {OWNER: _state(_profile(True, False))})

    code = _save(request, OWNER)["return_code"]

    assert normalize_return_code(code) == code
    assert _stored_values(store, code) == {
        "bpl_card_shown": True, "income_tax_paid_last_assessment_year": False,
    }


def test_a_caller_chosen_code_is_refused_for_a_new_save() -> None:
    store = InMemoryStore()
    request = _request(store, {OWNER: _state(_profile(True, False))})
    chosen = "SAATHI-CH0SENC0DE"

    assert _status(lambda: _save(request, OWNER, chosen)) == 404
    assert asyncio.run(store.aget(HOUSEHOLD_NAMESPACE, chosen)) is None


# -- Only a linked conversation can save over a code ---------------------------


def test_a_stranger_conversation_cannot_overwrite_a_household() -> None:
    store = InMemoryStore()
    states = {
        OWNER: _state(_profile(True, False)),
        STRANGER: _state(_profile(False, True)),
    }
    request = _request(store, states)
    code = _save(request, OWNER)["return_code"]

    assert _status(lambda: _save(request, STRANGER, code)) == 403
    assert _stored_values(store, code) == {
        "bpl_card_shown": True, "income_tax_paid_last_assessment_year": False,
    }


def test_the_conversation_that_created_a_code_can_update_it() -> None:
    store = InMemoryStore()
    states = {OWNER: _state(_profile(True, False))}
    request = _request(store, states)
    code = _save(request, OWNER)["return_code"]

    states[OWNER] = _state(_profile(True, True))
    assert _save(request, OWNER, code) == {"return_code": code}
    assert _stored_values(store, code)["income_tax_paid_last_assessment_year"] is True


def test_a_returning_visit_started_with_the_code_can_update_it() -> None:
    store = InMemoryStore()
    states = {OWNER: _state(_profile(True, False))}
    request = _request(store, states)
    code = _save(request, OWNER)["return_code"]

    states[RETURNING] = _state(_profile(False, False), return_code=code)
    assert _save(request, RETURNING, code) == {"return_code": code}
    assert _stored_values(store, code)["bpl_card_shown"] is False


# -- Scanning for codes is blocked ---------------------------------------------


def test_repeated_unknown_codes_block_the_client_even_for_a_real_code() -> None:
    store = InMemoryStore()
    states = {OWNER: _state(_profile(True, False))}
    code = _save(_request(store, states, host="198.51.100.1"), OWNER)["return_code"]
    scanner = _request(store, states)

    for attempt in range(household_failures.limit):
        guess = f"SAATHI-{attempt:010d}"
        assert _status(lambda: asyncio.run(
            api.get_household(guess, scanner, memory_consent=True)
        )) == 404

    with pytest.raises(HTTPException) as error:
        asyncio.run(api.get_household(code, scanner, memory_consent=True))
    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) >= 1

    # Another client is not affected.
    other = _request(store, states, host="198.51.100.2")
    assert asyncio.run(api.get_household(code, other, memory_consent=True))[
        "return_code"
    ] == code


def test_refused_saves_count_toward_the_scan_limit() -> None:
    store = InMemoryStore()
    request = _request(store, {STRANGER: _state(_profile(False, True))})

    for attempt in range(household_failures.limit):
        assert _status(lambda: _save(request, STRANGER, f"SAATHI-{attempt:010d}")) == 404

    assert _status(lambda: _save(request, STRANGER)) == 429


def test_too_many_household_requests_from_one_client_are_refused() -> None:
    store = InMemoryStore()
    states = {OWNER: _state(_profile(True, False))}
    request = _request(store, states)
    code = _save(request, OWNER)["return_code"]

    for _ in range(household_requests.limit - 1):
        asyncio.run(api.get_household(code, request, memory_consent=True))

    assert _status(lambda: asyncio.run(
        api.get_household(code, request, memory_consent=True)
    )) == 429


def test_sliding_window_limiter_frees_up_after_the_window() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 60, clock=lambda: now[0])

    assert limiter.hit("client") and limiter.hit("client")
    assert not limiter.hit("client")
    assert limiter.blocked("client")
    assert limiter.hit("someone-else")
    now[0] = 60.0
    assert limiter.hit("client")
