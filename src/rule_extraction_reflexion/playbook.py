"""Freeze reviewed lessons and retrieve relevant guidance without editing it."""

import hashlib
import json
from pathlib import Path

from langgraph.store.base import BaseStore

from src.rule_extraction_reflexion.lesson_store import (
    LESSON_NAMESPACE,
    REVIEW_NAMESPACE,
    validate_pending_lesson,
)
from src.rule_extraction_reflexion.models import (
    ApprovedLesson,
    LessonReview,
    PendingLesson,
    PlaybookSnapshot,
)


PLAYBOOK_NAMESPACE = ("rule_extraction_reflexion", "playbooks")
MAX_STORED_LESSONS = 500
STORE_PAGE_SIZE = 100
DEFAULT_RELEVANT_LESSONS = 3


class SharedPlaybookError(ValueError):
    """A shared playbook is missing, altered, or disagrees with a local one."""


def _canonical_json(value: object) -> str:
    """Serialize playbook content consistently for hashing."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def playbook_hash(version: str, lessons: tuple[ApprovedLesson, ...]) -> str:
    """Return a hash of the exact version and ordered approved lesson content."""
    content = {
        "version": version,
        "lessons": [lesson.model_dump(mode="json") for lesson in lessons],
    }
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def verify_playbook(snapshot: PlaybookSnapshot) -> None:
    """Raise when a frozen playbook no longer matches its content hash."""
    expected_hash = playbook_hash(snapshot.version, snapshot.lessons)
    if snapshot.content_hash != expected_hash:
        raise ValueError("Frozen playbook content hash does not match")


async def freeze_playbook(
    store: BaseStore,
    version: str,
    *,
    base: PlaybookSnapshot | None = None,
) -> PlaybookSnapshot:
    """Save a read-only snapshot containing only approved lessons.

    A version can be frozen once. To change lessons, create a new version.

    Args:
        base: An earlier playbook whose lessons are kept. Approved lessons are
            otherwise read only from this store, so without it a teammate's new
            version would drop lessons that were approved on another machine.
    """
    existing = await store.aget(PLAYBOOK_NAMESPACE, version)
    if existing is not None:
        raise ValueError("Playbook version is already frozen")

    lesson_items = []
    offset = 0
    while True:
        page = await store.asearch(
            LESSON_NAMESPACE,
            limit=STORE_PAGE_SIZE,
            offset=offset,
        )
        if not page:
            break
        lesson_items.extend(page)
        if len(lesson_items) > MAX_STORED_LESSONS:
            raise ValueError("Too many stored lessons to freeze safely")
        offset += len(page)
        if len(page) < STORE_PAGE_SIZE:
            break
    approved: list[ApprovedLesson] = []
    for item in lesson_items:
        pending = PendingLesson.model_validate(item.value)
        validate_pending_lesson(pending, item.key)
        review_item = await store.aget(REVIEW_NAMESPACE, pending.lesson_id)
        if review_item is None:
            continue
        review = LessonReview.model_validate(review_item.value)
        if review.lesson_id != pending.lesson_id:
            raise ValueError("Lesson review is stored under the wrong ID")
        if review.decision == "approved":
            approved.append(ApprovedLesson(
                lesson_id=pending.lesson_id,
                instruction=pending.proposal.instruction,
                when_to_apply=pending.proposal.when_to_apply,
                tags=pending.proposal.tags,
                reviewer_id=review.reviewer_id,
                review_reason=review.reason,
            ))
    if base is not None:
        verify_playbook(base)
        approved_ids = {lesson.lesson_id for lesson in approved}
        approved.extend(
            lesson for lesson in base.lessons if lesson.lesson_id not in approved_ids
        )
    approved.sort(key=lambda lesson: lesson.lesson_id)
    lessons = tuple(approved)
    snapshot = PlaybookSnapshot(
        version=version,
        lessons=lessons,
        content_hash=playbook_hash(version, lessons),
    )
    await store.aput(
        PLAYBOOK_NAMESPACE,
        version,
        snapshot.model_dump(mode="json"),
    )
    return snapshot


async def load_frozen_playbook(
    store: BaseStore,
    version: str,
) -> PlaybookSnapshot:
    """Load a frozen playbook and verify that stored content is unchanged."""
    item = await store.aget(PLAYBOOK_NAMESPACE, version)
    if item is None:
        raise KeyError(f"Unknown playbook version: {version}")
    snapshot = PlaybookSnapshot.model_validate(item.value)
    if snapshot.version != version:
        raise ValueError("Frozen playbook is stored under the wrong version")
    verify_playbook(snapshot)
    return snapshot


def _read_shared_playbook(path: Path, version: str) -> PlaybookSnapshot:
    """Read a shared playbook file, refusing one that was altered."""
    try:
        snapshot = PlaybookSnapshot.model_validate_json(path.read_bytes())
        if snapshot.version != version:
            raise ValueError(f"the file holds version {snapshot.version}")
        verify_playbook(snapshot)
    except ValueError as error:
        raise SharedPlaybookError(
            f"Shared playbook {path.name} cannot be used: {error}"
        ) from error
    return snapshot


def export_playbook(snapshot: PlaybookSnapshot, folder: Path) -> Path:
    """Write a frozen playbook to a file that can be committed to git."""
    verify_playbook(snapshot)
    path = folder / f"{snapshot.version}.json"
    if path.exists():
        if _read_shared_playbook(path, snapshot.version).content_hash != snapshot.content_hash:
            raise SharedPlaybookError(
                f"Playbook {snapshot.version} is already shared with different lessons. "
                "Frozen versions never change; freeze a new version."
            )
        return path
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    path.write_bytes(text.encode("utf-8"))
    return path


async def load_playbook(store: BaseStore, version: str, folder: Path) -> PlaybookSnapshot:
    """Load a playbook, copying the shared file into this store on first use."""
    path = folder / f"{version}.json"
    shared = _read_shared_playbook(path, version) if path.exists() else None
    try:
        local = await load_frozen_playbook(store, version)
    except KeyError as error:
        if shared is None:
            raise SharedPlaybookError(
                f"Unknown playbook version: {version}. It is not in the local "
                f"store or in {folder}."
            ) from error
        await store.aput(PLAYBOOK_NAMESPACE, version, shared.model_dump(mode="json"))
        return shared
    if shared is not None and shared.content_hash != local.content_hash:
        raise SharedPlaybookError(
            f"Local playbook {version} has different lessons from the shared file "
            f"{path.name}, so results would not be comparable."
        )
    return local


def relevant_lessons(
    snapshot: PlaybookSnapshot,
    topic_tags: tuple[str, ...],
    *,
    limit: int = DEFAULT_RELEVANT_LESSONS,
) -> tuple[ApprovedLesson, ...]:
    """Select approved lessons by reviewed tags from a verified snapshot."""
    verify_playbook(snapshot)
    if limit < 1:
        raise ValueError("Lesson retrieval limit must be positive")
    requested_tags = frozenset(topic_tags)
    if not requested_tags:
        return ()
    matches = [
        lesson
        for lesson in snapshot.lessons
        if requested_tags.intersection(lesson.tags)
    ]
    return tuple(matches[:limit])
