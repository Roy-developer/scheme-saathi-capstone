"""Choose which profile fact the intake agent should ask about next.

This is plain code with no LLM, so the same profile always gives the same
next question.
"""

from collections import Counter
from collections.abc import Sequence

from src.api.eligibility import APY_HISTORICAL_DATE_REASON, evaluate_mock_eligibility
from src.rules.facts import FactRegistry, HouseholdProfile
from src.rules.models import RulePackage


def pick_next_registered_fact(
    store: HouseholdProfile,
    package: RulePackage,
    registry: FactRegistry,
    skipped_facts: frozenset[str] = frozenset(),
) -> str | None:
    """Choose the first unresolved registry fact needed by an undecided rule."""

    verdict = evaluate_mock_eligibility(store, package, registry=registry)
    if verdict.reason == APY_HISTORICAL_DATE_REASON:
        return None
    if not verdict.deciding_rule_ids and verdict.missing_fields == ["application_date"]:
        return "application_date" if "application_date" not in skipped_facts else None
    if verdict.result != "need_more_information":
        return None
    for rule in package.rules:
        for fact_id in store.missing_inputs(rule.field, registry):
            if fact_id not in skipped_facts:
                return fact_id
    return None


def pick_shared_registered_fact(
    store: HouseholdProfile,
    packages: Sequence[RulePackage],
    registry: FactRegistry,
    skipped_facts: frozenset[str] = frozenset(),
) -> str | None:
    """Prefer a registered input shared by the most unresolved schemes.

    Only identical IDs in the same pinned registry share an answer. Candidate,
    rule and derived-input order break ties; similar question labels do not.
    """

    counts: Counter[str] = Counter()
    for package in packages:
        verdict = evaluate_mock_eligibility(store, package, registry=registry)
        if verdict.reason == APY_HISTORICAL_DATE_REASON:
            continue
        if not verdict.deciding_rule_ids and verdict.missing_fields == ["application_date"]:
            if "application_date" not in skipped_facts:
                counts.update(["application_date"])
            continue
        if verdict.result == "not_eligible":
            continue
        if verdict.result == "need_more_information":
            counts.update(dict.fromkeys(
                fact_id for rule in package.rules
                for fact_id in store.missing_inputs(rule.field, registry)
                if fact_id not in skipped_facts
            ).keys())
        counts.update(
            fact_id
            for fact_id in package.required_facts
            if fact_id not in store.facts and fact_id not in skipped_facts
        )
    return max(counts, key=counts.get) if counts else None
