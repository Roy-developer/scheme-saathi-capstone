"""Load and inventory E1–E4 experiment configs so they are not orphaned JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from eval.schema import ExperimentConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPERIMENTS_DIR = PROJECT_ROOT / "eval" / "experiments"
EXPECTED_IDS = ("E1", "E2", "E3", "E4")


def load_experiment_config(path: Path) -> ExperimentConfig:
    """Validate one experiment JSON file."""

    try:
        return ExperimentConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except ValidationError as error:
        raise ValueError(f"Invalid experiment config {path}: {error}") from error


def load_experiment_inventory(
    experiments_dir: Path = DEFAULT_EXPERIMENTS_DIR,
) -> dict[str, Any]:
    """Load every experiment JSON and summarise runnable vs blocked status."""

    paths = sorted(experiments_dir.glob("e*.json"))
    loaded: list[tuple[Path, ExperimentConfig]] = [
        (path, load_experiment_config(path)) for path in paths
    ]
    by_id = {item.experiment_id: path for path, item in loaded}
    missing = [experiment_id for experiment_id in EXPECTED_IDS if experiment_id not in by_id]
    if missing:
        raise ValueError(f"Missing experiment configs: {', '.join(missing)}")

    return {
        "experiment_count": len(loaded),
        "expected_ids": list(EXPECTED_IDS),
        "experiments": [
            {
                "experiment_id": item.experiment_id,
                "title": item.title,
                "status": item.status,
                "blocker": item.blocker,
                "path": str(path),
            }
            for path, item in loaded
        ],
    }
