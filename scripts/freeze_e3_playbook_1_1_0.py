"""Freeze and export Reflexion playbook 1.1.0 for E3 PDF path.

Seeds the two inclusion lessons approved in
``docs/e3_lesson_decision_2026-11-13.md`` (IGNWPS, IGNOAPS), keeps the
exclusion lesson from playbook 1.0.0 via ``--base 1.0.0``, then writes
``data/schemes/playbooks/1.1.0.json``.

IGNDPS is intentionally omitted (rejected). Does not run evaluate or spend
budget. Safe to re-run only if 1.1.0 is not already shared.
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
VERSION = "1.1.0"
BASE = "1.0.0"

# Exact approved draft text from docs/lesson_drafts_inclusion_2026-11-13.md
# (decision: docs/e3_lesson_decision_2026-11-13.md).
APPROVED_INCLUSION = (
    {
        "clause_id": "IGNWPS-MH-ELIGIBILITY-01",
        "instruction": (
            'When a clause gives an age range written as "X to Y years", write '
            "two separate rules: an inclusive lower bound (gte X) and an "
            "inclusive upper bound (lte Y). Do not write the range as one rule. "
            'Map a "family falls under Below Poverty Line" condition to the '
            "BPL card fact (`bpl_card_shown`), not to a list-membership fact."
        ),
        "when_to_apply": (
            "Any inclusion clause that combines a category (for example, a "
            "widow), an age range, and a BPL condition on the family."
        ),
        "reason": (
            "Approved unchanged per docs/e3_lesson_decision_2026-11-13.md "
            "(Roy-developer)."
        ),
    },
    {
        "clause_id": "IGNOAPS-MH-ELIGIBILITY-01",
        "instruction": (
            'When a clause says "aged N and above", write one inclusive '
            "lower-bound rule (gte N) and no upper bound. When a clause says a "
            'person\'s "names are on the ... list", map the condition to the '
            "list-membership fact (`name_on_bpl_list`, eq true), not to a "
            "card-shown fact. The two BPL facts are different and must not be "
            "used interchangeably."
        ),
        "when_to_apply": (
            'Any inclusion clause that states an "and above" age threshold '
            "together with a condition that the person's name appears on a list."
        ),
        "reason": (
            "Approved unchanged per docs/e3_lesson_decision_2026-11-13.md "
            "(Roy-developer)."
        ),
    },
)


async def _seed_and_freeze(store_path: Path) -> Path:
    shared = PLAYBOOK_DIR / f"{VERSION}.json"
    if shared.exists():
        raise SharedPlaybookError(
            f"Playbook {VERSION} is already shared at {shared}; freeze a new version."
        )

    by_id = {case.case_id: case for case in build_cases()}
    store_path.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteStore.from_conn_string(str(store_path)) as store:
        await store.setup()
        for item in APPROVED_INCLUSION:
            case = by_id[item["clause_id"]]
            # Provenance only: lesson teaches the gold mapping; no fake mismatch.
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
    except Exception as error:  # noqa: BLE001 — CLI boundary
        print(f"failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
