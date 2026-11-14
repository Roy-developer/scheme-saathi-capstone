"""Freeze playbook 1.1.1: keep 1.1.0 lessons + two accuracy lessons.

Adds:
- APY inclusion: extract every condition (age, citizenship, savings account)
- PM-KISAN exclusion boolean: threshold encoded in fact name -> eq false, not gte

Does not spend model budget. Safe if 1.1.1 is not already shared.
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
VERSION = "1.1.1"
BASE = "1.1.0"

NEW_LESSONS = (
    {
        "clause_id": "APY-IN-ELIGIBILITY-01",
        "instruction": (
            "When an inclusion clause states several conditions across one or "
            "more sentences (for example an age range, citizenship, and having "
            "a savings bank account), write a separate rule for each condition. "
            "Do not stop after the age bounds."
        ),
        "when_to_apply": (
            "Any inclusion clause that combines age limits with other "
            "eligibility conditions such as citizenship or account ownership."
        ),
        "reason": (
            "Accuracy fix for APY-IN-ELIGIBILITY-01: model often omitted "
            "citizen and savings-bank rules after extracting age."
        ),
    },
    {
        "clause_id": "PMKISAN-GUIDELINES-2020-4.1(b)(iv)",
        "instruction": (
            "When an exclusion clause mentions a money threshold (for example "
            "monthly pension Rs.10,000 or more) but the allowed fact is a "
            "boolean whose name already encodes that threshold, write that "
            "fact as eq false for the excluded group. Do not invent gte/lte "
            "numeric operators on that boolean field."
        ),
        "when_to_apply": (
            "Exclusion clauses about pension or similar thresholds mapped to "
            "boolean facts such as pension_at_least_10000_excluding_stated_grades."
        ),
        "reason": (
            "Accuracy fix for PMKISAN-GUIDELINES-2020-4.1(b)(iv): model often "
            "wrote gte 10000 on a boolean exclusion fact."
        ),
    },
)


async def _seed_and_freeze(store_path: Path) -> Path:
    shared = PLAYBOOK_DIR / f"{VERSION}.json"
    if shared.exists():
        raise SharedPlaybookError(
            f"Playbook {VERSION} is already shared at {shared}; freeze a new version."
        )

    # Prefer team_override file so APY clause is present; fall back to all splits.
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
