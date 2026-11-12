"""E1 runner: C0 fixed workflow vs C1 single agent vs C2 specialist team.

All three configurations get the same cases, the same code-owned tools
(rule engine and document check) and the same conversation budget. Only
the decision structure differs:

    C0  no model; the rule engine and checklist run in a fixed order.
    C1  one agent holds every tool (``run_single_agent_baseline``).
    C2  the eligibility and document specialists the journey graph uses.

``model_factory(agent_name)`` supplies the chat model, so the same runner
serves an offline dry run (scripted fake model, wiring check only) and a
live run (a fixed OpenRouter model ID). A dry run must never be reported
as an E1 result: it proves the harness, not the agents.

Limit: each case checks the persona's one labelled scheme, so C1's single
agent is never asked to juggle several candidates. Held-out cases and a
live model are still required for the final claim.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel

from eval.harness.runner import persona_input
from eval.schema import PersonaEvaluationSet
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.workflow.document_agent import run_document_specialist
from src.workflow.eligibility_agent import run_eligibility_specialist
from src.workflow.single_agent import run_single_agent_baseline

CONFIG_IDS = ("C0", "C1", "C2")
ModelFactory = Callable[[str], BaseChatModel | None]


def _usage(traces: list[list[dict[str, Any]]]) -> dict[str, int]:
    """Count model calls and tokens from scrubbed trace metadata."""

    calls = tokens = 0
    for trace in traces:
        steps = {event["step"] for event in trace if event.get("status") != "step_limit"}
        calls += len(steps)
        tokens += sum(
            int(event.get("input_tokens", 0)) + int(event.get("output_tokens", 0))
            for event in trace
        )
    return {"model_calls": calls, "tokens": tokens}


async def _run_case(
    config_id: str, persona, scheme_id: str, provider: RulePackageProvider,
    model_factory: ModelFactory, budget: dict[str, int],
) -> dict[str, Any]:
    registry, package = provider.registry, provider.packages[scheme_id]
    facts = persona_input(persona, registry)

    async def evaluate(_scheme_id: str | None = None):
        return evaluate_mock_eligibility(facts, package, registry=registry)

    async def inspect(_scheme_id: str | None = None) -> dict[str, object]:
        # Same stub in every configuration: documents are not under test.
        return {"status": "checklist_complete", "discrepancies": []}

    traces: list[list[dict[str, Any]]] = []
    if config_id == "C0":
        verdict = (await evaluate()).result
        if verdict == "eligible":
            await inspect()
        status = "deterministic"
    elif config_id == "C1":
        outcome, _, trace, status = await run_single_agent_baseline(
            model_factory("single"), [scheme_id], "en", budget, evaluate, inspect,
        )
        traces.append(trace)
        response = outcome.verdicts.get(scheme_id)
        verdict = response.result if response else "no_verdict"
    else:
        response, _, trace, status = await run_eligibility_specialist(
            model_factory("eligibility"), scheme_id, "en", budget, evaluate,
        )
        traces.append(trace)
        verdict = response.result if response else "no_verdict"
        if verdict == "eligible":
            _, _, doc_trace, _ = await run_document_specialist(
                model_factory("documents"), scheme_id, "en", budget, inspect,
            )
            traces.append(doc_trace)
    return {"verdict": verdict, "status": status, **_usage(traces)}


async def run_e1(
    evaluation_set: PersonaEvaluationSet,
    model_factory: ModelFactory,
    *,
    config_ids: tuple[str, ...] = CONFIG_IDS,
    budget: dict[str, int] | None = None,
    provider: RulePackageProvider | None = None,
    mode: str = "dry_run",
) -> dict[str, Any]:
    """Run every configuration on every case and summarise the comparison."""

    provider = provider or RulePackageProvider()
    report: dict[str, Any] = {"mode": mode, "case_count": 0, "configs": {}}
    for config_id in config_ids:
        rows: list[dict[str, Any]] = []
        for persona in evaluation_set.personas:
            for scheme_id, expected in persona.expected_by_scheme.items():
                if scheme_id not in provider.packages:
                    continue
                started = time.perf_counter()
                try:
                    result = await _run_case(
                        config_id, persona, scheme_id, provider,
                        model_factory, dict(budget or {}),
                    )
                    error = None
                except Exception as exc:  # recorded, never hidden
                    result = {"verdict": "error", "status": "error",
                              "model_calls": 0, "tokens": 0}
                    error = type(exc).__name__
                rows.append({
                    "persona_id": persona.persona_id, "scheme_id": scheme_id,
                    "expected": expected.result, "error": error,
                    "latency_ms": (time.perf_counter() - started) * 1000, **result,
                })
        latencies = sorted(r["latency_ms"] for r in rows)
        n = len(rows)
        report["case_count"] = n
        report["configs"][config_id] = {
            "task_success": sum(r["verdict"] == r["expected"] for r in rows),
            "cases": n,
            "errors": sum(r["error"] is not None for r in rows),
            "no_verdict": sum(r["verdict"] == "no_verdict" for r in rows),
            "model_calls_per_case": sum(r["model_calls"] for r in rows) / n if n else 0,
            "tokens_per_case": sum(r["tokens"] for r in rows) / n if n else 0,
            "median_latency_ms": statistics.median(latencies) if latencies else 0,
            "p95_latency_ms": latencies[min(n - 1, int(0.95 * n))] if n else 0,
            "rows": rows,
        }
    return report
