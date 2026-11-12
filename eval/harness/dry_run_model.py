"""Scripted offline chat model used only to dry-run the E1 harness.

It behaves like a well-behaved agent (observe, then hand off), so a dry run
proves the wiring and the metrics code. Its numbers say nothing about how a
real model performs and must never be quoted as E1 results.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from fake_chat_model import FakeChatModel, ModelDecision  # noqa: E402


def _tools_used(messages: list[dict[str, str]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        if message["role"] == "assistant":
            names += [call["tool"] for call in json.loads(message["content"])]
    return names


class DryRunModel(FakeChatModel):
    model_name: str = "dry-run-scripted"

    async def choose(self, agent, locale, messages, tools):
        task = json.loads(messages[0]["content"])
        used = _tools_used(messages)
        last = (
            json.loads(messages[-1]["content"]).get("observation", {})
            if len(messages) > 1 else {}
        )
        if agent == "single":
            if len(used) < len(task["scheme_ids"]):
                return ModelDecision(
                    action="check_candidate",
                    arguments={"scheme_id": task["scheme_ids"][len(used)]},
                    input_tokens=200, output_tokens=20)
            if last.get("result") == "eligible" and "inspect_documents" not in used:
                return ModelDecision(
                    action="inspect_documents",
                    arguments={"scheme_id": last["scheme_id"]},
                    input_tokens=260, output_tokens=20)
            return ModelDecision(action="finish_baseline", arguments={},
                                 input_tokens=300, output_tokens=10)
        if agent == "eligibility":
            if not used:
                return ModelDecision(
                    action="check_candidate",
                    arguments={"scheme_id": task["scheme_id"]},
                    input_tokens=150, output_tokens=15)
            if last.get("missing_fields"):
                return ModelDecision(
                    action="request_clarification",
                    arguments={"confirm": "request_observed_missing_facts"},
                    input_tokens=200, output_tokens=10)
            return ModelDecision(
                action="handoff_verdict",
                arguments={"confirm": "return_observed_verdict"},
                input_tokens=200, output_tokens=10)
        if agent == "documents":
            if not used:
                return ModelDecision(
                    action="inspect_document_metadata",
                    arguments={"scheme_id": task["scheme_id"]},
                    input_tokens=150, output_tokens=15)
            return ModelDecision(action="handoff_documents",
                                 arguments={"outcome": "ready"},
                                 input_tokens=200, output_tokens=10)
        raise AssertionError(f"unexpected agent {agent}")
