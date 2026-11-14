"""Language parity and planned-vs-fixed question order (code only)."""

from pathlib import Path

from eval.harness.interview_sim import run_interview_ablation
from eval.harness.runner import load_persona_evaluation_set

DEV = Path(__file__).resolve().parents[1] / "eval" / "development" / "personas_v1.json"


def test_same_persona_gets_same_verdict_in_en_hi_mr_and_planned_asks_fewer():
    report = run_interview_ablation(load_persona_evaluation_set(DEV))
    assert report["case_count"] >= 30
    assert report["parity_breaks"] == 0
    assert report["verdicts_differing_from_expected"] == 0
    means = report["mean_questions"]
    assert means["planned"] < means["fixed"]
    for case in report["cases"]:
        for run in case["runs"].values():
            assert len(set(run["questions"].values())) == 1  # same count per language
