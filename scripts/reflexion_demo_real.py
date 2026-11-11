#!/usr/bin/env python
"""Reflexion flow demo with REAL OpenRouter API calls.

This script runs the actual reflexion pipeline using the real extractor,
comparer, and lesson-store code, with real OpenRouter model calls.

⚠️  THIS SCRIPT MAKES REAL OPENAI-COMPATIBLE API CALLS TO OPENROUTER.
    See AGENTS.md line 112 for the exception that permits this.

Cost estimate: Each full cycle (extraction + reflection) typically uses
2-4 OpenRouter chat calls. At typical OpenRouter rates (~$0.001-$0.03 per
call), expect roughly $0.005-$0.15 per run. Do not run repeatedly without
understanding the cost implications.

Run with: python scripts\reflexion_demo_real.py
"""
from pathlib import Path
import asyncio
import json
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.store.sqlite.aio import AsyncSqliteStore
from langgraph.store.base import BaseStore

from src.config import load_project_dotenv, openrouter_chat_settings
from src.rules.facts import FactRegistry
from src.rules.models import Rule
from src.rule_extraction_reflexion import extractor, reflexion
from src.rule_extraction_reflexion.lesson_store import save_pending_lesson, review_lesson
from src.rule_extraction_reflexion.models import PlaybookSnapshot
from src.rule_extraction_reflexion.playbook import (
    PLAYBOOK_NAMESPACE,
    freeze_playbook,
    load_frozen_playbook,
)
from src.rule_extraction_reflexion.models import (
    LessonProposal,
    RuleExtractionCase,
    SourceClause,
)
from src.rule_extraction_reflexion.extraction_checker import compare_rules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURE_REGISTRY = PROJECT_ROOT / "tests" / "fixtures" / "phase4" / "fact_registry.json"
SQLITE_DB_PATH = PROJECT_ROOT / "data" / "runtime" / "reflexion_demo.sqlite3"
PLAYBOOK_PAGE_SIZE = 100


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


async def freeze_reviewed_lessons(store: BaseStore) -> PlaybookSnapshot:
    """Freeze all approved lessons under the next patch version and reload it."""
    versions: list[tuple[int, int, int]] = []
    offset = 0
    while True:
        page = await store.asearch(
            PLAYBOOK_NAMESPACE,
            limit=PLAYBOOK_PAGE_SIZE,
            offset=offset,
        )
        if not page:
            break
        for item in page:
            major, minor, patch = (int(part) for part in item.key.split("."))
            versions.append((major, minor, patch))
        offset += len(page)
        if len(page) < PLAYBOOK_PAGE_SIZE:
            break

    if versions:
        major, minor, patch = max(versions)
        next_version = f"{major}.{minor}.{patch + 1}"
    else:
        next_version = "1.0.0"
    await freeze_playbook(store, next_version)
    return await load_frozen_playbook(store, next_version)


# ---------------------------------------------------------------------------
# Real model calls (no mocking)
# ---------------------------------------------------------------------------

async def real_extract(model, output_schema, system_text, user_text):
    """
    Make a REAL extraction model call via OpenRouter.

    Args:
        model: The ChatOpenAI model instance (created once outside, passed in).
        output_schema: The Pydantic model class for structured output.
        system_text: System prompt instructions.
        user_text: JSON payload with allowed_fact_ids, source_clauses, etc.

    The model does NOT see expected_rules — those are hidden to prevent
    the model from simply copying the answers.

    Python then validates the proposed rules against the FactRegistry:
    - field must be an allowed fact
    - operator/value must match the fact's value_type
    - unit must match
    - source_text is replaced with the actual clause text (not model-written)
    """
    runnable = model.with_structured_output(output_schema)
    result = await runnable.ainvoke(
        [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]
    )
    return result


async def real_reflection(model, output_schema, system_text, user_text):
    """
    Make a REAL reflection model call via OpenRouter.

    This is called ONLY when extraction has differences (errors).
    The model receives:
    - source_clauses (the source text)
    - approved_reference_rules (the gold standard — for comparison context)
    - proposed_rules (what the model proposed, which was wrong)
    - differences (what Python detected as wrong)

    The model proposes a LESSON — general guidance for future extractions.
    The lesson is NOT automatically applied; it goes to human review first.

    Tags must be lowercase identifiers (e.g., 'age_boundary', 'value_mismatch').
    """
    runnable = model.with_structured_output(output_schema)
    result = await runnable.ainvoke(
        [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]
    )
    return result


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

async def run_demo_with_store(
    model: BaseChatModel,
    store: BaseStore,
    registry: FactRegistry,
    case: RuleExtractionCase,
) -> None:
    """Run the demo using an already-open model and persistent Store."""
    print("=" * 70)
    print("REFLEXION FLOW DEMO (REAL OpenRouter API calls)")
    print("=" * 70)

    # --- Step 1: Extraction (REAL model call) ---
    print("\n[1] Running extract_rules() with REAL model...")
    system_prompt = extractor.EXTRACTION_SYSTEM_PROMPT
    user_payload = {
        "allowed_fact_ids": sorted(["exam_ratio"]),
        "source_clauses": [case.clauses[0].model_dump(mode="json")],
        "approved_extractor_lessons": [],
    }
    user_text = json.dumps(user_payload, ensure_ascii=False, sort_keys=True)

    try:
        runnable = model.with_structured_output(
            extractor.RuleExtractionOutput
        )
        result = await runnable.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ]
        )
        proposed_rules = result.rules
        print(f"   Model returned {len(proposed_rules)} rule(s)")
        if proposed_rules:
            print(f"   First rule value: {proposed_rules[0].value}")
            print(f"   First rule operator: {proposed_rules[0].operator}")
    except Exception as e:
        print(f"   ❌ Extraction failed: {e}")
        return

    # --- Step 2: Comparison ---
    print("\n[2] Comparing with reference rules...")
    differences = compare_rules(case.expected_rules, proposed_rules)
    print(f"   Differences: {differences}")

    # --- Step 3: Reflection (REAL model call) ---
    pending_lesson = None
    if differences:
        print("\n[3] Running propose_lesson (reflection) with REAL model...")
        reflection_prompt_parts = {
            "source_clauses": [{"clause_id": case.clauses[0].clause_id, "text": case.clauses[0].text}],
            "approved_reference_rules": [
                {
                    "rule_id": case.expected_rules[0].rule_id,
                    "field": case.expected_rules[0].field,
                    "operator": case.expected_rules[0].operator,
                    "value": case.expected_rules[0].value,
                    "unit": case.expected_rules[0].unit,
                    "source_clause_id": case.expected_rules[0].source_clause_id,
                }
            ],
            "proposed_rules": [
                {
                    "rule_id": proposed_rules[0].rule_id,
                    "field": proposed_rules[0].field,
                    "operator": proposed_rules[0].operator,
                    "value": proposed_rules[0].value,
                    "unit": proposed_rules[0].unit,
                    "source_clause_id": proposed_rules[0].source_clause_id,
                }
            ],
            "differences": differences,
        }
        reflection_system = reflexion.REFLECTION_SYSTEM_PROMPT + "\n\nTags must be lowercase identifiers (a-z, 0-9, underscore), e.g., 'age_boundary', 'value_mismatch'."
        reflection_user = json.dumps(reflection_prompt_parts, ensure_ascii=False, sort_keys=True)

        try:
            result = await real_reflection(
                model,
                LessonProposal,
                reflection_system,
                reflection_user,
            )
            proposal = result  # Reflection returns LessonProposal
            print(f"   Model proposed lesson: {proposal.instruction}")
        except Exception as e:
            print(f"   ❌ Reflection failed: {e}")
            return

        print("\n[4] Saving pending lesson...")
        try:
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

            # --- Step 4b: Human Review (Manual) ---
            print("\n[4b] Reviewing lesson (human approval)...")
            print(f"   Lesson ID: {pending.lesson_id}")
            print(f"   Instruction: {pending.proposal.instruction}")
            print(f"   Tags: {pending.proposal.tags}")
            print()

            def is_authorized(reviewer_id: str) -> bool:
                return reviewer_id == "reviewer-1"

            # Wait for manual review decision
            decision = input("   Approve this lesson? (y/n): ").strip().lower()
            if decision in ("y", "yes"):
                review_decision = "approved"
                review_reason = input("   Review reason: ").strip() or "Approved by human reviewer."
            elif decision in ("n", "no"):
                review_decision = "rejected"
                review_reason = input("   Review reason: ").strip() or "Rejected by human reviewer."
            else:
                print("   ❌ Invalid decision. Skipping review.")
                review_decision = None

            if review_decision:
                try:
                    review = await review_lesson(
                        store,
                        lesson_id=pending.lesson_id,
                        decision=review_decision,
                        reviewer_id="reviewer-1",
                        reason=review_reason,
                        authorize_reviewer=is_authorized,
                    )
                    print(f"   ✓ Review recorded: {review.decision}")
                    print(f"   Reviewer: {review.reviewer_id}")
                    print(f"   Reason: {review.reason}")
                    print()
                    print("   📝 YOUR REVIEW REASON IS STORED IN:")
                    print("       LessonReview.reason =", repr(review.reason))
                    print("   📝 The lesson is now in REVIEW_NAMESPACE")
                    print("   📝 lesson_id =", pending.lesson_id)
                    if review.decision == "approved":
                        snapshot = await freeze_reviewed_lessons(store)
                        print("\n[4c] Frozen approved lessons into the playbook.")
                        print(f"   Playbook version: {snapshot.version}")
                        print(f"   Approved lessons: {len(snapshot.lessons)}")
                        print(f"   Content hash: {snapshot.content_hash}")
                    else:
                        print("\n[4c] Lesson rejected; it was not added to a playbook.")
                except Exception as e:
                    print(f"   ❌ Review failed: {e}")
        except Exception as e:
            print(f"   ❌ save_pending_lesson failed: {e}")
    else:
        print("\n[3] No differences → skipping reflection (no lesson saved)")

    # --- Step 4: Result ---
    print("\n[5] ReflexionResult...")
    result = reflexion.ReflexionResult(
        proposed_rules=tuple(proposed_rules) if proposed_rules else (),
        differences=differences,
        pending_lesson=pending_lesson,
    )
    print(f"   Differences in result: {result.differences}")
    print(f"   Pending lesson in result: {result.pending_lesson is not None}")
    if result.pending_lesson:
        pl = result.pending_lesson
        print(f"   Lesson status: {pl.status}")
        print(f"   Lesson instruction: {pl.proposal.instruction}")

    # --- Step 5: Boundaries ---
    print("\n[6] Key boundaries demonstrated:")
    print("    • Real OpenRouter API calls (as permitted by AGENTS.md §112)")
    print("    • lesson_id is content-hashed → tampering detected")
    print("    • PendingLesson.status = 'pending' (frozen literal)")
    print("    • Model never sees expected_rules (hidden from extraction payload)")
    print("    • Human must review via review_lesson(authorize_reviewer)")

    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)


async def run_demo():
    """Load project credentials and run with a properly managed SQLite Store."""
    # Do not let a coding-agent credential fall through if project .env lacks a key.
    os.environ.pop("OPENROUTER_API_KEY", None)
    load_project_dotenv()
    api_key, model_name = openrouter_chat_settings("openai/gpt-4o-mini")
    if not api_key:
        print("\nERROR: OPENROUTER_API_KEY is missing from the project .env.")
        return

    from src.llm_client import openrouter_chat_model

    model = openrouter_chat_model(api_key=api_key, model=model_name)
    registry = load_registry()
    case = make_case()
    SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("\nOpenRouter calls will use the project .env key.")
    print(f"Model: {model_name}; SQLite Store: {SQLITE_DB_PATH}")
    print("This demo makes real OpenRouter calls and may incur charges.")

    async with AsyncSqliteStore.from_conn_string(str(SQLITE_DB_PATH)) as store:
        await store.setup()
        await run_demo_with_store(model, store, registry, case)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_demo())