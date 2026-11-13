"""Offline tests for scripts/run_e1_live.py. No network: scripted models only."""

import asyncio
import importlib.util
import json
import socket
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_e1_live.py"


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


class ScriptedAgentModel(BaseChatModel):
    """Calls evaluate_eligibility once, then replies in plain text."""

    model_name: str = "scripted"

    @property
    def _llm_type(self) -> str:
        return "scripted-e1"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("agents call the model asynchronously")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(m, ToolMessage) for m in messages):
            reply = AIMessage(content="done")
        else:
            scheme = next(
                str(m.content).split("Scheme: ", 1)[1]
                for m in messages if isinstance(m, HumanMessage)
            )
            reply = AIMessage(content="", tool_calls=[{
                "name": "evaluate_eligibility",
                "args": {"scheme_id": scheme},
                "id": "call-1",
            }])
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _case(persona_index: int = 0) -> dict[str, Any]:
    return e1.load_development_cases(1)[persona_index]


def test_loads_only_development_cases():
    cases = e1.load_development_cases()
    # 76 development cases now; the count moved when the dev dataset was extended.
    assert len(cases) == 79
    assert all("held" not in c["case_id"].lower() for c in cases)


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
    obs = asyncio.run(e1.run_case("C0", case, None, e1.RulePackageProvider()))
    assert obs["error"] is None
    assert obs["actual_result"] == case["expected"]["result"]
    assert obs["task_success"] is True
    assert obs["model_calls"] == 0 and obs["cost_usd"] == 0.0


def test_c1_single_agent_uses_rule_engine_tool(portal_url, monkeypatch):
    monkeypatch.setattr(e1, "make_model", lambda key, rec: ScriptedAgentModel(callbacks=[rec]))
    case = _case()
    obs = asyncio.run(e1.run_case("C1", case, "offline-test-key", e1.RulePackageProvider()))
    assert obs["error"] is None, obs["error"]
    assert obs["actual_result"] == case["expected"]["result"]
    assert obs["model_calls"] == 2


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
    obs = asyncio.run(e1.run_case("C1", _case(), None, e1.RulePackageProvider()))
    assert obs["error"] and "OPENROUTER_API_KEY" in obs["error"]
    assert obs["task_success"] is False


def test_run_stops_when_reported_spend_exceeds_cap(tmp_path, monkeypatch, portal_url):
    async def fake_run_case(arm, case, key, provider):
        return {"case_id": case["case_id"], "arm": arm, "cost_usd": 0.6,
                "task_success": True, "error": None}

    monkeypatch.setattr(e1, "run_case", fake_run_case)
    monkeypatch.setattr(e1, "load_project_dotenv", lambda: None)
    args = e1.parse_args(["--cases", "5", "--spend-stop", "1.0",
                          "--out", str(tmp_path / "out.json")])
    with pytest.raises(SystemExit):
        asyncio.run(e1.main_async(args))
    assert not (tmp_path / "out.json").exists()


def _igndps_case(persona_suffix: str = "001") -> dict[str, Any]:
    return next(c for c in e1.load_development_cases()
                if c["case_id"].startswith(f"GEN-IGNDPS-{persona_suffix}"))


# The IGNDPS-MH rule package and the has_disability fact are now in the repo,
# so these cases must decide without changing their expected results.
def test_igndps_case_fact_is_known_to_registry():
    case = _igndps_case()
    e1.rule_engine_verdict(e1.RulePackageProvider(), case["scheme_id"], case["profile"])


def test_igndps_scheme_has_a_rule_package():
    provider = e1.RulePackageProvider()
    provider.packages["IGNDPS-MH"]
