"""Compare proposed rules with human-approved reference rules."""

from collections.abc import Sequence
import re

from src.rules.models import Rule


# Only what a model can read from the source clause is compared.
# if_not_met and missing_field_label are reviewer policy (e.g. IGNWPS: "no BPL
# card shown means ask for the card"), not stated in the clause, so they never
# produce a difference or a lesson. Reviewer decision, Debadyuti Roy,
# 2026-11-07 (docs/IGNWPS_MH_RULE_REVIEW_2026-10-30.md, amendment).
RULE_ATTRIBUTES = (
    "field",
    "operator",
    "value",
    "unit",
    "source_clause_id",
)

# Characters a clause ID may contain but a rule ID may not (see models.Rule).
_NOT_RULE_ID_CHARACTER = re.compile(r"[^A-Za-z0-9_.:-]")


def rule_meaning(rule: Rule) -> tuple[str, str, str]:
    """Return what identifies a rule: its clause, fact and comparison.

    The model never sees the approved rule IDs, so it cannot reproduce them.
    Rules are therefore paired by meaning. The operator is part of the key
    because one clause can hold two rules on one fact (age >= 40, age <= 79).
    """
    return (rule.source_clause_id, rule.field, rule.operator)


def meaning_rule_id(rule: Rule) -> str:
    """Build a stable rule ID from a rule's meaning.

    Replacing the model's free-form ID with this one makes the same rule get
    the same ID on every run, so the same mistake hashes to the same lesson.
    """
    rule_id = _NOT_RULE_ID_CHARACTER.sub("_", ":".join(rule_meaning(rule)))
    if len(rule_id) > 120:
        raise ValueError(f"Rule meaning is too long for a rule ID: {rule_id[:60]}...")
    return rule_id


def compare_rule(expected: Rule, proposed: Rule) -> list[str]:
    """Return the names of rule attributes that differ.

    Args:
        expected: The human-approved reference rule.
        proposed: The rule produced by the extractor.
    """
    differences: list[str] = []

    for attribute in RULE_ATTRIBUTES:
        if getattr(expected, attribute) != getattr(proposed, attribute):
            differences.append(attribute)

    return differences


def compare_rules(
    expected_rules: Sequence[Rule],
    proposed_rules: Sequence[Rule],
) -> dict[str, list[str]]:
    """Report missing, unexpected, or changed rules, paired by meaning.

    Args:
        expected_rules: Human-approved reference rules.
        proposed_rules: Rules produced by the extractor.

    Returns:
        A mapping from rule ID to its differences. Missing and changed rules
        use the approved rule's ID; an unexpected rule uses the proposed ID.
        An expected rule with no proposed rule of the same meaning is marked
        ``missing``; a proposed rule with no approved partner is marked
        ``unexpected``. A wrong operator therefore shows as one ``missing``
        and one ``unexpected`` rule.

    Raises:
        ValueError: If either list holds two rules with the same meaning.
    """
    expected_by_meaning = _index_rules(expected_rules)
    proposed_by_meaning = _index_rules(proposed_rules)
    differences: dict[str, list[str]] = {}

    for meaning, expected in expected_by_meaning.items():
        proposed = proposed_by_meaning.get(meaning)
        if proposed is None:
            differences[expected.rule_id] = ["missing"]
            continue

        attribute_differences = compare_rule(expected, proposed)
        if attribute_differences:
            differences[expected.rule_id] = attribute_differences

    for meaning, proposed in proposed_by_meaning.items():
        if meaning not in expected_by_meaning:
            differences[proposed.rule_id] = ["unexpected"]

    return differences


def _index_rules(rules: Sequence[Rule]) -> dict[tuple[str, str, str], Rule]:
    """Index rules by meaning while rejecting ambiguous duplicates."""
    indexed: dict[tuple[str, str, str], Rule] = {}
    for rule in rules:
        meaning = rule_meaning(rule)
        if meaning in indexed:
            raise ValueError(f"Duplicate rule meaning: {':'.join(meaning)}")
        indexed[meaning] = rule
    return indexed
