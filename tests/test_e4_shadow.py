"""Offline tests for the development-only E4 shadow path and question-order ablation."""

import ast
import asyncio
from pathlib import Path

import pytest

from eval.harness import e4_shadow
from eval.harness.runner import load_persona_evaluation_set, persona_input
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider

SHADOW_SOURCE = Path(e4_shadow.__file__)
FORBIDDEN_PREFIXES = (
    "src.workflow.journey",
    "src.workflow.state",
    "src.db",
    "src.storage",
    "sqlite3",
    "langgraph.store",
    "langgraph.checkpoint",
)


def _rule_results(report):
    return [(c["persona_id"], c["scheme_id"], c["rule_result"]) for c in report["cases"]]


def _direct_rule_results():
    provider = RulePackageProvider()
    registry = provider.registry
    evaluation_set = load_persona_evaluation_set(e4_shadow.DEV_PERSONAS)
    out = []
    for persona in evaluation_set.personas:
        profile = persona_input(persona, registry)
        for scheme_id in persona.expected_by_scheme:
            verdict = evaluate_mock_eligibility(
                profile, provider.get(scheme_id), registry=registry,
            )
            out.append((persona.persona_id, scheme_id, verdict.result))
    return out


def test_shadow_result_never_changes_rule_verdict():
    baseline = asyncio.run(e4_shadow.run_shadow_comparison())

    # A shadow that always contradicts the rules must not move any verdict.
    contrary = e4_shadow.ScriptedShadowModel(
        proposer=lambda request: "eligible",
    )
    contradicted = asyncio.run(e4_shadow.run_shadow_comparison(model=contrary))

    assert _rule_results(contradicted) == _rule_results(baseline)
    assert _rule_results(baseline) == _direct_rule_results()
    assert "verdict" not in contradicted
    assert all(c["authoritative"] is False for c in contradicted["cases"])
    assert contradicted["agree"] + contradicted["disagree"] == contradicted["case_count"]


def test_shadow_agreement_counts_match_recorded_cases():
    report = asyncio.run(e4_shadow.run_shadow_comparison())

    assert report["case_count"] == 46
    assert report["agree"] == sum(c["agree"] for c in report["cases"])
    assert report["disagree"] == report["case_count"] - report["agree"]
    assert report["agree"] == 14
    assert report["disagree"] == 29


def test_shadow_path_cannot_write_live_state(monkeypatch):
    # Source-level: the module imports no journey state, store or database code.
    tree = ast.parse(SHADOW_SOURCE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not name.startswith(FORBIDDEN_PREFIXES), name

    # Runtime: any store write attempted during the run fails the test.
    from langgraph.store.memory import InMemoryStore

    def refuse(*args, **kwargs):
        raise AssertionError("shadow path attempted a store write")

    monkeypatch.setattr(InMemoryStore, "put", refuse)
    monkeypatch.setattr(InMemoryStore, "aput", refuse)

    # A proposer that mutates the request it receives must not reach the rules.
    def mutating(request):
        request["known_facts"].clear()
        request["rule_fields"].append("is_widow")
        return "eligible"

    report = asyncio.run(e4_shadow.run_shadow_comparison(
        model=e4_shadow.ScriptedShadowModel(proposer=mutating),
    ))
    assert _rule_results(report) == _direct_rule_results()
    assert all(c["written_to_live_state"] is False for c in report["cases"])
    assert report["notice"] == e4_shadow.NON_AUTHORITATIVE_NOTICE


def test_shadow_model_is_offline_scripted_fake():
    model = e4_shadow.ScriptedShadowModel()
    assert isinstance(model, e4_shadow.FakeChatModel)
    assert model._llm_type == "fake-tool-calling-model"


def test_both_question_orders_reach_same_verdict_on_dev_personas():
    report = e4_shadow.run_question_order_ablation()

    assert report["case_count"] == 46
    assert report["verdict_match_count"] == report["case_count"]
    for row in report["cases"]:
        assert row["fixed"]["verdict"] == row["planned"]["verdict"], row["persona_id"]
        if row["fixed"]["decided"]:
            assert row["fixed"]["verdict"] == row["expected_result"], row["persona_id"]
        assert row["planned"]["questions"] <= 50


def test_question_order_counts_are_reported_per_order():
    report = e4_shadow.run_question_order_ablation()

    assert report["fixed_questions_total"] == sum(
        r["fixed"]["questions"] for r in report["cases"]
    )
    assert report["planned_questions_total"] == sum(
        r["planned"]["questions"] for r in report["cases"]
    )
    assert report["fixed_questions_total"] == 192
    assert report["planned_questions_total"] == 177


def test_unknown_question_order_is_rejected():
    provider = RulePackageProvider()
    package = provider.get("IGNWPS-MH")
    with pytest.raises(ValueError):
        e4_shadow._ask_until_verdict(
            e4_shadow.persona_input(
                load_persona_evaluation_set(e4_shadow.DEV_PERSONAS).personas[0],
                provider.registry,
            ),
            package, provider.registry, "random", [],
        )
