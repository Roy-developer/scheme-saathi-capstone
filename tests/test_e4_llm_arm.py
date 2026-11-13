"""Isolation and scoring tests for the E4 LLM eligibility arm."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from eval.harness import e4_llm_arm
from eval.harness.runner import load_persona_evaluation_set, persona_input
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider

SOURCE = Path(e4_llm_arm.__file__)
FORBIDDEN_PREFIXES = (
    "src.workflow.journey",
    "src.workflow.state",
    "src.db",
    "src.storage",
    "sqlite3",
    "langgraph.store",
    "langgraph.checkpoint",
)


def test_llm_arm_module_imports_no_live_state_surfaces():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not name.startswith(FORBIDDEN_PREFIXES), name


def test_package_source_excerpt_includes_unique_source_text():
    package = RulePackageProvider().get("APY-IN")
    text = e4_llm_arm.package_source_excerpt(package)
    assert "citizens of India" in text or "savings bank" in text or "age" in text.lower()
    assert package.scheme_id not in ("",)


def test_scripted_proposer_never_changes_rule_verdicts():
    provider = RulePackageProvider()
    evaluation_set = load_persona_evaluation_set(e4_llm_arm.DEV_PERSONAS)

    def direct_rules():
        rows = []
        for persona in evaluation_set.personas:
            profile = persona_input(persona, provider.registry)
            for scheme_id in persona.expected_by_scheme:
                verdict = evaluate_mock_eligibility(
                    profile, provider.get(scheme_id), registry=provider.registry,
                )
                rows.append((persona.persona_id, scheme_id, verdict.result))
        return rows

    async def always_eligible(_request):
        return "eligible"

    report = asyncio.run(
        e4_llm_arm.run_llm_eligibility_ablation(
            proposer=always_eligible,
            limit=12,
            model_name="scripted-test",
        )
    )
    asserted = [
        (c["persona_id"], c["scheme_id"], c["rule_result"]) for c in report["cases"]
    ]
    assert asserted == direct_rules()[: len(asserted)]
    assert all(c["authoritative"] is False for c in report["cases"])
    assert all(c["written_to_live_state"] is False for c in report["cases"])
    assert report["notice"] == e4_llm_arm.NON_AUTHORITATIVE_NOTICE


def test_boundary_errors_count_llm_disagreement_with_expected():
    async def always_eligible(_request):
        return "eligible"

    report = asyncio.run(
        e4_llm_arm.run_llm_eligibility_ablation(
            proposer=always_eligible,
            limit=20,
            model_name="scripted-test",
        )
    )
    assert report["case_count"] == 20
    assert report["scored_case_count"] == 20
    assert report["provider_error_count"] == 0
    assert report["boundary_error_count_llm"] == sum(
        1 for c in report["cases"] if c["boundary_error_llm"]
    )
    assert report["boundary_error_count_rules"] == sum(
        1 for c in report["cases"] if c["boundary_error_rules"]
    )
    # Scripted "always eligible" must disagree with some non-eligible labels.
    assert report["boundary_error_count_llm"] > 0
    assert (
        report["agree_llm_rules"] + report["disagree_llm_rules"]
        == report["scored_case_count"]
    )


def test_mutating_proposer_cannot_poison_request_for_rules():
    async def mutating(request):
        request["known_facts"].clear()
        request["scheme_source_text"] = "MUTATED"
        return "not_eligible"

    report = asyncio.run(
        e4_llm_arm.run_llm_eligibility_ablation(
            proposer=mutating,
            limit=5,
            model_name="scripted-test",
        )
    )
    provider = RulePackageProvider()
    evaluation_set = load_persona_evaluation_set(e4_llm_arm.DEV_PERSONAS)
    expected_rules = []
    for persona in evaluation_set.personas:
        profile = persona_input(persona, provider.registry)
        for scheme_id in persona.expected_by_scheme:
            expected_rules.append(
                evaluate_mock_eligibility(
                    profile, provider.get(scheme_id), registry=provider.registry,
                ).result
            )
            if len(expected_rules) >= 5:
                break
        if len(expected_rules) >= 5:
            break
    assert [c["rule_result"] for c in report["cases"]] == expected_rules


def test_multilingual_agreement_and_cost_fields():
    async def locale_aware(request):
        # Same result in every locale → full agreement.
        return {
            "result": "eligible",
            "input_tokens": 10,
            "output_tokens": 2,
        }

    report = asyncio.run(
        e4_llm_arm.run_llm_eligibility_ablation(
            proposer=locale_aware,
            limit=3,
            model_name="scripted-test",
            locales=("en", "hi", "mr"),
            pace_seconds=0,
        )
    )
    assert report["model_calls"] == 9
    assert report["verdict_agreement_hi_mr_en"]["cases_scored"] == 3
    assert report["verdict_agreement_hi_mr_en"]["all_three_agree"] == 3
    assert report["verdict_agreement_hi_mr_en"]["rate"] == 1.0
    assert report["cost"]["route"] == "openrouter_free"
    assert report["cost"]["total_usd"] == 0.0
    assert report["cost"]["cost_per_case_usd"] == 0.0
    assert report["cost"]["input_tokens_total"] == 90
    for case in report["cases"]:
        assert case["verdict_agreement_hi_mr_en"] is True
        assert set(case["locale_results"]) == {"en", "hi", "mr"}


def test_multilingual_disagreement_is_counted():
    async def disagree(request):
        locale = request.get("locale", "en")
        return "eligible" if locale == "en" else "not_eligible"

    report = asyncio.run(
        e4_llm_arm.run_llm_eligibility_ablation(
            proposer=disagree,
            limit=2,
            model_name="scripted-test",
            locales=("en", "hi", "mr"),
            pace_seconds=0,
        )
    )
    assert report["verdict_agreement_hi_mr_en"]["all_three_agree"] == 0
    assert report["verdict_agreement_hi_mr_en"]["rate"] == 0.0
