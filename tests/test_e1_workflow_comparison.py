"""Offline E1 workflow observations through the integrated API and MCP services."""

from __future__ import annotations

from dataclasses import asdict
from collections.abc import Callable, Iterator
import json
import os
from pathlib import Path
import socket
import time
from uuid import uuid4

import pytest


def _local_portal_url() -> str:
    """Pick a free loopback port before API modules read portal settings."""

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


os.environ.setdefault("SCHEME_SAATHI_PORTAL_URL", _local_portal_url())
os.environ.setdefault("SCHEME_SAATHI_DISABLE_CROSS_ENCODER", "1")

from eval.harness.e1_runner import (
    CaseObservation,
    DEVELOPMENT_CASE_IDS,
    DEVELOPMENT_SET_PATH,
)
from eval.harness.runner import load_persona_evaluation_set
from src.config import PROJECT_ROOT
from fake_chat_model import ModelDecision
from src.mcp_servers.service_routing import ACTOR_TOOLS, SERVICE_TOOLS
from src.workflow.agent_config import (
    MAX_CONVERSATION_AGENT_STEPS,
    MAX_CONVERSATION_DOMAIN_TOOL_CALLS,
    MAX_CONVERSATION_MODEL_CALLS,
    MAX_CONVERSATION_TOKENS,
    MAX_CONVERSATION_TOOL_CALLS,
)
from src.workflow.journey import build_journey_graph
from src.workflow.single_agent import SINGLE_AGENT_TOOLS
from test_red_team_runtime import (
    DOCUMENTS,
    SCHEME,
    RecordingAttackModel,
    _approval,
    _draft,
    _post,
    _snapshot,
)
from test_ui_integration import IntegratedUI, integrated_ui


E1_CASE_IDS = DEVELOPMENT_CASE_IDS
E1_BUDGET = {
    "model_calls": MAX_CONVERSATION_MODEL_CALLS,
    "agent_tool_calls": MAX_CONVERSATION_TOOL_CALLS,
    "agent_steps": MAX_CONVERSATION_AGENT_STEPS,
    "domain_tool_calls": MAX_CONVERSATION_DOMAIN_TOOL_CALLS,
    "total_token_reservation": MAX_CONVERSATION_TOKENS,
}
E1_SINGLE_AGENT_TOOLS = frozenset({
    "read_required_facts",
    "propose_profile_facts",
    "collect_information",
    "search_schemes",
    "evaluate_eligibility",
    "check_documents",
    "prepare_draft",
    "edit_draft",
    "submit_draft",
    "read_application_status",
})
E1_C2_ACTORS = ("intake", "eligibility", "documents", "application")


def _development_cases() -> tuple[tuple[str, dict[str, object], str], ...]:
    """Load only prelabelled, unprotected development personas."""

    dataset = load_persona_evaluation_set(
        PROJECT_ROOT.joinpath(*DEVELOPMENT_SET_PATH.split("/")),
    )
    selected = {
        persona.persona_id: persona
        for persona in dataset.personas
        if persona.persona_id in E1_CASE_IDS
    }
    if set(selected) != set(E1_CASE_IDS) or dataset.split != "development":
        raise ValueError("The E1 case selection is incomplete or not development.")
    rows: list[tuple[str, dict[str, object], str]] = []
    for case_id in E1_CASE_IDS:
        persona = selected[case_id]
        if persona.profile is None:
            raise ValueError(f"E1 case {case_id} must have an explicit synthetic profile.")
        expected = persona.expected_by_scheme.get(SCHEME)
        if expected is None:
            raise ValueError(f"E1 case {case_id} has no expected {SCHEME} result.")
        rows.append((case_id, persona.profile, expected.result))
    return tuple(rows)


E1_CASES = _development_cases()


class E1ScriptedModel(RecordingAttackModel):
    """One offline tool-choice fixture shared by C1 and C2, not efficacy evidence."""

    model_name: str = "e1-offline-script-v1"

    async def choose(self, agent, locale, messages, tools):
        if agent == "single":
            self.messages_seen.append({"agent": agent, "messages": messages})
            context = json.loads(messages[0]["content"])
            action = context["required_action"]
            if action not in E1_SINGLE_AGENT_TOOLS:
                raise AssertionError(f"Unexpected C1 action {action!r}")
            arguments: dict[str, object] = {}
            if action in {"read_required_facts", "evaluate_eligibility"}:
                candidates = context.get("available_candidate_ids", [])
                if not candidates:
                    raise AssertionError("C1 has no code-approved candidate to evaluate.")
                arguments["scheme_id"] = candidates[0]
            elif action == "propose_profile_facts":
                arguments["facts"] = context.get("description_facts", [])
            return ModelDecision(action=action, arguments=arguments)
        return await super().choose(agent, locale, messages, tools)


@pytest.fixture(scope="module", autouse=True)
def isolate_e1_upload_store() -> Iterator[None]:
    """Keep upload files and SQLite state unique to this E1 test process."""

    run_id = uuid4().hex
    upload_directory = PROJECT_ROOT / f".pytest-e1-uploads-{run_id}"
    upload_database = PROJECT_ROOT / f".pytest-e1-uploads-{run_id}.sqlite3"
    previous_directory = os.environ.get("SCHEME_SAATHI_UPLOAD_DIR")
    previous_database = os.environ.get("SCHEME_SAATHI_UPLOAD_DB")
    os.environ["SCHEME_SAATHI_UPLOAD_DIR"] = str(upload_directory)
    os.environ["SCHEME_SAATHI_UPLOAD_DB"] = str(upload_database)
    try:
        yield
    finally:
        if previous_directory is None:
            os.environ.pop("SCHEME_SAATHI_UPLOAD_DIR", None)
        else:
            os.environ["SCHEME_SAATHI_UPLOAD_DIR"] = previous_directory
        if previous_database is None:
            os.environ.pop("SCHEME_SAATHI_UPLOAD_DB", None)
        else:
            os.environ["SCHEME_SAATHI_UPLOAD_DB"] = previous_database
        if upload_directory.exists():
            for child in sorted(
                upload_directory.rglob("*"),
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                if child.is_file():
                    child.unlink(missing_ok=True)
                elif child.is_dir():
                    child.rmdir()
            upload_directory.rmdir()
        for suffix in ("", "-wal", "-shm"):
            upload_database.with_name(upload_database.name + suffix).unlink(
                missing_ok=True
            )


def _install_arm_graph(
    harness: IntegratedUI,
    monkeypatch: pytest.MonkeyPatch,
    arm: str,
    model: E1ScriptedModel | None,
) -> object:
    """Install each arm on the integrated app while sharing its real services."""

    state = harness.client.app.state
    model_options = {
        "single_agent_provider": model if arm == "C1" else None,
        "model_provider": model if arm == "C2" else None,
        "eligibility_model_provider": model if arm == "C2" else None,
        "count_domain_calls": True,
    }
    graph = build_journey_graph(
        state.mcp_client,
        state.rule_packages,
        checkpointer=state.journey_checkpointer,
        store=state.journey_store,
        fact_registry=state.fact_registry,
        rule_bundles=state.rule_bundles,
        **model_options,
    )
    monkeypatch.setattr(state, "journey_graph", graph)
    return graph


def _budget_snapshot(
    graph: object,
    harness: IntegratedUI,
    conversation_id: str,
) -> dict[str, int]:
    """Read final cumulative ledger counters without summing trace events."""

    stored = harness.client.portal.call(
        graph.store.aget, ("budget",), conversation_id,
    )
    if stored is None:
        return {}
    counters = stored.value.get("counters", {})
    return {
        key: value
        for key, value in counters.items()
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }


def _service_capabilities() -> frozenset[str]:
    """Compare service-level capabilities across fixed and specialist paths."""

    specialist_union = frozenset().union(
        *(ACTOR_TOOLS[actor] for actor in E1_C2_ACTORS)
    )
    all_services = frozenset().union(*SERVICE_TOOLS.values())
    if specialist_union != all_services:
        raise AssertionError(
            "The C2 specialist actor union does not cover the shared service set."
        )
    if frozenset(SINGLE_AGENT_TOOLS) != E1_SINGLE_AGENT_TOOLS:
        raise AssertionError("The C1 single-agent action inventory changed.")
    if {"approve", "reject"} & set(SINGLE_AGENT_TOOLS):
        raise AssertionError("Human approval must not be a C1 model action.")
    return all_services


@pytest.mark.parametrize("arm", ("C0", "C1", "C2"))
@pytest.mark.parametrize(
    ("case_id", "profile", "expected"),
    E1_CASES,
    ids=[case[0] for case in E1_CASES],
)
def test_e1_full_workflow_case(
    arm: str,
    case_id: str,
    profile: dict[str, object],
    expected: str,
    integrated_ui: IntegratedUI,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> None:
    """Exercise search, deterministic eligibility, and guarded application flow."""

    capabilities = _service_capabilities()
    model = E1ScriptedModel() if arm in {"C1", "C2"} else None
    graph = _install_arm_graph(integrated_ui, monkeypatch, arm, model)
    conversation_id = str(uuid4())
    before_tools = len(integrated_ui.tools)
    started = time.perf_counter()
    actual: str | None = None
    task_success: bool | None = None
    policy_violations = 0
    failed = False

    try:
        search = _post(
            integrated_ui,
            action="search",
            conversation_id=conversation_id,
            query="widow pension BPL",
        )
        assert search["status"] == "search_results"
        assert SCHEME in search["candidate_scheme_ids"]

        result = _post(
            integrated_ui,
            action="evaluate",
            conversation_id=conversation_id,
            scheme_id=SCHEME,
            profile=profile,
        )
        actual = result["status"]
        task_success = actual == expected

        if expected == "eligible":
            assert task_success
            draft = _draft(integrated_ui, conversation_id)
            denied = _approval(integrated_ui, conversation_id, draft, "submit")
            if denied.status_code != 409:
                policy_violations += 1
            assert denied.status_code == 409

            human_approval = _approval(
                integrated_ui, conversation_id, draft, "approve",
            )
            assert human_approval.status_code == 200
            edited = integrated_ui.client.put(
                f"/api/v1/journey/{conversation_id}/drafts/{draft['draft_id']}",
                json={
                    "revision": draft["revision"],
                    "applicant_reference": "Synthetic Person",
                    "district": "Synthetic district updated",
                },
            )
            if edited.status_code != 200:
                state = _snapshot(integrated_ui, conversation_id)
                assert edited.status_code == 200, (
                    f"{edited.text}; graph_status={state.get('status')!r}; "
                    f"agent_trace={state.get('agent_trace')!r}; "
                    f"budget={state.get('agent_budget')!r}"
                )
            assert edited.json()["revision"] != draft["revision"]
            assert edited.json()["fingerprint"] != draft["fingerprint"]
            assert not edited.json()["approved"]

            stale_submit = _approval(
                integrated_ui, conversation_id, draft, "submit",
            )
            if stale_submit.status_code != 409:
                policy_violations += 1
            assert stale_submit.status_code == 409

            reapproved = _approval(
                integrated_ui, conversation_id, edited.json(), "approve",
            )
            assert reapproved.status_code == 200
            submitted = _approval(
                integrated_ui, conversation_id, edited.json(), "submit",
            )
            assert submitted.status_code == 200
            assert submitted.json()["receipt_id"]
        else:
            assert task_success
            drafts = integrated_ui.client.get(
                f"/api/v1/journey/{conversation_id}/drafts",
            )
            assert drafts.status_code == 200
            assert drafts.json()["drafts"] == []
    except Exception:
        failed = True
        raise
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        counters = _budget_snapshot(graph, integrated_ui, conversation_id)
        observation = CaseObservation(
            case_id=case_id,
            arm_id=arm,
            task_success=task_success,
            outcome_source=(
                "deterministic_workflow" if arm == "C0" else "scripted_model"
            ),
            policy_violations=policy_violations,
            latency_ms=elapsed_ms,
            model_calls=counters.get("model_calls", 0 if arm == "C0" else None),
            domain_calls=counters.get("domain_tool_calls"),
            input_tokens=None,
            output_tokens=None,
            usage_kind="unknown",
            error=failed,
            timeout=False,
            agent_steps=counters.get("agent_steps", 0 if arm == "C0" else None),
            agent_tool_calls=counters.get("tool_calls", 0 if arm == "C0" else None),
            reserved_input_tokens=counters.get("input_tokens"),
            reserved_output_tokens=counters.get("output_tokens"),
        )
        record_property("e1_observation", json.dumps(asdict(observation)))
        record_property("e1_capabilities", json.dumps(sorted(capabilities)))
        record_property("e1_budget_ceilings", json.dumps(E1_BUDGET))
        record_property(
            "e1_dataset_version",
            load_persona_evaluation_set(
                PROJECT_ROOT.joinpath(*DEVELOPMENT_SET_PATH.split("/")),
            ).dataset_version,
        )
        record_property(
            "e1_tool_calls",
            json.dumps(sorted(set(integrated_ui.tools[before_tools:]))),
        )
        record_property(
            "e1_model_id",
            model.model_name if model is not None else "unused",
        )

