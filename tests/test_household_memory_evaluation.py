from eval.harness.household_memory import memory_on_off_report


def test_memory_on_off_smoke_reuses_only_consented_facts_without_changing_verdict():
    report = memory_on_off_report()

    assert report["model_calls"] == 0
    assert report["persona_count"] == 1
    assert report["summary"]["verdict_agreement_rate"] == 1.0
    assert report["summary"]["memory_on_reused_fact_count"] == 2
    assert report["summary"]["memory_off_reused_fact_count"] == 0
    assert report["summary"]["questions_avoided"] > 0
    assert report["cases"][0]["memory_off"]["reused_fact_count"] == 0
    assert "not independent validation" in report["claim_boundary"]
