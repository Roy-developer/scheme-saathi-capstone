"""Run offline-runnable Role 5 red-team checks against current defences."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = PROJECT_ROOT / "eval" / "red_team" / "attacks_v0.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "red_team_dev_latest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Execute runnable red-team checks (injection screen, ID mask, "
            "truthful eligibility). Stub attacks are reported as skipped."
        )
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from eval.harness.red_team_runner import (
        evaluate_red_team_suite,
        load_red_team_suite,
    )
    from eval.harness.runner import write_report

    suite = load_red_team_suite(args.suite)
    report = evaluate_red_team_suite(suite)
    write_report(report, args.output)

    summary = {
        "suite_version": report["suite_version"],
        "attack_count": report["attack_count"],
        "runnable_count": report["runnable_count"],
        "stub_skipped": report["stub_skipped"],
        "passed": report["passed"],
        "failed": report["failed"],
        "pass_rate": report["pass_rate"],
        "output": str(args.output),
    }
    print(json.dumps(summary, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
