"""Score development eligibility personas with the deterministic rule engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_SET = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "eligibility_dev_latest.json"


def main(argv: list[str] | None = None) -> int:
    """Load a development persona set, score it, and write a JSON report."""

    parser = argparse.ArgumentParser(
        description=(
            "Evaluate unprotected development personas against mock rule "
            "packages. Rejects held-out / protected sets."
        )
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=DEFAULT_EVAL_SET,
        help="Path to a development persona JSON set",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Where to write the JSON report",
    )
    parser.add_argument(
        "--scheme",
        action="append",
        dest="schemes",
        default=None,
        help="Limit scoring to one scheme ID (repeatable)",
    )
    args = parser.parse_args(argv)

    # Ensure repo-root imports work when run as a script.
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from eval.harness.runner import (
        evaluate_persona_set,
        load_persona_evaluation_set,
        write_report,
    )

    evaluation_set = load_persona_evaluation_set(args.eval_set)
    scheme_ids = set(args.schemes) if args.schemes else None
    report = evaluate_persona_set(evaluation_set, scheme_ids=scheme_ids)
    write_report(report, args.output)

    summary = {
        "dataset_version": report["dataset_version"],
        "case_count": report["case_count"],
        "correct": report["correct"],
        "incorrect": report["incorrect"],
        "accuracy": report["accuracy"],
        "by_scheme": {
            scheme_id: {
                "total": values["total"],
                "accuracy": values["accuracy"],
            }
            for scheme_id, values in report["by_scheme"].items()
        },
        "output": str(args.output),
    }
    print(json.dumps(summary, indent=2))
    return 0 if report["incorrect"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
