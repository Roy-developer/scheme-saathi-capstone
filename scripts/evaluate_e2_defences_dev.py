"""Run offline E2 defences off/on against the red-team suite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = PROJECT_ROOT / "eval" / "red_team" / "attacks_v0.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "e2_defences_dev_latest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from eval.harness.e2_runner import run_e2_defences
    from eval.harness.red_team_runner import load_red_team_suite
    from eval.harness.runner import write_report

    report = run_e2_defences(load_red_team_suite(args.suite))
    write_report(report, args.output)
    summary = {
        "experiment_id": report["experiment_id"],
        "defences_off_attack_success_rate": report["defences_off"]["attack_success_rate"],
        "defences_on_attack_success_rate": report["defences_on"]["attack_success_rate"],
        "defences_on_defence_hold_rate": report["defences_on"]["defence_hold_rate"],
        "output": str(args.output),
    }
    print(json.dumps(summary, indent=2))
    # Gate: with defences on, attack success should be 0 for the offline subset.
    on_rate = report["defences_on"]["attack_success_rate"]
    return 0 if on_rate == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
