"""Held-out evaluation run step. Dry run by default. Never makes a model call.

The run is refused unless every gate in check_held_out_gate.py passes.

Default (dry run): prints only counts per scheme and per intended category.
--execute: runs the deterministic rule engine on each held-out case, with no
model calls, and writes eval/reports/held_out_rule_engine.json with IDs and
results only, never applicant answers.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from check_held_out_gate import gate_failures  # noqa: E402

HELD_OUT_FILE = PROJECT_ROOT / "eval" / "held_out" / "local" / "personas_held_out_v2.json"
REPORT = PROJECT_ROOT / "eval" / "reports" / "held_out_rule_engine.json"


def run_rule_engine(cases: list[dict]) -> int:
    """Run the deterministic rule engine on each case. No model calls. IDs and results only."""

    from eval.harness.runner import typed_fact_store
    from src.api.eligibility import evaluate_mock_eligibility
    from src.rules.data_provider import RulePackageProvider

    provider = RulePackageProvider()
    registry = provider.registry
    results = []
    for case in cases:
        package = provider.packages[case["scheme_id"]]
        profile = typed_fact_store(case["answers"], registry)
        actual = evaluate_mock_eligibility(profile, package, registry=registry).result
        results.append({
            "id": case["id"],
            "scheme_id": case["scheme_id"],
            "intended_category": case["intended_category"],
            "engine_result": actual,
            "matches_intended": actual == case["intended_category"],
            "matches_stored_expected": actual == case["expected"]["result"],
        })

    summary = {
        "cases": len(results),
        "matches_intended": sum(r["matches_intended"] for r in results),
        "matches_stored_expected": sum(r["matches_stored_expected"] for r in results),
        "mismatched_intended": [r["id"] for r in results if not r["matches_intended"]],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "mode": "held_out_rule_engine_deterministic_no_model_calls",
        "note": "Rule-engine results only. Not an LLM result and not independent evidence of model quality.",
        "summary": summary,
        "results": results,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(f"Rule engine ran on {summary['cases']} held-out cases (no model calls).")
    print(f"  matches intended category: {summary['matches_intended']} of {summary['cases']}")
    print(f"  matches stored expected: {summary['matches_stored_expected']} of {summary['cases']}")
    print(f"  mismatched intended IDs: {summary['mismatched_intended']}")
    print(f"Report written to {REPORT.relative_to(PROJECT_ROOT)} (IDs and results only).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Refuse unless the gate passes. Summarise counts, or run the rule engine with --execute."""

    args = list(sys.argv[1:] if argv is None else argv)
    failures = gate_failures()
    if failures:
        print("HELD-OUT RUN REFUSED. Gates failed:")
        for item in failures:
            print(f"  - {item}")
        return 1

    cases = json.loads(HELD_OUT_FILE.read_text(encoding="utf-8"))["cases"]
    excluded = set(json.loads((PROJECT_ROOT / "eval" / "not_evaluable.json").read_text(encoding="utf-8"))["excluded_cases"])
    cases = [c for c in cases if c["id"] not in excluded]
    print(f"Excluded as not evaluable: {len(excluded)} cases (IGNDPS-MH, pending review).")
    by_scheme = Counter(c["scheme_id"] for c in cases)
    by_intent = Counter(c["intended_category"] for c in cases)
    print(f"Gate passed. Held-out cases: {len(cases)}")
    print(f"  per scheme: {dict(by_scheme)}")
    print(f"  per intended category: {dict(by_intent)}")
    print("No model calls are made by this step.")

    if "--execute" in args:
        return run_rule_engine(cases)
    print("Dry run only. Add --execute to run the rule engine (no model calls).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
