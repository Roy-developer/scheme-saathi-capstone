"""Choose which profile fact the intake agent should ask about next.

This is plain code with no LLM, so the same profile always gives the same
next question.
"""

from collections import Counter
from collections.abc import Sequence

from src.api.eligibility import evaluate_mock_eligibility
from src.rules.models import HouseholdProfile, RulePackage


def pick_next_fact(
    profile: HouseholdProfile,
    package: RulePackage,
    skipped_facts: frozenset[str] = frozenset(),
) -> str | None:
    """Return the next profile fact to ask about, or None to stop asking.

    Args:
        profile: What we know about the person so far. Unknown facts are None.
        package: The rule package of the chosen scheme.
        skipped_facts: Facts the person already said "I don't know" to.
            They must not be asked again, so the chat cannot loop forever.

    Returns:
        A HouseholdProfile field name, such as "date_of_birth", or None when
        the verdict is already decided or nothing is left to ask.
    """

    # 1. Ask the rule engine where we stand. A decided verdict (eligible or
    #    not_eligible) means more answers cannot change anything.
    verdict = evaluate_mock_eligibility(profile, package)
    if verdict.result != "need_more_information":
        return None
    # 2. Walk the rules in package order so questions come in a stable,
    #    sensible order (e.g. "Are you a widow?" before the age questions).
    for rule in package.rules:
        # input_facts turns a derived fact into the real profile fields:
        # "age" -> ("date_of_birth", "application_date").
        for fact in rule.input_facts:
            # Ask only facts that are still blank (None). A fact answered
            # "No" is known; if a proof rule fails on it (BPL card), the
            # person must show proof, not answer the same question again.
            if getattr(profile, fact) is None and fact not in skipped_facts:
                return fact

    # 3. Every remaining gap was answered "I don't know", so stop asking.
    #    The engine's verdict will list what is still missing.
    return None


def pick_shared_fact(
    profile: HouseholdProfile,
    packages: Sequence[RulePackage],
    skipped_facts: frozenset[str] = frozenset(),
) -> str | None:
    """Prefer a missing fact needed by the most undecided schemes.

    Count each fact once per scheme. Ties preserve candidate and rule order.
    Fact names represent the same profile field and scope, not similar wording.
    """

    counts: Counter[str] = Counter()
    for package in packages:
        verdict = evaluate_mock_eligibility(profile, package)
        if verdict.result != "need_more_information":
            continue
        facts = dict.fromkeys(
            fact for rule in package.rules for fact in rule.input_facts
            if getattr(profile, fact) is None and fact not in skipped_facts
        )
        counts.update(facts.keys())
    return max(counts, key=counts.get) if counts else None
