"""Live E1 run (paid OpenRouter calls) on DEVELOPMENT personas only.

Uses the key and OPENROUTER_CHAT_MODEL from the local .env (loaded by
``src.config``); the key is never printed. Held-out cases are Role 5's and
are not read here, so results are development evidence, not the final E1
claim. Hard caps stop the run before it can overspend.

    python scripts/run_e1_live.py --cases 3 --repeats 1     # smoke test
    python scripts/run_e1_live.py --repeats 3 --max-calls 900
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=0, help="limit cases (0 = all)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-calls", type=int, default=900,
                        help="stop if cumulative model calls would exceed this")
    args = parser.parse_args()

    from eval.harness.e1_runner import run_e1
    from eval.harness.runner import load_persona_evaluation_set
    from src.config import openrouter_chat_settings
    from src.llm_client import DEFAULT_CHAT_MODEL, openrouter_chat_model

    api_key, model_id = openrouter_chat_settings(DEFAULT_CHAT_MODEL)
    if not api_key:
        print("No OPENROUTER_API_KEY in .env; nothing run.")
        return 2
    print(f"model: {model_id} (same for C1 and C2); repeats={args.repeats}")

    evaluation_set = load_persona_evaluation_set(
        ROOT / "eval" / "development" / "personas_v1.json")
    if args.cases:
        evaluation_set = evaluation_set.model_copy(
            update={"personas": evaluation_set.personas[: args.cases]})

    def factory(_agent: str):
        return openrouter_chat_model(api_key, model_id)

    async def run_all() -> list[dict]:
        # One event loop for every repeat: the OpenRouter client caches HTTP
        # connections, which break if a loop is closed between repeats.
        runs, total_calls = [], 0
        for repeat in range(1, args.repeats + 1):
            report = await run_e1(evaluation_set, factory, mode="live_development")
            report["model_id"], report["repeat"] = model_id, repeat
            calls = sum(
                row["model_calls"]
                for cfg in report["configs"].values() for row in cfg["rows"])
            total_calls += calls
            runs.append(report)
            print(f"repeat {repeat}: {calls} model calls (total {total_calls})")
            for config_id, s in report["configs"].items():
                print(f"  {config_id}: success {s['task_success']}/{s['cases']}, "
                      f"errors {s['errors']}, no_verdict {s['no_verdict']}, "
                      f"calls/case {s['model_calls_per_case']:.2f}, "
                      f"tokens/case {s['tokens_per_case']:.0f}, "
                      f"median {s['median_latency_ms']:.0f} ms, "
                      f"p95 {s['p95_latency_ms']:.0f} ms")
            if total_calls >= args.max_calls:
                print(f"call cap {args.max_calls} reached; stopping.")
                break
        return runs

    runs = asyncio.run(run_all())
    out = ROOT / "eval" / "reports" / "e1_live_dev_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(runs, indent=2), encoding="utf-8")
    print(f"wrote {out} (development personas; not the final held-out E1 claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
