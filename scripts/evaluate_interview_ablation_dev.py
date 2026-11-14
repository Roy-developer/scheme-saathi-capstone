"""E4 (question order) and language parity on development personas, code only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from eval.harness.interview_sim import run_interview_ablation
    from eval.harness.runner import load_persona_evaluation_set

    report = run_interview_ablation(load_persona_evaluation_set(
        ROOT / "eval" / "development" / "personas_v1.json"))
    out = ROOT / "eval" / "reports" / "interview_ablation_dev_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    return 0 if report["parity_breaks"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
