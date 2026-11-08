"""Test playbook freezing in the real-call demo without calling OpenRouter."""

import asyncio

from langgraph.store.memory import InMemoryStore

from scripts.reflexion_demo_real import freeze_reviewed_lessons
from src.rule_extraction_reflexion.lesson_store import (
    review_lesson,
    save_pending_lesson,
)
from src.rule_extraction_reflexion.models import LessonProposal, SourceClause
from src.rules.models import Rule


def test_approved_demo_lesson_is_frozen_in_successive_versions() -> None:
    """The demo freezes reviewed lessons and advances versions on reruns."""
    async def scenario() -> None:
        store = InMemoryStore()
        clause = SourceClause(
            clause_id="synthetic-clause-1",
            text="The synthetic applicant must be at least 60 years old.",
        )
        expected = Rule(
            rule_id="synthetic-age",
            field="age",
            operator="gte",
            value=60,
            source_clause_id=clause.clause_id,
        )
        proposed = expected.model_copy(update={"value": 61})
        pending = await save_pending_lesson(
            store,
            proposal=LessonProposal(
                instruction="Copy the threshold from the source.",
                when_to_apply="Extracting an age boundary.",
                tags=("age_boundary",),
            ),
            source_case_id="synthetic-case-1",
            source_clauses=(clause,),
            expected_rules=(expected,),
            proposed_rules=(proposed,),
            differences={"synthetic-age": ["value"]},
        )
        await review_lesson(
            store,
            lesson_id=pending.lesson_id,
            decision="approved",
            reviewer_id="reviewer-1",
            reason="Verified against the synthetic reference rule.",
            authorize_reviewer=lambda reviewer: reviewer == "reviewer-1",
        )

        first = await freeze_reviewed_lessons(store)
        second = await freeze_reviewed_lessons(store)

        assert first.version == "1.0.0"
        assert second.version == "1.0.1"
        assert len(first.lessons) == 1
        assert first.lessons[0].lesson_id == pending.lesson_id
        assert second.lessons == first.lessons
        assert second.content_hash != first.content_hash

    asyncio.run(scenario())
