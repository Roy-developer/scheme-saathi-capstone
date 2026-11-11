"""Role 5 helpers for Reflexion playbook evaluation (E3 foundation).

Paid before/after extraction scoring still goes through
``python -m src.rule_extraction_reflexion.scheme_rules evaluate``.
This module verifies the committed playbook, inventories check-split cases,
and can compare two offline ``PlaybookEvaluation`` reports (no LLM required).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from src.rule_extraction_reflexion.models import PlaybookEvaluation, PlaybookSnapshot
from src.rule_extraction_reflexion.playbook import verify_playbook


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAYBOOK = PROJECT_ROOT / "data" / "schemes" / "playbooks" / "1.0.0.json"
DEFAULT_CASES = PROJECT_ROOT / "data" / "schemes" / "rule_extraction_cases_dev.json"


def load_and_verify_playbook(path: Path = DEFAULT_PLAYBOOK) -> PlaybookSnapshot:
    """Load a committed playbook and refuse a broken content hash."""

    snapshot = PlaybookSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    verify_playbook(snapshot)
    return snapshot


def list_check_cases(cases_path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    """Return development ``check``-split clause cases used for E3 measurement."""

    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    return [
        {
            "package": entry["package"],
            "clause_id": entry["clause_id"],
            "topic_tags": list(entry.get("topic_tags", [])),
            "split": entry.get("split"),
        }
        for entry in payload["cases"]
        if entry.get("split") == "check"
    ]


def playbook_inventory(
    playbook_path: Path = DEFAULT_PLAYBOOK,
    cases_path: Path = DEFAULT_CASES,
) -> dict[str, Any]:
    """Summarize the frozen playbook and check-split measurement set."""

    snapshot = load_and_verify_playbook(playbook_path)
    check_cases = list_check_cases(cases_path)
    return {
        "playbook_version": snapshot.version,
        "playbook_hash": snapshot.content_hash,
        "lesson_count": len(snapshot.lessons),
        "lessons": [
            {
                "lesson_id": lesson.lesson_id,
                "tags": list(lesson.tags),
                "reviewer_id": lesson.reviewer_id,
                "instruction": lesson.instruction,
                "when_to_apply": lesson.when_to_apply,
                "review_reason": lesson.review_reason,
            }
            for lesson in snapshot.lessons
        ],
        "check_case_count": len(check_cases),
        "check_cases": check_cases,
        "paid_evaluate_commands": {
            "before": (
                "python -m src.rule_extraction_reflexion.scheme_rules evaluate "
                "--split check --runs 3 --yes"
            ),
            "after": (
                "python -m src.rule_extraction_reflexion.scheme_rules evaluate "
                "--split check --playbook 1.0.0 --runs 3 --yes"
            ),
        },
        "note": (
            "E3 paid runs use development check cases until Role 5 authorizes a "
            "protected held-out extraction set. Inclusion-clause checks will not "
            "retrieve the current exclusion_clause lesson."
        ),
    }


def compare_playbook_evaluations(
    before: PlaybookEvaluation | Mapping[str, Any],
    after: PlaybookEvaluation | Mapping[str, Any],
) -> dict[str, Any]:
    """Compare exact-match rates and per-case regressions between two runs."""

    before_model = (
        before if isinstance(before, PlaybookEvaluation)
        else PlaybookEvaluation.model_validate(before)
    )
    after_model = (
        after if isinstance(after, PlaybookEvaluation)
        else PlaybookEvaluation.model_validate(after)
    )

    before_by_id = {item.case_id: item for item in before_model.results}
    after_by_id = {item.case_id: item for item in after_model.results}
    shared = sorted(set(before_by_id) & set(after_by_id))
    improved = [
        case_id for case_id in shared
        if not before_by_id[case_id].exact_match and after_by_id[case_id].exact_match
    ]
    regressed = [
        case_id for case_id in shared
        if before_by_id[case_id].exact_match and not after_by_id[case_id].exact_match
    ]
    unchanged_pass = [
        case_id for case_id in shared
        if before_by_id[case_id].exact_match and after_by_id[case_id].exact_match
    ]
    return {
        "before": {
            "playbook_version": before_model.playbook_version,
            "exact_match_count": before_model.exact_match_count,
            "case_count": before_model.case_count,
            "exact_match_rate": round(
                before_model.exact_match_count / before_model.case_count, 4
            )
            if before_model.case_count
            else 0.0,
        },
        "after": {
            "playbook_version": after_model.playbook_version,
            "exact_match_count": after_model.exact_match_count,
            "case_count": after_model.case_count,
            "exact_match_rate": round(
                after_model.exact_match_count / after_model.case_count, 4
            )
            if after_model.case_count
            else 0.0,
        },
        "improved_case_ids": improved,
        "regressed_case_ids": regressed,
        "unchanged_pass_case_ids": unchanged_pass,
        "delta_exact_matches": (
            after_model.exact_match_count - before_model.exact_match_count
        ),
    }
