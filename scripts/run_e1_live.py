"""Development-only live E1 comparison: C0 fixed workflow, C1 single agent, C2 specialist team.

Development personas only (eval/development/*). Held-out sets are refused.
The rule engine is the only eligibility decider: every arm asks
``evaluate_mock_eligibility`` for the verdict. The model only chooses which
tool to call (C1) or drives the existing specialist agents (C2).

Usage:
    .venv/Scripts/python.exe scripts/run_e1_live.py --cases 5 --out eval/reports/e1_live_dev_costtest.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.language_models import BaseChatModel  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from src.api.eligibility import evaluate_mock_eligibility  # noqa: E402
from src.config import load_project_dotenv, openrouter_chat_settings  # noqa: E402
from src.llm_client import openrouter_chat_model  # noqa: E402
from src.rules.data_provider import RulePackageProvider  # noqa: E402
from src.rules.facts import HouseholdProfile  # noqa: E402
from src.workflow.journey import JourneyRequest, build_journey_graph, run_journey  # noqa: E402

MODEL_ID = "openai/gpt-4o-mini"
DEV_FILES = (
    ROOT / "eval" / "development" / "personas_v1.json",
    ROOT / "eval" / "development" / "personas_generated_v2.json",
)
REPORT_LABEL = (
    "DEVELOPMENT-ONLY functional E1 comparison. Not a held-out result. "
    "Not a claim of agent quality."
)
ARMS = ("C0", "C1", "C2")
FIXED_TODAY = date(2026, 11, 13)


class UsageRecorder(BaseCallbackHandler):
    """Counts model calls and reads token counts and OpenRouter-reported cost."""

    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost = 0.0
        self.errors = 0

    def on_llm_end(self, response: Any, **_: Any) -> None:
        self.calls += 1
        llm_output = response.llm_output or {}
        usage = llm_output.get("token_usage") or {}
        self.input_tokens += int(usage.get("prompt_tokens") or 0)
        self.output_tokens += int(usage.get("completion_tokens") or 0)
        self.cost += float(usage.get("cost") or 0.0)

    def on_llm_error(self, *_: Any, **__: Any) -> None:
        self.errors += 1


def load_development_cases(limit: int | None = None) -> list[dict[str, Any]]:
    """Read development personas only. Refuses anything not marked development."""

    cases: list[dict[str, Any]] = []
    for path in DEV_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("split") != "development" or data.get("protected") is not False:
            raise ValueError(f"{path.name} is not a development, unprotected file")
        for persona in data["personas"]:
            if persona.get("split") != "development" or persona.get("protected") is not False:
                raise ValueError(f"{persona.get('persona_id')} is not development")
            for scheme_id, expected in persona["expected_by_scheme"].items():
                cases.append({
                    "case_id": f"{persona['persona_id']}::{scheme_id}",
                    "scheme_id": scheme_id,
                    # v1 uses "profile"; v2 uses "typed_facts".
                    "profile": persona.get("profile", persona.get("typed_facts")),
                    "expected": expected,
                })
    return cases[:limit] if limit is not None else cases


def rule_engine_verdict(provider: RulePackageProvider, scheme_id: str,
                        profile: dict[str, Any]) -> Any:
    """The only eligibility decider: the deterministic rule engine."""

    store = HouseholdProfile.from_answers(profile, provider.registry)
    return evaluate_mock_eligibility(
        store, provider.packages[scheme_id], provider.registry,
    )


def build_arm(arm: str, model: BaseChatModel | None, provider: RulePackageProvider,
              case: dict[str, Any]) -> Any:
    """Return an awaitable runner for one arm (fresh graph per case)."""

    async def eligibility_tool(_client, scheme_id, profile):
        # Journey passes a HouseholdProfile; rebuild the verdict from it.
        return evaluate_mock_eligibility(profile, provider.packages[scheme_id], provider.registry)

    async def identity(query: str) -> str:
        return query

    async def no_search(_client, _query):
        return []

    async def uncertain(_fact, _question, _reply):
        from src.workflow.intake import AnswerInterpretation
        return AnswerInterpretation(kind="uncertain", confidence=0.0)

    if arm == "C1":
        return single_agent_runner(model, provider, case)

    graph = build_journey_graph(
        None,
        provider.packages,
        search_tool=no_search,
        eligibility_tool=eligibility_tool,
        query_rewriter=identity,
        answer_interpreter=uncertain,
        model_provider=model if arm == "C2" else None,
        eligibility_model_provider=model if arm == "C2" else None,
        checkpointer=MemorySaver(),
        today=lambda: FIXED_TODAY,
        fact_registry=provider.registry,
        rule_bundles=provider.bundles,
    )

    async def run() -> str | None:
        response = await run_journey(graph, JourneyRequest(
            action="evaluate", scheme_id=case["scheme_id"], profile=case["profile"],
        ))
        verdict = response.eligibility_result
        return verdict.result if verdict is not None else None

    return run


def single_agent_runner(model: BaseChatModel | None, provider: RulePackageProvider,
                        case: dict[str, Any]):
    """C1: one agent with the same rule-engine tool; it chooses the call only."""

    from langchain.agents import create_agent
    from langchain_core.tools import tool

    @tool
    def evaluate_eligibility(scheme_id: str) -> str:
        """Ask the rule engine for the eligibility result of one scheme."""
        verdict = rule_engine_verdict(provider, scheme_id, case["profile"])
        return verdict.result

    async def run() -> str | None:
        agent = create_agent(
            model=model,
            tools=[evaluate_eligibility],
            system_prompt=(
                "Check one welfare scheme for the household. Call "
                "evaluate_eligibility with the scheme id, then reply with the result."
            ),
        )
        result = await agent.ainvoke({"messages": [
            {"role": "user", "content": f"Scheme: {case['scheme_id']}"},
        ]})
        for message in reversed(result["messages"]):
            if getattr(message, "type", "") == "tool":
                return str(message.content)
        return None

    return run


def make_model(api_key: str, recorder: UsageRecorder) -> BaseChatModel:
    model = openrouter_chat_model(api_key, MODEL_ID, max_tokens=512)
    # Ask OpenRouter for the reported cost in the usage block.
    model.extra_body = {**(model.extra_body or {}), "usage": {"include": True}}
    model.callbacks = [recorder]
    return model


async def run_case(arm: str, case: dict[str, Any], api_key: str | None,
                   provider: RulePackageProvider) -> dict[str, Any]:
    recorder = UsageRecorder()
    started = time.perf_counter()
    error = None
    actual = None
    try:
        model = None
        if arm != "C0":
            if not api_key:
                raise RuntimeError("OPENROUTER_API_KEY missing; cannot run live arm")
            model = make_model(api_key, recorder)
        actual = await build_arm(arm, model, provider, case)()
    except Exception as exc:  # recorded, not raised: one bad case must not stop the run
        error = f"{type(exc).__name__}: {exc}"[:300]
        recorder.errors += 1
    latency = time.perf_counter() - started
    expected = case["expected"]["result"]
    return {
        "case_id": case["case_id"],
        "arm": arm,
        "expected_result": expected,
        "actual_result": actual,
        "task_success": error is None and actual == expected,
        "model_calls": recorder.calls,
        "domain_calls": 1,
        "input_tokens": recorder.input_tokens,
        "output_tokens": recorder.output_tokens,
        "latency_seconds": round(latency, 3),
        "cost_usd": round(recorder.cost, 8),
        "error": error,
    }


async def main_async(args: argparse.Namespace) -> None:
    load_project_dotenv()
    api_key, _ = openrouter_chat_settings(MODEL_ID)
    provider = RulePackageProvider()
    cases = load_development_cases(args.cases)
    observations: list[dict[str, Any]] = []
    spent = 0.0
    for case in cases:
        for arm in ARMS:
            obs = await run_case(arm, case, api_key, provider)
            observations.append(obs)
            spent += obs["cost_usd"]
            if spent > args.spend_stop:
                raise SystemExit(f"stopped: reported spend {spent:.4f} exceeds {args.spend_stop}")
    summary = {
        "label": REPORT_LABEL,
        "split": "development",
        "protected": False,
        "model_id": MODEL_ID,
        "cases": len(cases),
        "observations": observations,
        "total_cost_usd": round(spent, 8),
        "cost_per_case_usd": round(spent / max(len(cases), 1), 8),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("cases", "total_cost_usd", "cost_per_case_usd")}))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=None)
    parser.add_argument("--spend-stop", type=float, default=1.0)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "eval" / "reports" / "e1_live_dev.json")
    return parser.parse_args(argv)


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
