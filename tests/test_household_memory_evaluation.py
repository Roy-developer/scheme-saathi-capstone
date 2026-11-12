from eval.harness.household_memory import memory_on_off_report


def test_memory_on_off_cases_reuse_only_consented_facts_without_changing_verdicts():
    report = memory_on_off_report()

    assert report["model_calls"] == 0
    assert report["case_count"] == 4
    assert report["summary"]["case_count"] == 4
    assert report["summary"]["verdict_agreement_rate"] == 1.0
    assert report["summary"]["verdict_agreement_count"] == 4
    assert report["summary"]["memory_on_reused_fact_count"] == 8
    assert report["summary"]["memory_off_reused_fact_count"] == 0
    assert report["summary"]["questions_avoided"] > 0
    assert all(case["memory_on"]["reused_fact_count"] == 2 for case in report["cases"])
    assert all(case["memory_off"]["reused_fact_count"] == 0 for case in report["cases"])
    assert all(case["verdicts_match"] for case in report["cases"])
    assert "not independent validation" in report["claim_boundary"]
