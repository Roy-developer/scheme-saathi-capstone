"""Compute dual-label agreement / Cohen's κ on a persona set.

By default copies ``role5-seed`` labels to ``role5-seed-smoke-b`` so the κ
harness can be smoke-tested. Replace with independent Role 1 labels before
claiming PDF dual-labelling.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "label_agreement_dev_latest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_SET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--labeller-a", default="role5-seed")
    parser.add_argument("--labeller-b", default="role5-seed-smoke-b")
    parser.add_argument(
        "--smoke-copy",
        action="store_true",
        default=True,
        help="Copy labeller-a labels to labeller-b for κ smoke (default on)",
    )
    parser.add_argument(
        "--no-smoke-copy",
        action="store_false",
        dest="smoke_copy",
        help="Require both labellers to already exist on the set",
    )
    args = parser.parse_args(argv)

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from eval.harness.agreement import (
        agreement_report,
        attach_second_labeller_copy,
    )
    from eval.harness.runner import load_persona_evaluation_set, write_report

    evaluation_set = load_persona_evaluation_set(args.eval_set)
    if args.smoke_copy:
        evaluation_set = attach_second_labeller_copy(
            evaluation_set,
            source_labeller=args.labeller_a,
            second_labeller=args.labeller_b,
        )
    report = agreement_report(
        evaluation_set,
        labeller_a=args.labeller_a,
        labeller_b=args.labeller_b,
    )
    report["smoke_copy"] = args.smoke_copy
    write_report(report, args.output)
    print(json.dumps(
        {
            "paired_label_count": report["paired_label_count"],
            "cohens_kappa": report["cohens_kappa"],
            "agreement_rate": report["agreement_rate"],
            "note": report["note"],
            "output": str(args.output),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
