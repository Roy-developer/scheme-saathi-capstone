"""Prove Role 5 eval assets are loadable and used by the umbrella runner."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

from eval.harness.experiments import load_experiment_inventory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UMBRELLA = PROJECT_ROOT / "scripts" / "run_role5_dev_evals.py"


def test_experiment_configs_are_inventoried() -> None:
    inventory = load_experiment_inventory()

    assert inventory["experiment_count"] == 4
    ids = sorted(item["experiment_id"] for item in inventory["experiments"])
    assert ids == ["E1", "E2", "E3", "E4"]
    e2 = next(item for item in inventory["experiments"] if item["experiment_id"] == "E2")
    assert e2["status"] == "offline_and_scoped_application_ablation_runnable"


def test_role5_umbrella_runner_writes_reports(tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    previous = sys.argv[:]
    try:
        sys.argv = [str(UMBRELLA), "--output-dir", str(output_dir)]
        try:
            runpy.run_path(str(UMBRELLA), run_name="__main__")
            raised = None
        except SystemExit as exit_info:
            raised = exit_info
    finally:
        sys.argv = previous

    assert raised is not None
    assert raised.code in (0, None)
    for name in (
        "eligibility_dev_latest.json",
        "reflexion_e3_inventory.json",
        "red_team_dev_latest.json",
        "e2_defences_dev_latest.json",
        "label_agreement_dev_latest.json",
        "simulated_citizen_smoke.json",
        "experiments_inventory.json",
    ):
        assert (output_dir / name).exists()
