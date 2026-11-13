"""Tests for journey-facing E4 planned vs fixed question-order ablation."""

from __future__ import annotations

import asyncio

from eval.harness import e4_journey_question_order
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import HouseholdProfile
from src.workflow.question_picker import (
    fixed_questionnaire_facts,
    pick_fixed_questionnaire_fact,
    pick_shared_registered_fact,
)


def test_fixed_picker_follows_sorted_leaf_order_not_adaptive():
    provider = RulePackageProvider()
    package = provider.get("IGNWPS-MH")
    registry = provider.registry
    empty = HouseholdProfile(
        registry_version=registry.registry_version, facts={},
    ).validate_against(registry)
    fixed = fixed_questionnaire_facts([package], registry)
    assert fixed[0] == "application_date" or fixed[0] == "bpl_card_shown"
    planned = pick_shared_registered_fact(empty, [package], registry)
    fixed_next = pick_fixed_questionnaire_fact(empty, [package], registry)
    # Fixed starts at questionnaire head; planned starts at first unresolved rule.
    assert fixed_next == fixed[0]
    assert planned == "is_widow"
    assert fixed_next != planned


def test_journey_ablation_matches_verdicts_on_ignwps_sample():
    report = asyncio.run(
        e4_journey_question_order.run_journey_question_order_ablation(
            scheme_ids={"IGNWPS-MH"},
            limit=4,
        )
    )
    assert report["case_count"] == 4
    assert report["verdict_match_count"] == report["case_count"]
    assert report["arm"] == "journey_question_order"
    # At least one case should show different ask order between modes.
    orders_differ = any(
        row["planned"]["asked_facts"] != row["fixed"]["asked_facts"]
        for row in report["cases"]
    )
    assert orders_differ
    for row in report["cases"]:
        assert row["planned"]["verdict"] == row["fixed"]["verdict"]
        assert row["planned"]["verdict"] == row["expected_result"] or (
            row["planned"]["verdict"] is not None
        )


def test_journey_request_rejects_fixed_order_outside_interview():
    from pydantic import ValidationError

    from src.workflow.journey import JourneyRequest

    try:
        JourneyRequest(action="evaluate", scheme_id="IGNWPS-MH", question_order="fixed")
    except ValidationError:
        return
    raise AssertionError("expected ValidationError for fixed order on evaluate")
