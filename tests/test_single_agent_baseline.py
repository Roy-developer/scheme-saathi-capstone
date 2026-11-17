"""E1 C1: one agent with every read tool, verdicts still from the rule engine."""

import asyncio

from fake_chat_model import FakeChatModel, ModelDecision
from src.api.eligibility import EligibilityResponse
from src.workflow.single_agent_baseline import run_single_agent_baseline


def _response(scheme_id: str, result: str) -> EligibilityResponse:
    return EligibilityResponse(
        scheme_id=scheme_id, result=result, reason="synthetic",
        deciding_rule_ids=["r1"], evidence=[],
    )


class ScriptedModel(FakeChatModel):
    model_name: str = "offline-single-model"

    def __init__(self, script: list[ModelDecision]) -> None:
        super().__init__()
        self.script = list(script)

    async def choose(self, agent, locale, messages, actions):
        assert agent == "single" and locale == "en"
        assert {a.name for a in actions} == {
            "check_candidate", "inspect_documents", "finish_baseline",
        }
        return self.script.pop(0)


def _run(script, verdicts, max_steps=8):
    inspected = []

    async def evaluate(scheme_id):
        return _response(scheme_id, verdicts[scheme_id])

    async def inspect(scheme_id):
        inspected.append(scheme_id)
        return {"status": "checklist_complete"}

    result = asyncio.run(run_single_agent_baseline(
        ScriptedModel(script), list(verdicts), "en", {}, evaluate, inspect,
        max_steps=max_steps,
    ))
    return result, inspected


def test_baseline_gets_verdicts_from_rule_engine_and_inspects_only_eligible():
    script = [
        ModelDecision(action="check_candidate", arguments={"scheme_id": "A"}),
        ModelDecision(action="check_candidate", arguments={"scheme_id": "B"}),
        ModelDecision(action="inspect_documents", arguments={"scheme_id": "A"}),
        ModelDecision(action="finish_baseline", arguments={}),
    ]
    (outcome, _, trace, status), inspected = _run(
        script, {"A": "eligible", "B": "not_eligible"},
    )
    assert status == "completed" and outcome.finished
    assert {k: v.result for k, v in outcome.verdicts.items()} == {
        "A": "eligible", "B": "not_eligible",
    }
    assert inspected == ["A"] and set(outcome.documents) == {"A"}
    assert trace  # same scrubbed trace as the team


def test_baseline_stops_when_it_inspects_an_ineligible_scheme():
    script = [
        ModelDecision(action="check_candidate", arguments={"scheme_id": "B"}),
        ModelDecision(action="inspect_documents", arguments={"scheme_id": "B"}),
    ]
    (outcome, _, _, status), inspected = _run(
        script, {"A": "eligible", "B": "not_eligible"},
    )
    assert status == "action_rejected"
    assert inspected == [] and outcome.documents == {} and not outcome.finished


def test_baseline_cannot_finish_before_checking_every_candidate():
    script = [
        ModelDecision(action="check_candidate", arguments={"scheme_id": "A"}),
        ModelDecision(action="finish_baseline", arguments={}),
    ]
    (outcome, _, _, status), _ = _run(script, {"A": "eligible", "B": "eligible"})
    assert status == "action_rejected" and not outcome.finished
