"""Offline tests for scripts/run_e1_live.py. No network: scripted models only."""

import asyncio
import importlib.util
import json
import socket
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.outputs import LLMResult

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_e1_live.py"
sys.path.insert(0, str(ROOT / "tests"))
from fake_chat_model import FakeChatModel, ModelDecision  # noqa: E402


def _load_script():
    spec = importlib.util.spec_from_file_location("run_e1_live", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_e1_live"] = module
    spec.loader.exec_module(module)
    return module


e1 = _load_script()


@pytest.fixture
def portal_url(monkeypatch):
    """Point the portal URL at a free local port (bound to 0, then released)."""

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("SCHEME_SAATHI_PORTAL_URL", f"http://127.0.0.1:{port}")
    return f"http://127.0.0.1:{port}"


class JourneyC1ScriptedModel(FakeChatModel):
    """Scripted journey single-agent: always choose the code-required action."""

    model_name: str = "scripted-e1-c1"

    async def choose(self, agent, locale, messages, tools):
        if agent != "single":
            raise AssertionError(f"Unexpected agent {agent!r} for C1")
        context = json.loads(messages[0]["content"])
        action = context["required_action"]
        arguments: dict[str, object] = {}
        if action in {"read_required_facts", "evaluate_eligibility"}:
            candidates = context.get("available_candidate_ids") or []
            if not candidates:
                raise AssertionError("C1 has no code-approved candidate")
            arguments["scheme_id"] = candidates[0]
        elif action == "propose_profile_facts":
            arguments["facts"] = context.get("description_facts", [])
        return ModelDecision(
            action=action,
            arguments=arguments,
            input_tokens=10,
            output_tokens=5,
        )


def _case(persona_index: int = 0) -> dict[str, Any]:
    return e1.load_development_cases(1)[persona_index]


def test_loads_only_development_cases():
    cases = e1.load_development_cases()
    assert len(cases) >= 46
    assert all("held" not in c["case_id"].lower() for c in cases)


def test_normalizes_cant_tell_expected():
    cases = e1.load_development_cases()
    row = next(c for c in cases if c["case_id"].startswith("IGNWPS-DEV-007"))
    assert row["expected"]["result"] == "need_more_information"


def test_refuses_protected_or_held_out_files(tmp_path, monkeypatch):
    bad = tmp_path / "held.json"
    bad.write_text(json.dumps({"split": "held_out", "protected": True, "personas": []}))
    monkeypatch.setattr(e1, "DEV_FILES", (bad,))
    with pytest.raises(ValueError):
        e1.load_development_cases()


def test_refuses_protected_persona_inside_dev_file(tmp_path, monkeypatch):
    bad = tmp_path / "dev.json"
    bad.write_text(json.dumps({
        "split": "development", "protected": False,
        "personas": [{"persona_id": "X", "split": "development", "protected": True,
                      "profile": {}, "expected_by_scheme": {}}],
    }))
    monkeypatch.setattr(e1, "DEV_FILES", (bad,))
    with pytest.raises(ValueError):
        e1.load_development_cases()


def test_c0_matches_rule_engine_without_any_model(portal_url):
    case = _case()
    obs = asyncio.run(
        e1.run_case("C0", case, None, e1.RulePackageProvider(), model_id=e1.DEFAULT_MODEL_ID)
    )
    assert obs["error"] is None
    assert obs["actual_result"] == case["expected"]["result"]
    assert obs["task_success"] is True
    assert obs["model_calls"] == 0 and obs["cost_usd"] == 0.0


def test_c1_uses_journey_single_agent_provider(portal_url, monkeypatch):
    monkeypatch.setattr(
        e1,
        "make_model",
        lambda key, rec, model_id: JourneyC1ScriptedModel(callbacks=[rec]),
    )
    case = _case()
    obs = asyncio.run(
        e1.run_case(
            "C1",
            case,
            "offline-test-key",
            e1.RulePackageProvider(),
            model_id=e1.DEFAULT_MODEL_ID,
        )
    )
    assert obs["error"] is None, obs["error"]
    assert obs["actual_result"] == case["expected"]["result"]
    assert obs["task_success"] is True


def test_usage_recorder_reads_tokens_and_reported_cost():
    rec = e1.UsageRecorder()
    result = LLMResult(generations=[[]], llm_output={"token_usage": {
        "prompt_tokens": 120, "completion_tokens": 30, "cost": 0.00012,
    }})
    rec.on_llm_end(result)
    rec.on_llm_end(result)
    assert rec.calls == 2
    assert rec.input_tokens == 240 and rec.output_tokens == 60
    assert rec.cost == pytest.approx(0.00024)


def test_missing_key_is_recorded_as_error_not_raised(portal_url):
    obs = asyncio.run(
        e1.run_case("C1", _case(), None, e1.RulePackageProvider(), model_id=e1.DEFAULT_MODEL_ID)
    )
    assert obs["error"] and "OPENROUTER_API_KEY" in obs["error"]
    assert obs["task_success"] is False


def test_run_stops_when_reported_spend_exceeds_cap(tmp_path, monkeypatch, portal_url):
    async def fake_run_case(arm, case, key, provider, model_id=None):
        return {"case_id": case["case_id"], "arm": arm, "cost_usd": 0.6,
                "task_success": True, "error": None}

    monkeypatch.setattr(e1, "run_case", fake_run_case)
    monkeypatch.setattr(e1, "load_project_dotenv", lambda: None)
    args = e1.parse_args(["--cases", "5", "--spend-stop", "1.0",
                          "--out", str(tmp_path / "out.json")])
    with pytest.raises(SystemExit):
        asyncio.run(e1.main_async(args))
    assert not (tmp_path / "out.json").exists()


def test_team_override_requires_yes(tmp_path, monkeypatch, portal_url):
    monkeypatch.setattr(e1, "load_project_dotenv", lambda: None)
    args = e1.parse_args([
        "--team-override", "--cases", "1",
        "--out", str(tmp_path / "out.json"),
    ])
    with pytest.raises(SystemExit, match="--yes"):
        asyncio.run(e1.main_async(args))


def _igndps_case(persona_suffix: str = "001") -> dict[str, Any]:
    return next(c for c in e1.load_development_cases()
                if c["case_id"].startswith(f"GEN-IGNDPS-{persona_suffix}"))


def test_igndps_case_fact_is_known_to_registry():
    case = _igndps_case()
    e1.rule_engine_verdict(e1.RulePackageProvider(), case["scheme_id"], case["profile"])


def test_igndps_scheme_has_a_rule_package():
    provider = e1.RulePackageProvider()
    provider.packages["IGNDPS-MH"]


def test_frozen_budget_pins_match_agent_config():
    pins = e1.frozen_budget_pins()
    assert pins["model_calls"] == e1.agent_config.MAX_CONVERSATION_MODEL_CALLS
    assert pins["total_tokens"] == e1.agent_config.MAX_CONVERSATION_TOKENS


def test_load_held_out_cases_from_local_custody():
    path = e1.DEFAULT_HELD_OUT
    if not path.is_file():
        pytest.skip("held-out local set not present")
    cases = e1.load_held_out_cases(path)
    assert len(cases) >= 40
    assert all("HO-" in c["case_id"] for c in cases)


def test_held_out_path_must_be_under_local_custody(tmp_path):
    bad = tmp_path / "leaked.json"
    bad.write_text(json.dumps({
        "split": "held_out", "protected": True, "personas": [],
    }))
    with pytest.raises(ValueError, match="held_out/local"):
        e1.load_held_out_cases(bad)
