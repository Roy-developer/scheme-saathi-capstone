"""Run the deterministic synthetic household-memory on/off smoke."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare synthetic journey behavior with memory on and off."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "eval" / "reports" / "memory_on_off_dev_latest.json",
    )
    args = parser.parse_args()
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from eval.harness.household_memory import memory_on_off_report, write_report

    report = memory_on_off_report()
    write_report(report, args.output)
    print(f"Wrote {args.output}")
    print(report["summary"])
    return 0 if report["summary"]["verdict_agreement_rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
