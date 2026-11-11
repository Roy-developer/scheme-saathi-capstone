"""Inventory the frozen Reflexion playbook and compare offline E3 reports.

Paid extraction scoring is intentionally separate:

    python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check --runs 3 --yes
    python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check --playbook 1.0.0 --runs 3 --yes

This script verifies the committed playbook, lists check-split cases, and can
diff two saved ``PlaybookEvaluation`` JSON reports without calling a model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "reflexion_e3_inventory.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Reflexion playbook 1.0.0 and prepare E3 inventory."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Where to write the inventory JSON",
    )
    parser.add_argument(
        "--before",
        type=Path,
        default=None,
        help="Optional PlaybookEvaluation JSON from evaluate without playbook",
    )
    parser.add_argument(
        "--after",
        type=Path,
        default=None,
        help="Optional PlaybookEvaluation JSON from evaluate with playbook 1.0.0",
    )
    args = parser.parse_args(argv)

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from eval.harness.reflexion_e3 import (
        compare_playbook_evaluations,
        playbook_inventory,
    )
    from eval.harness.runner import write_report

    report = playbook_inventory()
    if args.before is not None or args.after is not None:
        if args.before is None or args.after is None:
            raise SystemExit("Provide both --before and --after report paths")
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
        # Accept either a raw PlaybookEvaluation or a wrapper with "evaluation".
        before_eval = before.get("evaluation", before)
        after_eval = after.get("evaluation", after)
        report["comparison"] = compare_playbook_evaluations(before_eval, after_eval)

    write_report(report, args.output)
    summary = {
        "playbook_version": report["playbook_version"],
        "lesson_count": report["lesson_count"],
        "check_case_count": report["check_case_count"],
        "output": str(args.output),
    }
    if "comparison" in report:
        summary["comparison"] = {
            "delta_exact_matches": report["comparison"]["delta_exact_matches"],
            "improved": report["comparison"]["improved_case_ids"],
            "regressed": report["comparison"]["regressed_case_ids"],
        }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
