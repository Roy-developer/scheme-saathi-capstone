"""Generate ≥40 protected held-out personas into Role-5-only local storage.

Writes ``eval/held_out/local/personas_held_out_v1.json`` (gitignored).
Does not commit secrets into the app image. Related boundary families stay
together. Expected outcomes are copied from transformed development seeds and
MUST be dual-labelled by Role 1 before a final held-out claim.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEV_SET = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"
DEFAULT_OUT = PROJECT_ROOT / "eval" / "held_out" / "local" / "personas_held_out_v1.json"


def _shift_iso(value: str | None, days: int) -> str | None:
    if value is None:
        return None
    return (date.fromisoformat(value) + timedelta(days=days)).isoformat()


def _transform_persona(raw: dict, *, index: int, wave: int) -> dict:
    persona = copy.deepcopy(raw)
    old_id = persona["persona_id"]
    persona["persona_id"] = f"HO-{old_id}-W{wave}-{index:02d}"
    persona["split"] = "held_out"
    persona["protected"] = True
    persona["description"] = (
        f"[HELD-OUT wave {wave}] " + persona.get("description", "")
    )
    shift = 7 * wave + index
    if persona.get("profile"):
        profile = persona["profile"]
        for key in ("date_of_birth", "application_date"):
            if key in profile and isinstance(profile[key], str):
                profile[key] = _shift_iso(profile[key], shift)
    if persona.get("typed_facts"):
        facts = persona["typed_facts"]
        for key in ("date_of_birth", "application_date"):
            if key in facts and isinstance(facts[key], str):
                facts[key] = _shift_iso(facts[key], shift)
    # Strip development labels; Role 1 dual-labels held-out separately.
    persona["labels"] = [
        {
            "labeller_id": "role5-heldout-seed",
            "scheme_id": scheme_id,
            "result": expected["result"],
            "status": "pending",
            "note": "Seed expectation from transformed development case; dual-label pending",
        }
        for scheme_id, expected in persona["expected_by_scheme"].items()
    ]
    return persona


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-set", type=Path, default=DEV_SET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--minimum", type=int, default=40)
    args = parser.parse_args(argv)

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from eval.schema import PersonaEvaluationSet

    source = json.loads(args.dev_set.read_text(encoding="utf-8"))
    seeds = source["personas"]
    held_out: list[dict] = []
    wave = 1
    while len(held_out) < args.minimum:
        for index, seed in enumerate(seeds, start=1):
            held_out.append(_transform_persona(seed, index=index, wave=wave))
            if len(held_out) >= args.minimum:
                break
        wave += 1

    payload = {
        "dataset_version": "heldout-1.0.0",
        "split": "held_out",
        "protected": True,
        "annotation_note": (
            "Role-5-only held-out personas generated from development boundary "
            "families with date shifts. Not dual-labelled yet. Do not commit. "
            "Do not load into the agent image or CI app checkout."
        ),
        "personas": held_out[: max(args.minimum, 40)],
    }
    PersonaEvaluationSet.model_validate(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "persona_count": len(payload["personas"]),
                "protected": True,
                "split": "held_out",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
