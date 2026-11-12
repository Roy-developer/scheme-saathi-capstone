"""E1 harness wiring (dry run only; says nothing about real agent quality)."""

import asyncio
from pathlib import Path

from eval.harness.dry_run_model import DryRunModel
from eval.harness.e1_runner import run_e1
from eval.harness.runner import load_persona_evaluation_set

DEV = Path(__file__).resolve().parents[1] / "eval" / "development" / "personas_v1.json"


def test_e1_runs_all_configs_on_the_same_cases_and_counts_model_use():
    report = asyncio.run(run_e1(
        load_persona_evaluation_set(DEV), lambda _agent: DryRunModel(),
    ))
    assert report["mode"] == "dry_run"
    configs = report["configs"]
    assert set(configs) == {"C0", "C1", "C2"}
    assert len({c["cases"] for c in configs.values()}) == 1
    assert configs["C0"]["model_calls_per_case"] == 0
    assert configs["C1"]["model_calls_per_case"] > 0
    assert configs["C2"]["model_calls_per_case"] > 0
    assert all(c["errors"] == 0 for c in configs.values())
