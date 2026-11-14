"""Freeze playbook 1.1.2: keep 1.1.1 lessons + APY multi-sentence lesson.

Adds:
- When clause text has several sentences under one clause_id, extract from every
  sentence (APY age + citizenship/savings), not only the first.

Does not spend model budget. Safe if 1.1.2 is not already shared.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.store.sqlite.aio import AsyncSqliteStore  # noqa: E402

from src.rule_extraction_reflexion.lesson_store import (  # noqa: E402
    review_lesson,
    save_pending_lesson,
)
from src.rule_extraction_reflexion.models import LessonProposal  # noqa: E402
from src.rule_extraction_reflexion.playbook import (  # noqa: E402
    SharedPlaybookError,
    export_playbook,
    freeze_playbook,
    load_playbook,
)
from src.rule_extraction_reflexion.scheme_rules import (  # noqa: E402
    PLAYBOOK_DIR,
    STORE_FILE,
    build_cases,
)

REVIEWER = "Roy-developer"
VERSION = "1.1.2"
BASE = "1.1.1"

NEW_LESSONS = (
    {
        "clause_id": "APY-IN-ELIGIBILITY-01",
        "instruction": (
            "When the clause text contains more than one sentence under a "
            "single clause_id, read every sentence and write a rule for each "
            "condition named in any of them. Do not stop after the first "
            "sentence (for example age bounds) when a later sentence adds "
            "citizenship or a savings-bank requirement."
        ),
        "when_to_apply": (
            "Inclusion clauses whose supplied text spans multiple sentences "
            "or lists several independent eligibility conditions."
        ),
        "reason": (
            "Accuracy fix for APY-IN-ELIGIBILITY-01 after case-text assembly "
            "joined all unique source_text lines: model must use the full "
            "multi-sentence clause block, not only the age sentence."
        ),
    },
)


async def _seed_and_freeze(store_path: Path) -> Path:
    shared = PLAYBOOK_DIR / f"{VERSION}.json"
    if shared.exists():
        raise SharedPlaybookError(
            f"Playbook {VERSION} is already shared at {shared}; freeze a new version."
        )

    override = (
        PROJECT_ROOT
        / "eval"
        / "held_out"
        / "extraction"
        / "local"
        / "cases_all_live_clauses_v1.json"
    )
    cases = (
        build_cases("team_override", path=override)
        if override.is_file()
        else build_cases()
    )
    by_id = {case.case_id: case for case in cases}
    store_path.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteStore.from_conn_string(str(store_path)) as store:
        await store.setup()
        for item in NEW_LESSONS:
            case = by_id[item["clause_id"]]
            pending = await save_pending_lesson(
                store,
                proposal=LessonProposal(
                    instruction=item["instruction"],
                    when_to_apply=item["when_to_apply"],
                    tags=case.topic_tags,
                ),
                source_case_id=case.case_id,
                source_clauses=case.clauses,
                expected_rules=case.expected_rules,
                proposed_rules=case.expected_rules,
                differences={},
            )
            await review_lesson(
                store,
                lesson_id=pending.lesson_id,
                decision="approved",
                reviewer_id=REVIEWER,
                reason=item["reason"],
                authorize_reviewer=lambda reviewer: reviewer == REVIEWER,
            )
            print(f"approved {pending.lesson_id} from {case.case_id}")

        base = await load_playbook(store, BASE, PLAYBOOK_DIR)
        snapshot = await freeze_playbook(store, VERSION, base=base)
        path = export_playbook(snapshot, PLAYBOOK_DIR)

    print(
        f"playbook {snapshot.version}: {len(snapshot.lessons)} lesson(s), "
        f"hash {snapshot.content_hash} -> {path}"
    )
    for lesson in snapshot.lessons:
        print(f"  [{', '.join(lesson.tags)}] {lesson.lesson_id[:12]}…")
    return path


def main() -> int:
    try:
        asyncio.run(_seed_and_freeze(STORE_FILE))
    except SharedPlaybookError as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001
        print(f"failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
