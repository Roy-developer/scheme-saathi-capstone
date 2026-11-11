"""Test comparison of synthetic extracted rules with reference rules."""

import pytest

from src.rule_extraction_reflexion.extraction_checker import (
    compare_rule,
    compare_rules,
)
from src.rules.models import Rule


@pytest.fixture
def expected_rule() -> Rule:
    """Provide one synthetic, human-approved reference rule."""
    return Rule(
        rule_id="synthetic-age",
        field="age",
        operator="gte",
        value=60,
        source_clause_id="synthetic-clause-1",
    )


def test_matching_rules_return_no_differences(expected_rule: Rule) -> None:
    """Matching rule attributes produce an empty result."""
    proposed = Rule(
        rule_id="synthetic-age",
        field="age",
        operator="gte",
        value=60,
        source_clause_id="synthetic-clause-1",
    )

    assert compare_rule(expected_rule, proposed) == []


def test_changed_value_returns_value_difference(expected_rule: Rule) -> None:
    """An incorrect threshold is reported without changing either rule."""
    proposed = Rule(
        rule_id="synthetic-age",
        field="age",
        operator="gte",
        value=61,
        source_clause_id="synthetic-clause-1",
    )

    assert compare_rule(expected_rule, proposed) == ["value"]
    assert expected_rule.value == 60
    assert proposed.value == 61


def test_reviewer_policy_fields_are_not_compared(expected_rule: Rule) -> None:
    """What happens when a condition is unmet is reviewer policy, not text.

    The source clause never says it, so a model cannot extract it. Reviewer
    decision (Debadyuti Roy, 2026-11-07): ignore it when comparing.
    """
    proposed = expected_rule.model_copy(update={
        "if_not_met": "need_more_information",
        "missing_field_label": "Age proof",
    })

    assert compare_rule(expected_rule, proposed) == []


def test_multiple_differences_are_reported(expected_rule: Rule) -> None:
    """Report every changed attribute, not just the first."""
    proposed = Rule(
        rule_id="synthetic-age",
        field="age",
        operator="lte",
        value=61,
        source_clause_id="synthetic-clause-2",
    )

    assert compare_rule(expected_rule, proposed) == [
        "operator",
        "value",
        "source_clause_id",
    ]


@pytest.mark.parametrize(
    ("field", "operator", "source_clause_id", "expected_difference"),
    [
        ("exam_marks", "gte", "synthetic-clause-1", "field"),
        ("age", "lte", "synthetic-clause-1", "operator"),
        ("age", "gte", "synthetic-clause-2", "source_clause_id"),
    ],
)
def test_each_rule_attribute_is_checked(
    expected_rule: Rule,
    field: str,
    operator: str,
    source_clause_id: str,
    expected_difference: str,
) -> None:
    proposed = Rule(
        rule_id="synthetic-age",
        field=field,
        operator=operator,
        value=60,
        source_clause_id=source_clause_id,
    )

    assert compare_rule(expected_rule, proposed) == [expected_difference]


def test_rule_sets_report_missing_and_unexpected_rules(
    expected_rule: Rule,
) -> None:
    """Distinguish an omitted approved rule from an added extra rule."""
    extra_rule = Rule(
        rule_id="synthetic-income",
        field="age",
        operator="lte",
        value=100,
        source_clause_id="synthetic-clause-2",
    )

    missing = compare_rules(
        expected_rules=[expected_rule, extra_rule],
        proposed_rules=[expected_rule],
    )
    unexpected = compare_rules(
        expected_rules=[expected_rule],
        proposed_rules=[expected_rule, extra_rule],
    )

    assert missing == {"synthetic-income": ["missing"]}
    assert unexpected == {"synthetic-income": ["unexpected"]}


def test_rule_sets_report_changed_attributes_by_rule_id(
    expected_rule: Rule,
) -> None:
    """Compare fields when the expected and proposed rule IDs match."""
    changed_rule = Rule(
        rule_id=expected_rule.rule_id,
        field="age",
        operator="gte",
        value=61,
        source_clause_id="synthetic-clause-1",
    )

    assert compare_rules([expected_rule], [changed_rule]) == {
        expected_rule.rule_id: ["value"],
    }


def test_boolean_exclusion_matches_equivalent_positive_eligibility_form() -> None:
    excluded = Rule(
        rule_id="synthetic-exclusion",
        field="is_institutional_account_holder",
        operator="eq",
        value=True,
        source_clause_id="synthetic-clause-1",
    )
    eligible_form = excluded.model_copy(update={"value": False})

    assert compare_rules([excluded], [eligible_form]) == {
        excluded.rule_id: ["value"],
    }
    assert compare_rules(
        [excluded],
        [eligible_form],
        boolean_exclusion_rule_ids=(excluded.rule_id,),
    ) == {}


def test_rule_sets_reject_two_rules_with_the_same_meaning(expected_rule: Rule) -> None:
    """Two rules with one meaning cannot silently overwrite each other."""
    duplicate = Rule(
        rule_id=expected_rule.rule_id,
        field="age",
        operator="gte",
        value=61,
        source_clause_id="synthetic-clause-1",
    )

    with pytest.raises(ValueError, match="Duplicate rule meaning"):
        compare_rules([expected_rule, duplicate], [])