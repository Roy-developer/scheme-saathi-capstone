"""DEVELOPMENT-ONLY, NON-AUTHORITATIVE E4 helpers.

Two offline pieces for experiment E4:

1. ``run_shadow_comparison``: asks an LLM-shadow eligibility *proposal* (a
   scripted chat model, never a live provider) for each development persona
   and records it next to the rule-engine result. The shadow proposal is only
   counted for agreement; it is never returned as a verdict, never passed to
   a store, and never changes the rule result.
2. ``run_question_order_ablation``: counts questions asked before a verdict
   under a fixed questionnaire order versus the planned order produced by the
   existing question picker (``pick_next_registered_fact``). The picker is
   used unchanged.

Nothing here imports journey state, stores, or databases, and nothing here
writes live state. Held-out personas are out of scope: callers must pass a
development persona set (the loader rejects protected sets by default).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from eval.harness.runner import load_persona_evaluation_set, persona_input
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import HouseholdProfile
from src.workflow.question_picker import pick_next_registered_fact

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEV_PERSONAS = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"
SHADOW_ACTION = "propose_eligibility"
SHADOW_PROMPT = (
    "DEVELOPMENT-ONLY shadow eligibility proposal. Non-authoritative; "
    "never a live verdict."
)
NON_AUTHORITATIVE_NOTICE = (
    "development-only, non-authoritative: shadow proposals are never written "
    "to live state and never change the rule-engine verdict"
)
MAX_QUESTIONS = 50


def _load_fake_chat_model():
    """Load tests/fake_chat_model.py by path so tests/ is not put on sys.path."""

    if "fake_chat_model" in sys.modules:
        return sys.modules["fake_chat_model"]
    path = PROJECT_ROOT / "tests" / "fake_chat_model.py"
    spec = importlib.util.spec_from_file_location("fake_chat_model", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fake_chat_model"] = module
    spec.loader.exec_module(module)
    return module


_fake = _load_fake_chat_model()
ModelDecision = _fake.ModelDecision
FakeChatModel = _fake.FakeChatModel

ShadowProposer = Callable[[dict[str, Any]], str]


class ScriptedShadowModel(FakeChatModel):
    """Scripted stand-in for the LLM-shadow eligibility proposal.

    ``proposer`` maps the shadow request (a plain dict copy) to a result
    string. The default proposer is a deliberately naive stub: it says
    ``eligible`` when every rule field is known and ``need_more_information``
    otherwise, so it never sees boundary values. It is a placeholder, not a
    model of any real LLM behaviour.
    """

    model_name: str = "scripted-shadow-stub"
    proposer: Any = None

    async def choose(self, agent, locale, messages, tools) -> ModelDecision:
        request = json.loads(str(messages[-1]["content"]))
        if self.proposer is not None:
            result = self.proposer(request)
        else:
            known = set(request["known_facts"])
            result = (
                "eligible"
                if set(request["rule_fields"]) <= known
                else "need_more_information"
            )
        return ModelDecision(
            action=SHADOW_ACTION,
            arguments={"result": result, "non_authoritative": True},
        )


def _rule_fields(package: Any) -> list[str]:
    return sorted({rule.field for rule in package.rules})


async def propose_shadow_result(
    model: Any, request: Mapping[str, Any],
) -> dict[str, Any]:
    """Ask the shadow model for one proposal; returns its raw arguments only."""

    payload = json.dumps(dict(request), sort_keys=True)
    reply = await model.ainvoke([
        SystemMessage(content=SHADOW_PROMPT),
        HumanMessage(content=payload),
    ])
    calls = [c for c in reply.tool_calls if c["name"] == SHADOW_ACTION]
    if len(calls) != 1:
        return {"result": None, "error": "no proposal returned"}
    return dict(calls[0]["args"])


async def run_shadow_comparison(
    *,
    eval_path: Path = DEV_PERSONAS,
    model: Any = None,
) -> dict[str, Any]:
    """Compare the shadow proposal with the rule engine on development personas.

    The rule result is computed first and is the only value reported as a
    verdict. The shadow result is recorded beside it and only feeds the
    agreement counts.
    """

    evaluation_set = load_persona_evaluation_set(eval_path)
    provider = RulePackageProvider()
    registry = provider.registry
    active_model = model or ScriptedShadowModel()
    cases: list[dict[str, Any]] = []
    for persona in evaluation_set.personas:
        profile = persona_input(persona, registry)
        known = sorted(fid for fid, s in profile.facts.items() if s.status == "known")
        for scheme_id in persona.expected_by_scheme:
            package = provider.get(scheme_id)
            rule = evaluate_mock_eligibility(profile, package, registry=registry)
            request = {
                "scheme_id": scheme_id,
                "known_facts": known,
                "rule_fields": _rule_fields(package),
            }
            shadow = await propose_shadow_result(active_model, request)
            cases.append({
                "persona_id": persona.persona_id,
                "scheme_id": scheme_id,
                "rule_result": rule.result,
                "shadow_result": shadow.get("result"),
                "agree": shadow.get("result") == rule.result,
                "authoritative": False,
                "written_to_live_state": False,
            })
    agree = sum(case["agree"] for case in cases)
    return {
        "notice": NON_AUTHORITATIVE_NOTICE,
        "case_count": len(cases),
        "agree": agree,
        "disagree": len(cases) - agree,
        "cases": cases,
    }


def _leaf_facts(package: Any, registry: Any) -> list[str]:
    """Raw fact IDs a package reads, in sorted order (the fixed questionnaire)."""

    empty = HouseholdProfile(
        registry_version=registry.registry_version, facts={},
    ).validate_against(registry)
    leaves: set[str] = set(package.required_facts)
    for rule in package.rules:
        leaves.update(empty.missing_inputs(rule.field, registry))
    return sorted(leaves)


def _ask_until_verdict(
    full: HouseholdProfile,
    package: Any,
    registry: Any,
    order: str,
    fixed: list[str],
) -> dict[str, Any]:
    """Ask in one order until the rule verdict is decided; count questions."""

    revealed: dict[str, Any] = {}
    skipped: set[str] = set()
    asked = 0

    def store() -> HouseholdProfile:
        return HouseholdProfile(
            registry_version=registry.registry_version, facts=dict(revealed),
        ).validate_against(registry)

    def result() -> str:
        return evaluate_mock_eligibility(store(), package, registry=registry).result

    def answer(fact_id: str) -> None:
        nonlocal asked
        asked += 1
        state = full.facts.get(fact_id)
        if state is not None and state.status == "known":
            revealed[fact_id] = state
        else:
            skipped.add(fact_id)

    if order == "fixed":
        for fact_id in fixed:
            if result() != "need_more_information":
                break
            answer(fact_id)
    elif order == "planned":
        for _ in range(MAX_QUESTIONS):
            if result() != "need_more_information":
                break
            next_fact = pick_next_registered_fact(
                store(), package, registry, frozenset(skipped),
            )
            if next_fact is None:
                break
            answer(next_fact)
    else:
        raise ValueError(f"Unknown question order {order!r}")

    final = result()
    return {
        "questions": asked,
        "verdict": final,
        "decided": final != "need_more_information",
    }


def run_question_order_ablation(
    *, eval_path: Path = DEV_PERSONAS,
) -> dict[str, Any]:
    """Count questions before a verdict under fixed versus planned order."""

    evaluation_set = load_persona_evaluation_set(eval_path)
    provider = RulePackageProvider()
    registry = provider.registry
    rows: list[dict[str, Any]] = []
    for persona in evaluation_set.personas:
        full = persona_input(persona, registry)
        for scheme_id, expected in persona.expected_by_scheme.items():
            package = provider.get(scheme_id)
            fixed_order = _leaf_facts(package, registry)
            fixed = _ask_until_verdict(full, package, registry, "fixed", fixed_order)
            planned = _ask_until_verdict(full, package, registry, "planned", fixed_order)
            rows.append({
                "persona_id": persona.persona_id,
                "scheme_id": scheme_id,
                "expected_result": expected.result,
                "fixed": fixed,
                "planned": planned,
                "verdict_match": fixed["verdict"] == planned["verdict"],
            })
    count = len(rows)
    return {
        "notice": NON_AUTHORITATIVE_NOTICE,
        "case_count": count,
        "fixed_questions_total": sum(r["fixed"]["questions"] for r in rows),
        "planned_questions_total": sum(r["planned"]["questions"] for r in rows),
        "verdict_match_count": sum(r["verdict_match"] for r in rows),
        "cases": rows,
    }
