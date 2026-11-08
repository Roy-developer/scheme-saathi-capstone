"""Test validation and immutability of rule-extraction lesson records."""

import pytest
from pydantic import ValidationError

from src.rule_extraction_reflexion.models import (
    LessonProposal,
    PendingLesson,
    SourceClause,
)
from src.rules.models import Rule


@pytest.fixture
def lesson_proposal() -> LessonProposal:
    """Provide one synthetic lesson proposal."""
    return LessonProposal(
        instruction="Use gte for 'at least'.",
        when_to_apply="Extracting a lower boundary.",
        tags=("age_boundary",),
    )


@pytest.fixture
def pending_lesson(lesson_proposal: LessonProposal) -> PendingLesson:
    """Provide an immutable, pending lesson record."""
    return PendingLesson(
        lesson_id="synthetic-lesson-1",
        proposal=lesson_proposal,
        source_case_id="synthetic-case-1",
        source_clauses=(SourceClause(
            clause_id="synthetic-clause-1",
            text="The synthetic applicant must be at least 60 years old.",
        ),),
        expected_rules=(Rule(
            rule_id="synthetic-age",
            field="age",
            operator="gte",
            value=60,
            source_clause_id="synthetic-clause-1",
        ),),
        proposed_rules=(),
        differences=(),
    )


def test_proposal_rejects_approval_status() -> None:
    """A model proposal cannot declare itself approved."""
    with pytest.raises(ValidationError):
        LessonProposal.model_validate({
            "instruction": "Use gte for 'at least'.",
            "when_to_apply": "Extracting a lower boundary.",
            "status": "approved",
        })


def test_new_record_starts_pending(lesson_proposal: LessonProposal) -> None:
    """The application creates lessons awaiting human review."""
    record = PendingLesson(
        lesson_id="synthetic-lesson-1",
        proposal=lesson_proposal,
        source_case_id="synthetic-case-1",
        source_clauses=(SourceClause(
            clause_id="synthetic-clause-1",
            text="The synthetic applicant must be at least 60 years old.",
        ),),
        expected_rules=(),
        proposed_rules=(),
        differences=(),
    )

    assert record.status == "pending"
    assert record.proposal == lesson_proposal


def test_pending_record_cannot_start_approved(
    lesson_proposal: LessonProposal,
) -> None:
    """Reject an approval status supplied when creating a pending record."""
    with pytest.raises(ValidationError):
        PendingLesson.model_validate({
            "lesson_id": "synthetic-lesson-1",
            "proposal": lesson_proposal.model_dump(),
            "source_case_id": "synthetic-case-1",
            "source_clauses": [{
                "clause_id": "synthetic-clause-1",
                "text": "The synthetic applicant must be at least 60 years old.",
            }],
            "expected_rules": [],
            "proposed_rules": [],
            "differences": [],
            "status": "approved",
        })


def test_pending_status_cannot_be_changed(pending_lesson: PendingLesson) -> None:
    """A pending record cannot be reassigned to approved."""
    with pytest.raises(ValidationError):
        pending_lesson.status = "approved"


def test_pending_proposal_cannot_be_edited(pending_lesson: PendingLesson) -> None:
    """A pending lesson's proposal cannot be silently changed."""
    with pytest.raises(ValidationError):
        pending_lesson.proposal.instruction = "Use gt for 'at least'."
