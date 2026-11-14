"""Development-only live E1 comparison: C0 fixed workflow, C1 single agent, C2 specialist team.

Development personas only (eval/development/*). Held-out sets are refused.
The rule engine is the only eligibility decider. C0 uses the journey without a
model; C1 uses ``single_agent_provider`` (real journey single-agent path); C2
uses the specialist team on the same graph.

Usage:
    python scripts/run_e1_live.py --cases 5 --out eval/reports/e1_live_dev_costtest.json
    python scripts/run_e1_live.py --team-override --yes --out eval/reports/e1_team_override_live.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path
from statistics import median
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
from src.workflow import agent_config  # noqa: E402
from src.workflow.journey import JourneyRequest, build_journey_graph, run_journey  # noqa: E402

DEFAULT_MODEL_ID = "openai/gpt-4o-mini"
FREE_MODEL_ID = "nvidia/nemotron-3.5-lightning:free"
DEV_FILES = (
    ROOT / "eval" / "development" / "personas_v1.json",
    ROOT / "eval" / "development" / "personas_generated_v2.json",
)
DEFAULT_HELD_OUT = (
    ROOT / "eval" / "held_out" / "local" / "personas_held_out_v1.json"
)
REPORT_LABEL = (
    "DEVELOPMENT-ONLY functional E1 comparison. Not a held-out result. "
    "Not a claim of agent quality."
)
TEAM_OVERRIDE_LABEL = (
    "TEAM-OVERRIDE development E1 (held-out waived). "
    "Not a PDF unseen held-out cost-benefit claim."
)
HELD_OUT_LABEL = (
    "HELD-OUT E1 comparison on Role-5 local custody personas. "
    "Generated/transformed seeds are not dual-labelled; not a final PDF claim."
)
ARMS = ("C0", "C1", "C2")
FIXED_TODAY = date(2026, 11, 13)


def normalize_verdict(result: object) -> object:
    """Map the UI alias ``cant_tell`` to the engine verdict."""

    return "need_more_information" if result == "cant_tell" else result


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


def _cases_from_persona_file(
    path: Path,
    *,
    require_split: str,
    require_protected: bool,
    provider: RulePackageProvider,
) -> list[dict[str, Any]]:
    """Load persona×scheme cases from one evaluation set file."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("split") != require_split or bool(data.get("protected")) != require_protected:
        raise ValueError(
            f"{path.name}: expected split={require_split!r} protected={require_protected}"
        )
    cases: list[dict[str, Any]] = []
    for persona in data["personas"]:
        if persona.get("split") != require_split or bool(persona.get("protected")) != require_protected:
            raise ValueError(f"{persona.get('persona_id')} has wrong split/protection")
        for scheme_id, expected in persona["expected_by_scheme"].items():
            if scheme_id not in provider.packages:
                continue
            profile = persona.get("profile", persona.get("typed_facts")) or {}
            cases.append({
                "case_id": f"{persona['persona_id']}::{scheme_id}",
                "scheme_id": scheme_id,
                "profile": profile,
                "expected": {
                    **expected,
                    "result": normalize_verdict(expected.get("result")),
                },
            })
    return cases


def load_development_cases(
    limit: int | None = None,
    *,
    provider: RulePackageProvider | None = None,
) -> list[dict[str, Any]]:
    """Read development personas only. Refuses anything not marked development."""

    active = provider or RulePackageProvider()
    cases: list[dict[str, Any]] = []
    for path in DEV_FILES:
        cases.extend(
            _cases_from_persona_file(
                path,
                require_split="development",
                require_protected=False,
                provider=active,
            )
        )
    return cases[:limit] if limit is not None else cases


def load_held_out_cases(
    path: Path,
    limit: int | None = None,
    *,
    provider: RulePackageProvider | None = None,
) -> list[dict[str, Any]]:
    """Read Role-5 local held-out personas. Never package these into the app image."""

    if "held_out/local" not in path.as_posix().replace("\\", "/"):
        raise ValueError("Held-out E1 cases must live under eval/held_out/local/")
    if not path.is_file():
        raise FileNotFoundError(
            f"Held-out set missing: {path}. Generate with "
            "scripts/generate_held_out_personas.py"
        )
    active = provider or RulePackageProvider()
    cases = _cases_from_persona_file(
        path,
        require_split="held_out",
        require_protected=True,
        provider=active,
    )
    if len(cases) < 40:
        raise ValueError(f"Held-out E1 needs ≥40 cases; found {len(cases)} in {path}")
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
    """Return an awaitable runner for one arm (fresh journey graph per case)."""

    async def eligibility_tool(_client, scheme_id, profile):
        return evaluate_mock_eligibility(
            profile, provider.packages[scheme_id], provider.registry,
        )

    async def identity(query: str) -> str:
        return query

    async def no_search(_client, _query):
        return []

    async def uncertain(_fact, _question, _reply):
        from src.workflow.intake import AnswerInterpretation
        return AnswerInterpretation(kind="uncertain", confidence=0.0)

    graph = build_journey_graph(
        None,
        provider.packages,
        search_tool=no_search,
        eligibility_tool=eligibility_tool,
        query_rewriter=identity,
        answer_interpreter=uncertain,
        single_agent_provider=model if arm == "C1" else None,
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
        if verdict is None:
            return None
        return normalize_verdict(verdict.result)

    return run


def make_model(api_key: str, recorder: UsageRecorder, model_id: str) -> BaseChatModel:
    model = openrouter_chat_model(api_key, model_id, max_tokens=512)
    model.extra_body = {**(model.extra_body or {}), "usage": {"include": True}}
    # Journey agents invoke the model through LangChain config; attribute
    # assignment alone does not attach callbacks, so bind them explicitly.
    return model.with_config(callbacks=[recorder])


def frozen_budget_pins() -> dict[str, int]:
    """Shared conversation ceilings from agent_config (E1 freeze pins)."""

    return {
        "model_calls": agent_config.MAX_CONVERSATION_MODEL_CALLS,
        "agent_tool_calls": agent_config.MAX_CONVERSATION_TOOL_CALLS,
        "domain_calls": agent_config.MAX_CONVERSATION_DOMAIN_TOOL_CALLS,
        "agent_steps": agent_config.MAX_CONVERSATION_AGENT_STEPS,
        "total_tokens": agent_config.MAX_CONVERSATION_TOKENS,
        "max_completion_tokens": agent_config.MAX_COMPLETION_TOKENS,
    }


def summarize_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-arm task success, cost, tokens, and latency for the comparison report."""

    per_arm: dict[str, Any] = {}
    for arm in ARMS:
        rows = [row for row in observations if row["arm"] == arm]
        latencies = [float(row["latency_seconds"]) for row in rows]
        successes = sum(1 for row in rows if row.get("task_success"))
        errors = sum(1 for row in rows if row.get("error"))
        per_arm[arm] = {
            "cases": len(rows),
            "task_success": successes,
            "task_success_rate": round(successes / max(len(rows), 1), 4),
            "errors": errors,
            "model_calls": sum(int(row.get("model_calls") or 0) for row in rows),
            "model_calls_per_case": round(
                sum(int(row.get("model_calls") or 0) for row in rows) / max(len(rows), 1),
                4,
            ),
            "input_tokens": sum(int(row.get("input_tokens") or 0) for row in rows),
            "output_tokens": sum(int(row.get("output_tokens") or 0) for row in rows),
            "cost_usd": round(sum(float(row.get("cost_usd") or 0) for row in rows), 8),
            "cost_per_case_usd": round(
                sum(float(row.get("cost_usd") or 0) for row in rows) / max(len(rows), 1),
                8,
            ),
            "median_latency_seconds": round(median(latencies), 4) if latencies else None,
            "p95_latency_seconds": (
                round(sorted(latencies)[max(int(0.95 * len(latencies)) - 1, 0)], 4)
                if latencies
                else None
            ),
        }
    return per_arm


async def run_case(
    arm: str,
    case: dict[str, Any],
    api_key: str | None,
    provider: RulePackageProvider,
    *,
    model_id: str,
) -> dict[str, Any]:
    recorder = UsageRecorder()
    started = time.perf_counter()
    error = None
    actual = None
    try:
        model = None
        if arm != "C0":
            if not api_key:
                raise RuntimeError("OPENROUTER_API_KEY missing; cannot run live arm")
            model = make_model(api_key, recorder, model_id)
        actual = await build_arm(arm, model, provider, case)()
    except Exception as exc:  # recorded, not raised: one bad case must not stop the run
        error = f"{type(exc).__name__}: {exc}"[:300]
        recorder.errors += 1
    latency = time.perf_counter() - started
    expected = normalize_verdict(case["expected"]["result"])
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
    model_id = args.model
    api_key, _ = openrouter_chat_settings(model_id)
    provider = RulePackageProvider()
    if args.held_out and args.team_override:
        raise SystemExit("use either --held-out or --team-override, not both")
    if args.held_out:
        if not args.yes:
            raise SystemExit("held-out E1 requires --yes (Role-5 custody run)")
        cases = load_held_out_cases(args.held_out_path, args.cases, provider=provider)
        claim_level = "held_out_role5_local"
        label = HELD_OUT_LABEL
        split = "held_out"
        protected = True
        interpretation = (
            "Held-out custody scored with journey-wired C0/C1/C2. Seeds are "
            "transformed development personas without independent dual labels; "
            "not a final PDF E1 claim until Role-1 dual-labelling and freeze "
            "repeats are done."
        )
    else:
        if args.team_override and not args.yes:
            raise SystemExit("team-override requires --yes (held-out waived; not PDF HO)")
        cases = load_development_cases(args.cases, provider=provider)
        claim_level = (
            "team_override_dev_personas" if args.team_override else "development_only"
        )
        label = TEAM_OVERRIDE_LABEL if args.team_override else REPORT_LABEL
        split = "development"
        protected = False
        interpretation = (
            "Same task_success across arms on synthetic single-scheme evaluate "
            "cases does not establish a specialist-team quality benefit; compare "
            "cost/latency in per_arm. Not PDF held-out."
        )
    observations: list[dict[str, Any]] = []
    spent = 0.0
    for case in cases:
        for arm in ARMS:
            obs = await run_case(arm, case, api_key, provider, model_id=model_id)
            observations.append(obs)
            spent += obs["cost_usd"]
            if spent > args.spend_stop:
                raise SystemExit(
                    f"stopped: reported spend {spent:.4f} exceeds {args.spend_stop}"
                )
    per_arm = summarize_observations(observations)
    summary = {
        "label": label,
        "claim_level": claim_level,
        "split": split,
        "protected": protected,
        "model_id": model_id,
        "c1_path": "journey.single_agent_provider",
        "c2_path": "journey.specialist_team",
        "budget_pins": frozen_budget_pins(),
        "freeze_pin": "eval/freeze/manifest.json#e1_team_override_freeze",
        "held_out_path": str(args.held_out_path) if args.held_out else None,
        "cases": len(cases),
        "observations": observations,
        "per_arm": per_arm,
        "total_cost_usd": round(spent, 8),
        "cost_per_case_usd": round(spent / max(len(cases), 1), 8),
        "interpretation": interpretation,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "cases": summary["cases"],
                "total_cost_usd": summary["total_cost_usd"],
                "cost_per_case_usd": summary["cost_per_case_usd"],
                "per_arm": {
                    arm: {
                        "task_success": row["task_success"],
                        "cost_usd": row["cost_usd"],
                        "model_calls_per_case": row["model_calls_per_case"],
                    }
                    for arm, row in per_arm.items()
                },
                "output": str(args.out),
            },
            indent=2,
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=None)
    parser.add_argument("--spend-stop", type=float, default=1.0)
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument(
        "--free-model",
        action="store_true",
        help=f"Use {FREE_MODEL_ID} (overrides --model)",
    )
    parser.add_argument(
        "--team-override",
        action="store_true",
        help="Waive held-out for a development team-override record (requires --yes)",
    )
    parser.add_argument(
        "--held-out",
        action="store_true",
        help="Score Role-5 local held-out personas (requires --yes; not dual-labelled PDF)",
    )
    parser.add_argument(
        "--held-out-path",
        type=Path,
        default=DEFAULT_HELD_OUT,
        help="Path under eval/held_out/local/ (default personas_held_out_v1.json)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm team-override / held-out / paid-or-free live run",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "eval" / "reports" / "e1_live_dev.json",
    )
    args = parser.parse_args(argv)
    if args.free_model:
        args.model = FREE_MODEL_ID
    return args


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
