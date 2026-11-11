"""Score a protected held-out persona set (Role-5-only environment)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = (
    PROJECT_ROOT / "eval" / "held_out" / "local" / "personas_held_out_v1.json"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "eligibility_held_out_latest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_SET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.eval_set.exists():
        raise SystemExit(
            f"Held-out set not found: {args.eval_set}. "
            "Generate with: python scripts/generate_held_out_personas.py"
        )

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from eval.harness.runner import (
        evaluate_persona_set,
        load_persona_evaluation_set,
        write_report,
    )

    evaluation_set = load_persona_evaluation_set(args.eval_set, allow_held_out=True)
    report = evaluate_persona_set(evaluation_set)
    write_report(report, args.output)
    summary = {
        "dataset_version": report["dataset_version"],
        "split": report["split"],
        "protected": report["protected"],
        "case_count": report["case_count"],
        "accuracy": report["accuracy"],
        "incorrect": report["incorrect"],
        "output": str(args.output),
        "warning": (
            "Held-out results must not be used to tune the system. "
            "If they are, reclassify those cases as development."
        ),
    }
    print(json.dumps(summary, indent=2))
    return 0 if report["incorrect"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
