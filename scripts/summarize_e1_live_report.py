"""Rebuild an E1 comparative summary from an existing live observations report.

Normalizes ``cant_tell`` → ``need_more_information`` when scoring. Does not call
a model. Used to record the team-override development comparison without a
re-paid run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "eval" / "reports" / "e1_live_dev.json"
DEFAULT_OUT = ROOT / "eval" / "reports" / "e1_team_override_comparison_2026-11-14.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from scripts.run_e1_live import (
        TEAM_OVERRIDE_LABEL,
        frozen_budget_pins,
        normalize_verdict,
        summarize_observations,
    )

    raw = json.loads(args.source.read_text(encoding="utf-8"))
    observations: list[dict] = []
    for row in raw.get("observations") or []:
        expected = normalize_verdict(row.get("expected_result"))
        actual = normalize_verdict(row.get("actual_result"))
        error = row.get("error")
        observations.append({
            **row,
            "expected_result": expected,
            "actual_result": actual,
            "task_success": error is None and actual == expected,
        })
    per_arm = summarize_observations(observations)
    report = {
        "label": TEAM_OVERRIDE_LABEL,
        "claim_level": "team_override_dev_personas",
        "source_report": str(args.source.relative_to(ROOT)),
        "no_new_model_calls": True,
        "model_id": raw.get("model_id"),
        "c1_path_at_source": (
            "ad-hoc create_agent evaluate tool "
            "(superseded by journey.single_agent_provider in run_e1_live.py)"
        ),
        "budget_pins": frozen_budget_pins(),
        "cases": raw.get("cases"),
        "observation_count": len(observations),
        "per_arm": per_arm,
        "total_cost_usd": round(
            sum(float(row.get("cost_usd") or 0) for row in observations), 8
        ),
        "interpretation": (
            "C0/C1/C2 task_success rates match on this synthetic evaluate set; "
            "C2 costs more model calls/tokens than C1. Does not establish a "
            "specialist-team quality benefit. Not PDF held-out."
        ),
        "remaining_for_pdf": [
            "protected held-out eval set",
            "owner-signed E1 thresholds beyond lead report-only",
            "fresh live run on journey-wired C1 under freeze pins",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "per_arm": {
        arm: {"task_success": row["task_success"], "cost_usd": row["cost_usd"]}
        for arm, row in per_arm.items()
    }}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
