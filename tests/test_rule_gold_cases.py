"""Test development-only gold rule conversion and its isolated fact overlay."""

import asyncio
import json

from src.rule_extraction_reflexion import extractor
from src.rule_extraction_reflexion.extraction_checker import compare_rules
from src.rule_extraction_reflexion.gold_cases import (
    build_development_gold_cases,
)


def test_development_gold_cases_validate_with_only_the_temporary_overlay(
    monkeypatch,
) -> None:
    cases, registry = build_development_gold_cases()
    assert len(cases) == 91
    assert sum(len(case.expected_rules) for case in cases) == 106
    assert len(registry.overlay_fact_ids) == 36
    assert registry.active_fact_count == 19
    assert all(case.expected_rules for case in cases)

    active_case = None

    async def fake_invoke(_model, output_schema, _system, user_text):
        payload = json.loads(user_text)
        assert "expected_rules" not in payload
        assert active_case is not None
        return output_schema.model_validate({
            "rules": [
                rule.model_dump(mode="json")
                for rule in active_case.expected_rules
            ],
        })

    monkeypatch.setattr(extractor, "invoke_structured_output", fake_invoke)

    async def validate_cases() -> None:
        nonlocal active_case
        for case in cases:
            active_case = case
            proposed = await extractor.extract_rules(
                object(), case, registry,
            )
            assert compare_rules(case.expected_rules, proposed) == {}

    asyncio.run(validate_cases())


def test_gold_comparison_accepts_boolean_exclusion_polarity_and_full_context() -> None:
    cases, _registry = build_development_gold_cases()
    institutional_exclusion = next(
        case for case in cases
        if any(rule.rule_id == "PMSBY-IN-R04" for rule in case.expected_rules)
    )
    expected = institutional_exclusion.expected_rules[0]
    proposed = expected.model_copy(update={"value": False})

    assert institutional_exclusion.boolean_exclusion_rule_ids == (
        "PMSBY-IN-R04",
    )
    assert compare_rules(
        institutional_exclusion.expected_rules,
        (proposed,),
        boolean_exclusion_rule_ids=(
            institutional_exclusion.boolean_exclusion_rule_ids
        ),
    ) == {}

    professional_case = next(
        case for case in cases
        if any(rule.rule_id == "PM-KISAN-IN-R07" for rule in case.expected_rules)
    )
    nri_case = next(
        case for case in cases
        if any(rule.rule_id == "PM-KISAN-IN-R08" for rule in case.expected_rules)
    )
    assert "registered with Professional bodies and carrying out profession" in (
        professional_case.clauses[0].text
    )
    assert "new beneficiaries" in nri_case.clauses[0].text
    assert "Income Tax Act, 1961" in nri_case.clauses[0].text
