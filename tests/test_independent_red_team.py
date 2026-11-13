"""Independent red-team subset sheet gate."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.check_independent_red_team import assess_sheet, main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHEET = PROJECT_ROOT / "eval" / "red_team" / "independent_subset_v1_blank.json"


def test_blank_sheet_is_pending_not_claimable():
    data = json.loads(SHEET.read_text(encoding="utf-8"))
    report = assess_sheet(data)
    assert report["status"] == "blank_pending_author"
    assert report["claimable"] is False
    assert report["authored_complete"] == 0
    assert main(["--sheet", str(SHEET)]) == 0


def test_author_equals_reviewer_is_inconsistent():
    data = json.loads(SHEET.read_text(encoding="utf-8"))
    row = copy.deepcopy(data["rows"][0])
    row.update(
        {
            "independent_attack_input": "synthetic attack",
            "independent_expected_behaviour": "deny without disclosure",
            "author": "vivian",
            "authored_on": "2026-11-14",
            "did_not_consult_v0_expected_behaviour": True,
            "reviewed_by": "Vivian",
            "reviewed_on": "2026-11-14",
            "review_status": "approved_for_implementation",
        }
    )
    data["rows"] = [row] + data["rows"][1:]
    report = assess_sheet(data)
    assert report["status"] == "inconsistent"
    assert any("must differ" in err for err in report["errors"])


def test_full_signoff_is_claimable():
    data = json.loads(SHEET.read_text(encoding="utf-8"))
    filled = []
    for row in data["rows"]:
        item = copy.deepcopy(row)
        item.update(
            {
                "independent_attack_input": f"synthetic for {row['attack_id']}",
                "independent_expected_behaviour": "fail closed on this boundary",
                "author": "independent-author",
                "authored_on": "2026-11-14",
                "did_not_consult_v0_expected_behaviour": True,
                "reviewed_by": "brief-reviewer",
                "reviewed_on": "2026-11-14",
                "review_status": "approved_for_implementation",
                "execution_validation": {
                    "validator": "execution-validator",
                    "validated_on": "2026-11-14",
                    "run_report": "eval/reports/example.json",
                    "accepted": True,
                    "note": "observations match brief",
                },
            }
        )
        filled.append(item)
    data["rows"] = filled
    report = assess_sheet(data)
    assert report["status"] == "independent_subset_claimable"
    assert report["claimable"] is True
    assert report["execution_accepted"] == len(filled)
