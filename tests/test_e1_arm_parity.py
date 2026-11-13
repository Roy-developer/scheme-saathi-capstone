"""Offline parity checks for the E1 single-agent (C1) arm.

These are functional mechanics tests with scripted models. They are not model
quality or cost evidence.
"""

import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver

from eval.harness import e1_runner as e1
from src.workflow import agent_config, single_agent
from src.workflow.agent_middleware import AgentModelError
from src.workflow.conversation_budget import BUDGET_NAMESPACE
from src.workflow.journey import JourneyRequest, run_journey
from test_single_agent_journey import (
    PROFILE, PROVIDER, RuleService, SelectingModel, graph_for,
)


class UnavailableAtEligibilityModel(SelectingModel):
    """Behaves normally until the eligibility step, then the model is unavailable."""

    async def choose(self, agent, locale, messages, actions):
        if (
            self.contexts == []
            or self.choices[-1:] != ["collect_information"]
        ):
            return await super().choose(agent, locale, messages, actions)
        self.choices.append("model_unavailable")
        raise AgentModelError("scripted model outage")


def test_c1_recovers_eligibility_from_the_rule_engine_when_model_is_unavailable():
    """If the model drops out at the eligibility step, C1 still gets the rule verdict.

    C2 uses the same code-selected recovery, so an outage cannot make C1 fail
    where C2 would succeed for reasons unrelated to agent design.
    """

    async def scenario():
        service = RuleService()
        model = UnavailableAtEligibilityModel()
        graph = graph_for(model, service)
        request = JourneyRequest(action="evaluate", scheme_id="IGNWPS-MH", profile=PROFILE)
        response = await run_journey(graph, request)
        ledger = await graph.store.aget(BUDGET_NAMESPACE, str(request.conversation_id))
        return response, ledger.value["counters"], service

    response, counters, service = asyncio.run(scenario())
    assert response.eligibility_result is not None
    assert response.eligibility_result.result == "eligible"
    assert service.calls.count("evaluate_eligibility") == 1
    assert counters["tool_calls"] <= 24


def test_c1_prompt_carries_the_same_role_guidance_as_c2_in_every_locale():
    """C1 and C2 must receive the same instructions; only orchestration differs."""

    from src.workflow.agent_config import AGENT_PROMPTS

    roles = ("supervisor", "intake", "eligibility", "documents", "application")
    for locale in ("en", "hi", "mr"):
        single = AGENT_PROMPTS["single"][locale]
        for role in roles:
            assert AGENT_PROMPTS[role][locale] in single, (role, locale)


_DATASET = e1.DevelopmentSetControls(
    split="development", protected=False, synthetic_only=True,
)


def _declared_arms(
    budget: e1.BudgetCeilings | None = None,
    capabilities: frozenset[str] | None = None,
) -> tuple[e1.ArmControls, ...]:
    """Arms declared from the shared values unless a drifted value is supplied."""

    budget = budget or e1.shared_budget_ceilings()
    caps = capabilities if capabilities is not None else e1.shared_single_agent_capabilities()
    rule = ("rule_engine", "separate_exact_human_approval")
    return (
        e1.ArmControls("C0", None, "none", caps, budget, *rule),
        e1.ArmControls("C1", "offline-script-v1", "scripted", caps, budget, *rule),
        e1.ArmControls("C2", "offline-script-v1", "scripted", caps, budget, *rule),
    )


def test_shared_budget_mapping_matches_agent_config_constants():
    """The runner's ceilings must mirror agent_config, field by field."""

    assert e1.shared_budget_ceilings() == e1.BudgetCeilings(
        model_calls=agent_config.MAX_CONVERSATION_MODEL_CALLS,
        agent_tool_calls=agent_config.MAX_CONVERSATION_TOOL_CALLS,
        domain_calls=agent_config.MAX_CONVERSATION_DOMAIN_TOOL_CALLS,
        agent_steps=agent_config.MAX_CONVERSATION_AGENT_STEPS,
        total_tokens=agent_config.MAX_CONVERSATION_TOKENS,
    )
    assert e1.comparability_blockers(_declared_arms(), _DATASET) == []


def test_c1_capabilities_are_the_single_agent_tool_set():
    assert e1.shared_single_agent_capabilities() == frozenset(
        single_agent.SINGLE_AGENT_TOOLS,
    )


@pytest.mark.parametrize(
    ("constant", "drifted"),
    [
        ("MAX_CONVERSATION_MODEL_CALLS", 9),
        ("MAX_CONVERSATION_TOOL_CALLS", 25),
        ("MAX_CONVERSATION_DOMAIN_TOOL_CALLS", 23),
        ("MAX_CONVERSATION_AGENT_STEPS", 11),
        ("MAX_CONVERSATION_TOKENS", 11_999),
    ],
)
def test_declared_budget_blocks_when_shared_constant_drifts(
    monkeypatch, constant, drifted,
):
    """Arms declared at the old ceilings must block once a shared constant moves."""

    declared = _declared_arms()
    assert e1.comparability_blockers(declared, _DATASET) == []
    monkeypatch.setattr(agent_config, constant, drifted)
    blockers = e1.comparability_blockers(declared, _DATASET)
    assert any("shared agent_config constants" in item for item in blockers)


@pytest.mark.parametrize("arm_id", ["C0", "C1", "C2"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("model_calls", 9),
        ("agent_tool_calls", 25),
        ("domain_calls", 23),
        ("agent_steps", 11),
        ("total_tokens", 11_999),
    ],
)
def test_declared_budget_drift_in_any_arm_blocks(arm_id, field, value):
    """A single arm that declares a non-shared ceiling is not comparable."""

    shared = e1.shared_budget_ceilings()
    drifted = e1.BudgetCeilings(**{**shared.__dict__, field: value})
    arms = tuple(
        e1.ArmControls(
            arm.arm_id, arm.model_id, arm.model_mode, arm.capabilities,
            drifted if arm.arm_id == arm_id else arm.budget,
            arm.eligibility_decider, arm.approval_policy,
        )
        for arm in _declared_arms()
    )
    blockers = e1.comparability_blockers(arms, _DATASET)
    assert any("shared agent_config constants" in item for item in blockers)


@pytest.mark.parametrize("arm_id", ["C0", "C1", "C2"])
def test_declared_capability_drift_in_any_arm_blocks(arm_id):
    """Dropping or adding a tool in any arm breaks the shared C1 tool set."""

    shared = e1.shared_single_agent_capabilities()
    for drifted in (shared - {"submit_draft"}, shared | {"extra_tool"}):
        arms = tuple(
            e1.ArmControls(
                arm.arm_id, arm.model_id, arm.model_mode,
                drifted if arm.arm_id == arm_id else arm.capabilities,
                arm.budget, arm.eligibility_decider, arm.approval_policy,
            )
            for arm in _declared_arms()
        )
        blockers = e1.comparability_blockers(arms, _DATASET)
        assert any("SINGLE_AGENT_TOOLS" in item for item in blockers)


def test_capability_drift_in_shared_tool_tuple_blocks(monkeypatch):
    """If SINGLE_AGENT_TOOLS gains a tool, previously declared arms must block."""

    declared = _declared_arms()
    monkeypatch.setattr(
        single_agent, "SINGLE_AGENT_TOOLS",
        (*single_agent.SINGLE_AGENT_TOOLS, "new_tool"),
    )
    blockers = e1.comparability_blockers(declared, _DATASET)
    assert any("SINGLE_AGENT_TOOLS" in item for item in blockers)


def _row(arm_id, **counters):
    base = dict(
        case_id="DEV-001", arm_id=arm_id, task_success=True,
        outcome_source="live_model" if arm_id != "C0" else "deterministic_workflow",
        policy_violations=0, latency_ms=10.0, model_calls=0, domain_calls=5,
        input_tokens=None, output_tokens=None, usage_kind="unknown",
    )
    base.update(counters)
    return e1.CaseObservation(**base)


def _report_with(*rows):
    return e1.build_report(
        _declared_arms(), _DATASET, rows, expected_case_ids=("DEV-001",),
    )


def test_observed_counters_at_shared_ceilings_are_accepted():
    shared = e1.shared_budget_ceilings()
    report = _report_with(
        _row("C0"),
        _row("C1", model_calls=shared.model_calls, agent_tool_calls=shared.agent_tool_calls,
             domain_calls=shared.domain_calls, agent_steps=shared.agent_steps,
             input_tokens=6_000, output_tokens=6_000, usage_kind="actual"),
        _row("C2", model_calls=1),
    )
    assert not any("exceed" in item for item in report["blockers"])
    assert report["evidence_label"] == e1.EVIDENCE_LABEL


@pytest.mark.parametrize(
    "counters",
    [
        {"model_calls": 9},
        {"agent_tool_calls": 25},
        {"domain_calls": 25},
        {"agent_steps": 13},
        {"input_tokens": 7_000, "output_tokens": 6_000, "usage_kind": "actual"},
    ],
)
def test_observed_counters_over_shared_ceilings_block(counters):
    report = _report_with(_row("C0"), _row("C1", **counters), _row("C2"))
    assert report["status"] == "blocked"
    assert any("exceed the shared" in item for item in report["blockers"])


def test_c0_recording_model_usage_blocks():
    report = _report_with(_row("C0", model_calls=1), _row("C1"), _row("C2"))
    assert any("model-free" in item for item in report["blockers"])


def test_report_is_labelled_development_only_with_shared_constants():
    report = _report_with(_row("C0"), _row("C1"), _row("C2"))
    assert report["evidence_label"] == (
        "development_only_not_model_quality_evidence"
    )
    assert report["shared_constants"]["budget_ceilings"] == e1.shared_budget_ceilings().__dict__
    assert report["status"] == "observed"
    assert report["blockers"] == []
