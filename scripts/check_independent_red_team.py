"""Gate for the independent red-team subset sheet.

Reports progress honestly. Never treats a blank or partially filled sheet as
an independent PDF claim. Exit codes:

- 0: consistent sheet (blank, mid-flight, or fully claimable)
- 2: inconsistent / dishonest metadata
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHEET = (
    PROJECT_ROOT / "eval" / "red_team" / "independent_subset_v1_blank.json"
)
APPROVED = "approved_for_implementation"


def _filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def assess_sheet(data: dict[str, Any]) -> dict[str, Any]:
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("sheet needs a non-empty rows list")

    priority = data.get("priority_attack_ids") or []
    if priority:
        have = {row.get("attack_id") for row in rows}
        missing = [aid for aid in priority if aid not in have]
        if missing:
            raise ValueError(f"missing priority attack_ids: {missing}")

    errors: list[str] = []
    authored = 0
    brief_approved = 0
    execution_accepted = 0

    for row in rows:
        aid = row.get("attack_id") or "<missing id>"
        author = row.get("author")
        reviewed_by = row.get("reviewed_by")
        review_status = row.get("review_status")
        input_text = row.get("independent_attack_input")
        expected = row.get("independent_expected_behaviour")
        attest = row.get("did_not_consult_v0_expected_behaviour")
        authored_on = row.get("authored_on")
        ev = row.get("execution_validation") or {}

        has_content = _filled(input_text) or _filled(expected) or _filled(author)
        complete_author = all(
            [
                _filled(input_text),
                _filled(expected),
                _filled(author),
                _filled(authored_on),
                attest is True,
            ]
        )
        if has_content and not complete_author:
            errors.append(
                f"{aid}: partial author fields — need input, expected_behaviour, "
                "author, authored_on, and did_not_consult_v0_expected_behaviour=true"
            )
        if complete_author:
            authored += 1

        if review_status is not None or _filled(reviewed_by):
            if not complete_author:
                errors.append(f"{aid}: review metadata requires a complete author pass")
            if not _filled(reviewed_by):
                errors.append(f"{aid}: review_status requires reviewed_by")
            if _filled(author) and _filled(reviewed_by) and (
                str(author).casefold() == str(reviewed_by).casefold()
            ):
                errors.append(f"{aid}: author and reviewed_by must differ")
            if review_status == APPROVED and not complete_author:
                errors.append(f"{aid}: cannot approve without complete author fields")

        if review_status == APPROVED and complete_author and _filled(reviewed_by):
            brief_approved += 1

        accepted = ev.get("accepted")
        if accepted is not None or any(
            _filled(ev.get(key))
            for key in ("validator", "validated_on", "run_report", "note")
        ):
            if accepted is not True:
                if accepted is False:
                    pass  # explicit reject is OK mid-flight
                else:
                    errors.append(
                        f"{aid}: execution_validation partially filled; "
                        "set accepted true/false"
                    )
            else:
                if not all(
                    _filled(ev.get(key))
                    for key in ("validator", "validated_on", "run_report")
                ):
                    errors.append(
                        f"{aid}: accepted execution_validation needs "
                        "validator, validated_on, run_report"
                    )
                elif review_status != APPROVED:
                    errors.append(
                        f"{aid}: execution accepted before brief "
                        f"{APPROVED!r}"
                    )
                else:
                    execution_accepted += 1

    n = len(rows)
    if errors:
        status = "inconsistent"
    elif execution_accepted == n and brief_approved == n and authored == n:
        status = "independent_subset_claimable"
    elif brief_approved == n and authored == n:
        status = "briefs_approved_awaiting_execution_validation"
    elif authored == n:
        status = "ready_for_brief_review"
    elif authored == 0 and brief_approved == 0 and execution_accepted == 0:
        status = "blank_pending_author"
    else:
        status = "in_progress"

    return {
        "sheet": str(data.get("sheet_version")),
        "status": status,
        "row_count": n,
        "authored_complete": authored,
        "briefs_approved": brief_approved,
        "execution_accepted": execution_accepted,
        "claimable": status == "independent_subset_claimable",
        "errors": errors,
        "note": (
            "Independent subset is claimable."
            if status == "independent_subset_claimable"
            else "Not an independent PDF claim yet; see eval/red_team/INDEPENDENT_VALIDATION.md."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    args = parser.parse_args(argv)

    data = json.loads(args.sheet.read_text(encoding="utf-8"))
    try:
        report = assess_sheet(data)
    except ValueError as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, indent=2))
        return 2

    print(json.dumps(report, indent=2))
    return 2 if report["status"] == "inconsistent" else 0


if __name__ == "__main__":
    raise SystemExit(main())
