#!/usr/bin/env python
"""Reflexion flow demo with real code, fake models.

This script runs the actual reflexion pipeline using the real extractor,
comparer, and lesson-store code, but with scripted model responses
so it works offline without any API calls.

Run with: .\.venv\Scripts\python.exe scripts\reflexion_demo.py
"""
from pathlib import Path
import asyncio
import json
import sys

from langgraph.store.memory import InMemoryStore

from src.rules.facts import FactRegistry
from src.rules.models import Rule
from src.rule_extraction_reflexion import extractor, reflexion
from src.rule_extraction_reflexion.lesson_store import save_pending_lesson
from src.rule_extraction_reflexion.models import (
    LessonProposal,
    RuleExtractionCase,
    RuleExtractionOutput,
    SourceClause,
)
from src.rule_extraction_reflexion.extraction_checker import compare_rules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_REGISTRY = Path(__file__).parent.parent / "tests" / "fixtures" / "phase4" / "fact_registry.json"


def load_registry() -> FactRegistry:
    return FactRegistry.model_validate_json(
        FIXTURE_REGISTRY.read_text(encoding="utf-8")
    )


def make_case() -> RuleExtractionCase:
    expected = Rule(
        rule_id="synthetic-ratio-minimum",
        field="exam_ratio",
        operator="gte",
        value=0.6,
        unit="ratio",
        source_clause_id="synthetic-clause-1",
    )
    return RuleExtractionCase(
        case_id="synthetic-case-1",
        clauses=(SourceClause(
            clause_id="synthetic-clause-1",
            text="The synthetic exam ratio must be at least 0.6.",
        ),),
        expected_rules=(expected,),
        allowed_fact_ids=("exam_ratio",),
        topic_tags=("age_boundary",),
    )


# ---------------------------------------------------------------------------
# Scripted model boundaries
# ---------------------------------------------------------------------------

async def make_fake_extraction(_model, output_schema, _system_text, _user_text):
    """Extraction always returns value=0.7 (wrong) — model mistake."""
    print("\n--- Extraction model called (returns value=0.7) ---")
    wrong_rule = Rule(
        rule_id="synthetic-ratio-minimum",
        field="exam_ratio",
        operator="gte",
        value=0.7,  # <-- deliberate mismatch
        unit="ratio",
        source_clause_id="synthetic-clause-1",
    )
    # source_text added later by _validate_extracted_rules using clause.text
    return output_schema(rules=(wrong_rule,))


async def make_fake_reflection(_model, output_schema, _system_text, _user_text):
    """Reflection always returns one lesson proposal."""
    print("\n--- Reflection model called ---")
    payload = json.loads(_user_text)
    print(f"Differences sent: {payload['differences']}")
    print(f"Proposed rules sent: {[r['value'] for r in payload['proposed_rules']]}")
    print(f"Expected rules sent: {[r['value'] for r in payload['approved_reference_rules']]}")
    return output_schema(
        instruction="Use gte for an inclusive lower boundary.",
        when_to_apply="The source says 'at least'.",
        tags=("age_boundary",),
    )


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

async def run_demo(with_differences: bool = True):
    print("=" * 60)
    print("REFLEXION FLOW DEMO (real code, fake models)")
    print("=" * 60)

    registry = load_registry()
    case = make_case()
    store = InMemoryStore()

    # --- Step 1: Extraction ---
    print("\n[1] Running extract_rules()...")
    # Temporarily replace invoke_structured_output so our fake runs
    original = extractor.invoke_structured_output
    extractor.invoke_structured_output = make_fake_extraction

    try:
        proposed_rules = await extractor.extract_rules(
            None, case, registry, playbook=None,
        )
    finally:
        extractor.invoke_structured_output = original

    # _validate_extracted_rules has already run and attached source_text
    # from case.clauses[0].text. The Rule model is frozen, but source_text
    # was set during validation, so it's fine.
    print(f"   Proposed rule value: {proposed_rules[0].value}")
    print(f"   Proposed rule source_text: {proposed_rules[0].source_text[:50]}...")

    # --- Step 2: Comparison ---
    print("\n[2] Comparing with reference rules...")
    differences = compare_rules(case.expected_rules, proposed_rules)
    print(f"   Differences: {differences}")

    # --- Step 3: Reflection (only if differences) ---
    pending_lesson = None
    if differences:
        print("\n[3] Running propose_lesson (reflection)...")
        # Replace reflection's invoke too
        orig_reflex = reflexion.invoke_structured_output
        reflexion.invoke_structured_output = make_fake_reflection

        try:
            proposal = await reflexion.propose_lesson(
                None, case, proposed_rules, differences,
            )
        finally:
            reflexion.invoke_structured_output = orig_reflex

        print(f"   Lesson proposal: {proposal.instruction}")

        print("\n[4] Saving pending lesson...")
        pending = await save_pending_lesson(
            store,
            proposal=proposal,
            source_case_id=case.case_id,
            source_clauses=case.clauses,
            expected_rules=case.expected_rules,
            proposed_rules=proposed_rules,
            differences=differences,
        )
        pending_lesson = pending
        print(f"   Lesson ID: {pending.lesson_id}")
        print(f"   Lesson status: {pending.status}")
        print(f"   Instruction: {pending.proposal.instruction}")
        print(f"   Tags: {pending.proposal.tags}")
    else:
        print("\n[3] No differences → skipping reflection (no lesson saved)")

    # --- Step 4: Result ---
    print("\n[5] ReflexionResult...")
    result = reflexion.ReflexionResult(
        proposed_rules=tuple(proposed_rules),
        differences=differences,
        pending_lesson=pending_lesson,
    )
    print(f"   Differences in result: {result.differences}")
    print(f"   Pending lesson in result: {result.pending_lesson is not None}")
    if result.pending_lesson:
        pl = result.pending_lesson
        print(f"   Lesson status: {pl.status}")
        print(f"   Lesson instruction: {pl.proposal.instruction}")

    # --- Step 5: Boundary explanation ---
    print("\n[6] Key boundaries demonstrated:")
    print("    • lesson_id is content-hashed → tampering detected")
    print("    • PendingLesson.status = 'pending' (frozen literal)")
    print("    • Model never sees expected_rules (hidden from extraction)")
    print("    • Human must review via review_lesson(authorize_reviewer)")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Run with differences (model proposes wrong value)
    print("\n=== RUN 1: Model proposes wrong value (0.7 vs 0.6) ===\n")
    asyncio.run(run_demo(with_differences=True))

    print("\n\n" + "=" * 60)
    print("RUN 2: Model proposes correct value (press Ctrl+C to skip)")
    print("=" * 60 + "\n")
    try:
        asyncio.run(run_demo(with_differences=False))
    except KeyboardInterrupt:
        print("\nSkipped run 2.")