"""Dry-run the E1 harness (C0/C1/C2) offline on development personas.

Uses a scripted fake model: it checks the wiring and metrics, not agent
quality. The report is stamped ``dry_run`` and is not an E1 result.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from eval.harness.dry_run_model import DryRunModel
    from eval.harness.e1_runner import run_e1
    from eval.harness.runner import load_persona_evaluation_set

    evaluation_set = load_persona_evaluation_set(
        ROOT / "eval" / "development" / "personas_v1.json")
    report = asyncio.run(run_e1(evaluation_set, lambda _agent: DryRunModel()))
    out = ROOT / "eval" / "reports" / "e1_dry_run_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for config_id, summary in report["configs"].items():
        print(config_id, {k: (round(v, 1) if isinstance(v, float) else v)
                          for k, v in summary.items() if k != "rows"})
    print("DRY RUN ONLY: scripted model, not an E1 result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
