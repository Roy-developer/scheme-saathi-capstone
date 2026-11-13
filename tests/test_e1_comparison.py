"""Focused tests for E1 comparability gates and honest metric reporting."""

from eval.harness.e1_runner import (
    ArmControls,
    BudgetCeilings,
    CaseObservation,
    DevelopmentSetControls,
    TokenPricing,
    build_report,
    comparability_blockers,
    shared_budget_ceilings,
    shared_single_agent_capabilities,
)


_BUDGET = shared_budget_ceilings()
_CAPABILITIES = shared_single_agent_capabilities()
_DATASET = DevelopmentSetControls(
    split="development", protected=False, synthetic_only=True,
)


def _arms(
    *,
    c1_model: str = "offline-script-v1",
    c2_model: str = "offline-script-v1",
    c2_budget: BudgetCeilings = _BUDGET,
) -> tuple[ArmControls, ...]:
    return (
        ArmControls(
            "C0", None, "none", _CAPABILITIES, _BUDGET,
            "rule_engine", "separate_exact_human_approval",
        ),
        ArmControls(
            "C1", c1_model, "scripted", _CAPABILITIES, _BUDGET,
            "rule_engine", "separate_exact_human_approval",
        ),
        ArmControls(
            "C2", c2_model, "scripted", _CAPABILITIES, c2_budget,
            "rule_engine", "separate_exact_human_approval",
        ),
    )


def test_e1_blocks_mismatched_model_tools_or_budget() -> None:
    """Do not compare arms when a required shared control is unavailable."""

    arms = _arms(
        c1_model="model-a",
        c2_model="model-b",
        c2_budget=BudgetCeilings(8, 24, 23, 12, 12_000),
    )
    blockers = comparability_blockers(arms, _DATASET)
    assert any("same nonempty model" in blocker for blocker in blockers)
    assert any("ceilings must match" in blocker for blocker in blockers)

    wrong_tools = list(arms)
    wrong_tools[1] = ArmControls(
        "C1", "model-a", "scripted", frozenset({"eligibility"}),
        _BUDGET, "rule_engine", "separate_exact_human_approval",
    )
    assert any(
        "capabilities must be equivalent"
        in blocker
        for blocker in comparability_blockers(tuple(wrong_tools), _DATASET)
    )


def test_e1_reports_scripted_outcomes_without_quality_or_cost_claims() -> None:
    """Scripted model results are functional checks, not efficacy evidence."""

    rows = (
        CaseObservation(
            "DEV-001", "C0", True, "deterministic_workflow", 0, 10.0,
            0, 5, None, None, "unknown",
        ),
        CaseObservation(
            "DEV-001", "C1", True, "scripted_model", 0, 25.0,
            2, 5, 400, 40, "estimated",
        ),
        CaseObservation(
            "DEV-001", "C2", True, "scripted_model", 0, 30.0,
            3, 5, 500, 60, "unknown",
        ),
    )
    report = build_report(
        _arms(), _DATASET, rows, expected_case_ids=("DEV-001",),
    )

    assert report["status"] == "observed"
    assert report["model_quality_claim"] == (
        "not_measured_scripted_outputs_are_functional_tests_only"
    )
    assert report["arms"]["C1"]["task_success_rate"] == 1
    assert report["arms"]["C1"]["input_tokens"] is None
    assert report["arms"]["C1"]["cost_usd"] is None
    assert report["arms"]["C1"]["latency_ms"]["median"] == 25.0
    assert report["arms"]["C1"]["policy_violations"] == 0


def test_e1_prices_only_provider_reported_tokens_with_pinned_model_rates() -> None:
    """Estimated token reservations never become measured usage or cost."""

    rows = (
        CaseObservation(
            "DEV-001", "C0", True, "deterministic_workflow", 0, 15.0,
            0, 5, None, None, "unknown",
        ),
        CaseObservation(
            "DEV-001", "C1", True, "live_model", 0, 20.0,
            2, 5, 1_000, 500, "actual",
        ),
        CaseObservation(
            "DEV-001", "C2", True, "live_model", 0, 40.0,
            3, 5, 2_000, 1_000, "actual",
        ),
    )
    report = build_report(
        _arms(
            c1_model="model-pinned",
            c2_model="model-pinned",
        ),
        _DATASET,
        rows,
        expected_case_ids=("DEV-001",),
        pricing=TokenPricing("model-pinned", 1.0, 2.0),
    )

    assert report["arms"]["C1"]["input_tokens"] == 1_000
    assert report["arms"]["C1"]["output_tokens"] == 500
    assert report["arms"]["C1"]["cost_usd"] == 0.002
    assert report["arms"]["C2"]["latency_ms"]["p95"] == 40.0
    assert report["arms"]["C0"]["cost_usd"] == 0.0


def test_e1_blocks_incomplete_arm_results() -> None:
    """Missing cases cannot be mistaken for a complete comparison."""

    report = build_report(
        _arms(),
        _DATASET,
        (
            CaseObservation(
                "DEV-001", "C0", True, "deterministic_workflow", 0, 10.0,
                0, 5, None, None, "unknown",
            ),
        ),
        expected_case_ids=("DEV-001", "DEV-002"),
    )
    assert report["status"] == "blocked"
    assert report["complete"] is False
    assert any("exactly one observation" in item for item in report["blockers"])
