"""Synthetic development memory-on/off report checks (no model calls)."""

import pytest

from eval.harness.memory_on_off_runner import (
    CASES,
    FORGET_CHECKS,
    _summarise,
    memory_on_off_dev_report,
)


@pytest.fixture(scope="module")
def report():
    return memory_on_off_dev_report()


def test_report_is_synthetic_development_and_makes_no_model_calls(report):
    assert report["model_calls"] == 0
    assert report["split"] == "development"
    assert "SYNTHETIC" in report["label"]
    assert "not independent validation" in report["claim_boundary"].lower()


def test_report_has_at_least_six_cases_with_all_metrics(report):
    assert report["case_count"] == len(CASES) >= 6
    assert len(report["cases"]) == report["case_count"]
    required = {
        "questions_asked_on",
        "questions_asked_off",
        "fact_reuse_on_return",
        "verdict_match",
        "correction_visible_on_return",
        "policy_violations",
        "cross_household_leaks",
        "forget_completeness",
    }
    for case in report["cases"]:
        assert required <= set(case), case["case_id"]


def test_memory_on_reuses_saved_facts_and_asks_fewer_questions(report):
    for case in report["cases"]:
        reuse = case["fact_reuse_on_return"]
        assert reuse["saved"] == 2
        assert reuse["reused"] == reuse["saved"], case["case_id"]
        assert case["questions_asked_on"] <= case["questions_asked_off"], case["case_id"]
    assert sum(c["questions_avoided"] for c in report["cases"]) > 0


def test_verdicts_match_between_memory_on_and_off(report):
    assert all(case["verdict_match"] for case in report["cases"])


def test_corrections_are_visible_on_return(report):
    corrected = [c for c in report["cases"] if c["correction_visible_on_return"] is not None]
    assert len(corrected) >= 2
    assert all(c["correction_visible_on_return"] is True for c in corrected)


def test_no_policy_violations_or_cross_household_leaks(report):
    assert all(case["policy_violations"] == 0 for case in report["cases"])
    assert all(case["cross_household_leaks"] == 0 for case in report["cases"])


def test_forget_is_complete_in_every_case(report):
    assert all(case["forget_completeness"] == 1.0 for case in report["cases"])
    assert FORGET_CHECKS == 4


def test_summary_is_recomputed_from_case_metrics(report):
    assert report["summary"] == _summarise(report["cases"])
    assert report["summary"]["case_count"] == report["case_count"]
    assert report["summary"]["questions_avoided_total"] == sum(
        c["questions_avoided"] for c in report["cases"]
    )
