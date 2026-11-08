"""Persist proposed lessons and append-only human review decisions."""

from collections.abc import Callable
import hashlib
import json
from typing import Literal

from langgraph.store.base import BaseStore

from src.rule_extraction_reflexion.models import (
    LessonProposal,
    LessonReview,
    PendingLesson,
    SourceClause,
)
from src.rules.models import Rule


LESSON_NAMESPACE = ("rule_extraction_reflexion", "lessons")
REVIEW_NAMESPACE = ("rule_extraction_reflexion", "reviews")


def _canonical_json(value: object) -> str:
    """Serialize records consistently before hashing them."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def lesson_identity(
    proposal: LessonProposal,
    source_case_id: str,
    source_clauses: tuple[SourceClause, ...],
    expected_rules: tuple[Rule, ...],
    proposed_rules: tuple[Rule, ...],
    differences: dict[str, list[str]],
) -> str:
    """Derive a stable lesson ID from the exact proposal and its evidence."""
    identity = {
        "proposal": proposal.model_dump(mode="json"),
        "source_case_id": source_case_id,
        "source_clauses": [
            clause.model_dump(mode="json") for clause in source_clauses
        ],
        "expected_rules": [
            rule.model_dump(mode="json") for rule in expected_rules
        ],
        "proposed_rules": [
            rule.model_dump(mode="json") for rule in proposed_rules
        ],
        "differences": differences,
    }
    return hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


def validate_pending_lesson(record: PendingLesson, key: str) -> None:
    """Reject stored lesson edits or a record stored under another key."""
    differences = {
        item.rule_id: list(item.attributes)
        for item in record.differences
    }
    if lesson_identity(
        record.proposal,
        record.source_case_id,
        record.source_clauses,
        record.expected_rules,
        record.proposed_rules,
        differences,
    ) != key or record.lesson_id != key:
        raise ValueError("Pending lesson content does not match its ID")


async def save_pending_lesson(
    store: BaseStore,
    *,
    proposal: LessonProposal,
    source_case_id: str,
    source_clauses: tuple[SourceClause, ...],
    expected_rules: tuple[Rule, ...],
    proposed_rules: tuple[Rule, ...],
    differences: dict[str, list[str]],
) -> PendingLesson:
    """Save a new immutable lesson proposal; duplicate evidence is rejected."""
    lesson_id = lesson_identity(
        proposal,
        source_case_id,
        source_clauses,
        expected_rules,
        proposed_rules,
        differences,
    )
    existing = await store.aget(LESSON_NAMESPACE, lesson_id)
    if existing is not None:
        raise ValueError("This lesson proposal is already stored")

    record = PendingLesson(
        lesson_id=lesson_id,
        proposal=proposal,
        source_case_id=source_case_id,
        source_clauses=source_clauses,
        expected_rules=expected_rules,
        proposed_rules=proposed_rules,
        differences=tuple(
            {"rule_id": rule_id, "attributes": tuple(attributes)}
            for rule_id, attributes in sorted(differences.items())
        ),
    )
    await store.aput(
        LESSON_NAMESPACE,
        lesson_id,
        record.model_dump(mode="json"),
    )
    return record


async def review_lesson(
    store: BaseStore,
    *,
    lesson_id: str,
    decision: Literal["approved", "rejected"],
    reviewer_id: str,
    reason: str,
    authorize_reviewer: Callable[[str], bool],
) -> LessonReview:
    """Record one trusted human decision separately from the proposal.

    ``authorize_reviewer`` must be supplied by a trusted administrative
    boundary. This package does not provide user authentication or an HTTP
    review endpoint.
    """
    if not authorize_reviewer(reviewer_id):
        raise PermissionError("Reviewer is not authorized")
    pending_item = await store.aget(LESSON_NAMESPACE, lesson_id)
    if pending_item is None:
        raise KeyError(f"Unknown lesson: {lesson_id}")
    pending = PendingLesson.model_validate(pending_item.value)
    validate_pending_lesson(pending, lesson_id)
    existing_review = await store.aget(REVIEW_NAMESPACE, lesson_id)
    if existing_review is not None:
        raise ValueError("A lesson review is already recorded")

    review = LessonReview(
        lesson_id=lesson_id,
        decision=decision,
        reviewer_id=reviewer_id,
        reason=reason,
    )
    await store.aput(
        REVIEW_NAMESPACE,
        lesson_id,
        review.model_dump(mode="json"),
    )
    return review
