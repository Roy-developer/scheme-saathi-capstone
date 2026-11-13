"""Synthetic development memory-on/off runner (no model calls).

Runs the real journey graph and the real household memory store for each
synthetic case. Every metric is computed from those runs; nothing is
hard-coded. The report is labelled synthetic and development only.

Metrics per case:
- questions_asked_on / questions_asked_off: interview questions asked on the
  return visit with and without memory.
- fact_reuse: reusable facts known on the memory-on return visit / facts saved.
- verdict_match: memory-on verdict equals memory-off verdict.
- correction_visible_on_return: a corrected value saved before the return
  visit is the value the store hands back (None when the case has no
  correction).
- policy_violations: disallowed facts (non-approved, highly sensitive, or
  unreviewed) found in a stored record or reused on a return visit.
- cross_household_leaks: values of the case household that differ from the
  saved truth, plus facts reused by a return code that was never saved.
- forget_completeness: share of forget checks passed (record gone, load
  returns nothing, return visit reuses nothing, other household intact).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.store.base import BaseStore

from eval.harness.household_memory import (
    SCHEME_ID,
    _build_graph,
    _finish,
    write_report,
)
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactRegistry, FactState, HouseholdProfile
from src.workflow.household_memory import (
    HOUSEHOLD_NAMESPACE,
    delete_household,
    load_household,
    save_household,
)
from src.workflow.journey import JourneyRequest, run_journey

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = PROJECT_ROOT / "eval" / "reports" / "memory_on_off_dev_latest.json"

CODE_A = "SAATHI-AB12"
CODE_B = "SAATHI-CD34"
CODE_UNSAVED = "SAATHI-ZZ99"
CODE_POLICY = "SAATHI-PQ56"
REUSABLE_FACTS = ("bpl_card_shown", "income_tax_paid_last_assessment_year")
POLICY_PROBE_FACTS = ("has_disability", "date_of_birth")
FORGET_CHECKS = 4


@dataclass(frozen=True)
class SyntheticCase:
    case_id: str
    description: str
    saved: dict[str, bool]
    is_widow: bool
    date_of_birth: str
    correction: dict[str, bool] = field(default_factory=dict)
    other_household: dict[str, bool] | None = None


CASES: tuple[SyntheticCase, ...] = (
    SyntheticCase(
        "SYN-MEMORY-001", "Consented return, BPL yes, no income tax",
        {"bpl_card_shown": True, "income_tax_paid_last_assessment_year": False},
        is_widow=True, date_of_birth="01/01/1986",
    ),
    SyntheticCase(
        "SYN-MEMORY-002", "Consented return, BPL no, no income tax",
        {"bpl_card_shown": False, "income_tax_paid_last_assessment_year": False},
        is_widow=True, date_of_birth="01/01/1986",
    ),
    SyntheticCase(
        "SYN-MEMORY-003", "Consented return, income tax paid",
        {"bpl_card_shown": True, "income_tax_paid_last_assessment_year": True},
        is_widow=True, date_of_birth="01/01/1986",
    ),
    SyntheticCase(
        "SYN-MEMORY-004", "Consented return, not widow, age over threshold",
        {"bpl_card_shown": True, "income_tax_paid_last_assessment_year": False},
        is_widow=False, date_of_birth="01/01/1970",
    ),
    SyntheticCase(
        "SYN-MEMORY-005", "Income-tax answer corrected before return",
        {"bpl_card_shown": True, "income_tax_paid_last_assessment_year": False},
        is_widow=True, date_of_birth="01/01/1986",
        correction={"income_tax_paid_last_assessment_year": True},
    ),
    SyntheticCase(
        "SYN-MEMORY-006", "BPL answer corrected before return",
        {"bpl_card_shown": False, "income_tax_paid_last_assessment_year": True},
        is_widow=True, date_of_birth="01/01/1986",
        correction={"bpl_card_shown": True},
    ),
    SyntheticCase(
        "SYN-MEMORY-007", "Second synthetic household saved with opposite answers",
        {"bpl_card_shown": True, "income_tax_paid_last_assessment_year": False},
        is_widow=True, date_of_birth="01/01/1986",
        other_household={"bpl_card_shown": False, "income_tax_paid_last_assessment_year": True},
    ),
)


def _facts(registry: FactRegistry, values: dict[str, Any]) -> dict[str, FactState]:
    facts: dict[str, FactState] = {}
    for fact_id, value in values.items():
        definition = registry.get(fact_id)
        facts[fact_id] = FactState(
            status="known",
            value=definition.validate_value(value),
            definition_version=definition.version,
            provenance="user_reported",
        )
    return facts


def _profile(registry: FactRegistry, values: dict[str, Any]) -> HouseholdProfile:
    return HouseholdProfile(
        registry_version=registry.registry_version,
        facts=_facts(registry, values),
    )


def _is_policy_allowed(registry: FactRegistry, fact_id: str) -> bool:
    definition = registry.get(fact_id)
    return (
        definition.definition_review_status == "approved"
        and definition.privacy.review_status == "approved"
        and definition.privacy.sensitivity != "highly_sensitive"
    )


def _answers(case: SyntheticCase, truth: dict[str, bool]) -> dict[str, str]:
    answers = {
        "is_widow": "yes" if case.is_widow else "no",
        "date_of_birth": case.date_of_birth,
    }
    for fact_id in REUSABLE_FACTS:
        answers[fact_id] = "yes" if truth[fact_id] else "no"
    return answers


async def _stored_fact_ids(store: BaseStore, code: str) -> list[str]:
    item = await store.aget(HOUSEHOLD_NAMESPACE, code)
    if item is None or not isinstance(item.value, dict):
        return []
    return list(item.value.get("fact_ids", []))


async def _run_case(provider: RulePackageProvider, case: SyntheticCase) -> dict[str, Any]:
    registry = provider.registry
    graph = _build_graph(provider)
    store = graph.store

    # Visit 1: save consented facts, then apply any correction before return.
    await save_household(store, CODE_A, _profile(registry, case.saved), registry, memory_consent=True)
    truth = dict(case.saved)
    if case.correction:
        truth.update(case.correction)
        await save_household(
            store, CODE_A, _profile(registry, truth), registry, memory_consent=True,
        )
    if case.other_household is not None:
        await save_household(
            store, CODE_B, _profile(registry, case.other_household), registry, memory_consent=True,
        )
    answers = _answers(case, truth)
    saved_reusable = [f for f in REUSABLE_FACTS if f in truth]

    # Return visit with memory on, then the same journey with memory off.
    on_final, on_asked, on_start = await _return_visit_with_code(graph, CODE_A, answers, case)
    off_final, off_asked = await _finish(
        graph,
        await run_journey(graph, JourneyRequest(
            action="interview", scheme_id=SCHEME_ID,
            profile={"application_date": date(2026, 11, 12).isoformat()},
        )),
        answers,
    )
    on_known = set(on_final.known_fact_names)
    # Reuse means memory supplied the fact before any answer was given this visit.
    reused = [f for f in saved_reusable if f in on_start]
    correction_visible = None
    if case.correction:
        loaded = await load_household(store, CODE_A, registry)
        correction_visible = all(
            loaded is not None
            and loaded.facts[f].value == truth[f]
            for f in case.correction
        ) and all(f in on_known for f in case.correction)

    # Leaks: wrong values for this household, and reuse under a never-saved code.
    loaded_a = await load_household(store, CODE_A, registry)
    value_leaks = 0
    if loaded_a is None:
        value_leaks += len(saved_reusable)
    else:
        value_leaks += sum(
            1 for f in saved_reusable
            if f not in loaded_a.facts or loaded_a.facts[f].value != truth[f]
        )
    _, _, stranger_start = await _return_visit_with_code(graph, CODE_UNSAVED, answers, case)
    stranger_leaks = len(stranger_start & set(REUSABLE_FACTS))
    cross_household_leaks = value_leaks + stranger_leaks

    # Policy: store an out-of-policy profile and confirm it is filtered out.
    policy_values = {**case.saved, "has_disability": True, "date_of_birth": "1986-01-01"}
    policy_profile = _profile(registry, policy_values)
    attempted = [f for f in policy_profile.facts if not _is_policy_allowed(registry, f)]
    await save_household(store, CODE_POLICY, policy_profile, registry, memory_consent=True)
    stored_policy = await _stored_fact_ids(store, CODE_POLICY)
    _, _, policy_start = await _return_visit_with_code(graph, CODE_POLICY, answers, case)
    reused_disallowed = policy_start & set(POLICY_PROBE_FACTS)
    policy_violations = (
        sum(1 for f in stored_policy if not _is_policy_allowed(registry, f))
        + len(reused_disallowed)
    )

    # Forget: remove the household, then check every forget claim.
    removed = await delete_household(store, CODE_A)
    _, _, forget_start = await _return_visit_with_code(graph, CODE_A, answers, case)
    other_intact = True
    if case.other_household is not None:
        loaded_b = await load_household(store, CODE_B, registry)
        other_intact = loaded_b is not None and all(
            loaded_b.facts[f].value == case.other_household[f] for f in case.other_household
        )
    forget_checks = [
        removed and await store.aget(HOUSEHOLD_NAMESPACE, CODE_A) is None,
        await load_household(store, CODE_A, registry) is None,
        not (forget_start & set(REUSABLE_FACTS)),
        other_intact,
    ]
    forget_completeness = sum(forget_checks) / FORGET_CHECKS

    return {
        "case_id": case.case_id,
        "description": case.description,
        "scheme_id": SCHEME_ID,
        "questions_asked_on": len(on_asked),
        "questions_asked_off": len(off_asked),
        "questions_avoided": len(off_asked) - len(on_asked),
        "fact_reuse_on_return": {
            "reused": len(reused),
            "saved": len(saved_reusable),
            "rate": len(reused) / len(saved_reusable) if saved_reusable else 0.0,
        },
        "verdict_on": on_final.eligibility_result.result,
        "verdict_off": off_final.eligibility_result.result,
        "verdict_match": on_final.eligibility_result.result == off_final.eligibility_result.result,
        "correction_visible_on_return": correction_visible,
        "policy_violations": policy_violations,
        "policy_probe": {
            "attempted_disallowed": sorted(attempted),
            "stored_fact_ids": sorted(stored_policy),
        },
        "cross_household_leaks": cross_household_leaks,
        "forget_completeness": forget_completeness,
    }


async def _return_visit_with_code(
    graph: Any,
    code: str,
    answers: dict[str, str],
    case: SyntheticCase,
) -> tuple[Any, list[str], set[str]]:
    """Return the final state, questions asked, and facts known before any answer."""

    profile = {"application_date": date(2026, 11, 12).isoformat()}
    start = await run_journey(graph, JourneyRequest(
        action="interview", scheme_id=SCHEME_ID, profile=profile,
        return_code=code, memory_consent=True,
    ))
    known_at_start = set(start.known_fact_names)
    final, asked = await _finish(graph, start, answers)
    return final, asked, known_at_start


def _summarise(cases: list[dict[str, Any]]) -> dict[str, Any]:
    corrections = [c["correction_visible_on_return"] for c in cases if c["correction_visible_on_return"] is not None]
    total = len(cases)
    return {
        "case_count": total,
        "verdict_match_count": sum(c["verdict_match"] for c in cases),
        "verdict_match_rate": sum(c["verdict_match"] for c in cases) / total,
        "questions_asked_on_total": sum(c["questions_asked_on"] for c in cases),
        "questions_asked_off_total": sum(c["questions_asked_off"] for c in cases),
        "questions_avoided_total": sum(c["questions_avoided"] for c in cases),
        "fact_reuse_rate_mean": sum(c["fact_reuse_on_return"]["rate"] for c in cases) / total,
        "correction_case_count": len(corrections),
        "correction_visible_count": sum(bool(v) for v in corrections),
        "policy_violations_total": sum(c["policy_violations"] for c in cases),
        "cross_household_leaks_total": sum(c["cross_household_leaks"] for c in cases),
        "forget_completeness_mean": sum(c["forget_completeness"] for c in cases) / total,
    }


def memory_on_off_dev_report() -> dict[str, Any]:
    provider = RulePackageProvider()
    cases = [asyncio.run(_run_case(provider, case)) for case in CASES]
    return {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": "SYNTHETIC - DEVELOPMENT ONLY",
        "split": "development",
        "model_calls": 0,
        "case_count": len(cases),
        "cases": cases,
        "summary": _summarise(cases),
        "claim_boundary": (
            "Synthetic development cases run through the real journey graph and "
            "household memory store. Not independent validation, a user study, "
            "a security evaluation, or full L9 evidence."
        ),
    }


if __name__ == "__main__":
    write_report(memory_on_off_dev_report(), REPORT_PATH)
    print(f"Wrote {REPORT_PATH}")
