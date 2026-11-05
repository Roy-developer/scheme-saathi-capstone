"""Verify the additive Phase 2 API contract without a network model."""

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from src.api.app import app
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from fake_chat_model import FakeChatModel, ModelDecision
from src.workflow.journey import build_journey_graph


PACKAGES = RulePackageProvider().packages


class FakeModel(FakeChatModel):
    """Provide one complete planner/intake action trace offline."""

    model_name: str = "fake-api-model"

    def __init__(self) -> None:
        super().__init__()
        self.choices = [
            ModelDecision(
                action="propose_plan",
                arguments={"step_ids": ["intake", "eligibility"]},
            ),
            ModelDecision(
                action="finish_plan",
                arguments={"confirm": "use_validated_plan"},
            ),
            ModelDecision(
                action="read_required_facts",
                arguments={"scheme_id": "IGNWPS-MH"},
            ),
            ModelDecision(
                action="propose_profile_facts",
                arguments={
                    "facts": [
                        {"fact_name": "is_widow", "value": True},
                    ]
                },
            ),
            ModelDecision(
                action="finish_intake",
                arguments={"confirm": "return_to_supervisor"},
            ),
        ]

    async def choose(self, _agent, _locale, _messages, _actions):
        return self.choices.pop(0)


class FakeRuleClient:
    """Supply the rule engine's structured fact list."""

    async def call_tool(self, _name, arguments):
        return SimpleNamespace(
            is_error=False,
            structured_content=list(
                PACKAGES[str(arguments["scheme_id"])].required_facts
            ),
        )


def test_journey_api_accepts_localized_csc_intake_and_rejects_missing_presence(
    monkeypatch,
) -> None:
    """The API requires citizen presence and returns typed localized intake data."""

    async def eligibility(_client, scheme_id, profile):
        return evaluate_mock_eligibility(profile, PACKAGES[scheme_id])

    graph = build_journey_graph(
        FakeRuleClient(),
        PACKAGES,
        eligibility_tool=eligibility,
        model_provider=FakeModel(),
        checkpointer=MemorySaver(),
        today=lambda: date(2026, 11, 4),
    )
    monkeypatch.setattr(app.state, "journey_graph", graph, raising=False)
    client = TestClient(app)
    base_payload = {
        "action": "interview",
        "scheme_id": "IGNWPS-MH",
        "profile_description": "काल्पनिक कुटुंबाची माहिती.",
        "locale": "mr",
        "mode": "csc",
    }

    rejected = client.post("/api/v1/journey", json=base_payload)
    assert rejected.status_code == 422

    accepted = client.post(
        "/api/v1/journey",
        json={**base_payload, "citizen_present": True},
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["status"] == "awaiting_answer"
    assert body["locale"] == "mr"
    assert body["mode"] == "csc"
    assert "CSC" in body["mode_acknowledgement"]
    assert "होय" in body["question"]
    assert body["react_status"] == "model_assisted"
    assert body["agent_trace"]
