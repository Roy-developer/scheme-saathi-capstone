"""E4 team-override dual-label agreement (Cohen's κ) without smoke copy.

Attaches the two Role-1 model-assisted sheets plus the APY extension onto the
development persona set and scores κ. Honest claim: model-assisted dual labels,
not independent human Role-1 labels. Does not mutate personas_v1.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"
SHEET_A = PROJECT_ROOT / "eval" / "development" / "role1_model_assisted_labels.json"
SHEET_B = PROJECT_ROOT / "eval" / "development" / "role1_model_assisted_labels_2.json"
APY_EXT = PROJECT_ROOT / "eval" / "development" / "role1_model_assisted_labels_apy.json"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "eval"
    / "reports"
    / "e4_team_override_label_agreement_2026-11-13.json"
)
DEFAULT_MERGED = (
    PROJECT_ROOT / "eval" / "development" / "e4_team_override_dual_labels.json"
)

LABELLER_A = "model-assisted-check"
LABELLER_B = "model-assisted-check-2"
NOTE = (
    "Model-assisted dual label for E4 team-override κ; "
    "NOT an independent human Role-1 label"
)


def _load_sheet_labels(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    labels = data.get("labels")
    if not isinstance(labels, list):
        raise ValueError(f"{path}: expected top-level 'labels' list")
    return labels


def _load_apy_extension(path: Path) -> dict[str, list[dict[str, object]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    by_labeller = data.get("labels_by_labeller")
    if not isinstance(by_labeller, dict):
        raise ValueError(f"{path}: expected labels_by_labeller")
    return {
        str(labeller_id): list(records)
        for labeller_id, records in by_labeller.items()
    }


def attach_e4_dual_labels(evaluation_set):  # type: ignore[no-untyped-def]
    """Attach both model-assisted labellers (live sheets + APY extension)."""

    from eval.harness.agreement import attach_external_labels

    sheet_a = _load_sheet_labels(SHEET_A) + _load_apy_extension(APY_EXT)[LABELLER_A]
    sheet_b = _load_sheet_labels(SHEET_B) + _load_apy_extension(APY_EXT)[LABELLER_B]
    evaluation_set = attach_external_labels(
        evaluation_set,
        sheet_a,
        labeller_id=LABELLER_A,
        note=NOTE,
    )
    return attach_external_labels(
        evaluation_set,
        sheet_b,
        labeller_id=LABELLER_B,
        note=NOTE,
    )


def _merged_sheet(evaluation_set) -> dict[str, object]:  # type: ignore[no-untyped-def]
    rows: list[dict[str, object]] = []
    for persona in evaluation_set.personas:
        for label in persona.labels:
            if label.labeller_id not in {LABELLER_A, LABELLER_B}:
                continue
            rows.append(
                {
                    "persona_id": persona.persona_id,
                    "scheme_id": label.scheme_id,
                    "labeller_id": label.labeller_id,
                    "result": label.result,
                    "note": label.note,
                }
            )
    rows.sort(key=lambda row: (str(row["persona_id"]), str(row["scheme_id"]), str(row["labeller_id"])))
    return {
        "dataset_version": evaluation_set.dataset_version,
        "labeller_a": LABELLER_A,
        "labeller_b": LABELLER_B,
        "claim": (
            "Model-assisted dual labels for E4 team-override (n=46). "
            "Not independent human Role-1 labels; not PDF held-out."
        ),
        "label_count": len(rows),
        "labels": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_SET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--merged-sheet", type=Path, default=DEFAULT_MERGED)
    args = parser.parse_args(argv)

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from eval.harness.agreement import agreement_report
    from eval.harness.runner import load_persona_evaluation_set, write_report

    evaluation_set = attach_e4_dual_labels(load_persona_evaluation_set(args.eval_set))
    report = agreement_report(
        evaluation_set,
        labeller_a=LABELLER_A,
        labeller_b=LABELLER_B,
    )
    report["smoke_copy"] = False
    report["claim_level"] = "team_override_dev_personas"
    report["independence"] = (
        "model_assisted_dual_not_human_role1; "
        "APY 12 same-session extension; live 34 from prior dual AI sessions"
    )
    report["bar"] = "team_override_dev_personas"
    report["eval_set"] = str(args.eval_set)
    report["sources"] = {
        "sheet_a": str(SHEET_A.relative_to(PROJECT_ROOT)),
        "sheet_b": str(SHEET_B.relative_to(PROJECT_ROOT)),
        "apy_extension": str(APY_EXT.relative_to(PROJECT_ROOT)),
    }
    if report.get("smoke_copy"):
        raise SystemExit("refusing to write: smoke_copy unexpectedly true")

    merged = _merged_sheet(evaluation_set)
    args.merged_sheet.parent.mkdir(parents=True, exist_ok=True)
    args.merged_sheet.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    write_report(report, args.output)
    print(
        json.dumps(
            {
                "paired_label_count": report["paired_label_count"],
                "cohens_kappa": report["cohens_kappa"],
                "agreement_rate": report["agreement_rate"],
                "disagreement_count": report["disagreement_count"],
                "smoke_copy": report["smoke_copy"],
                "note": report["note"],
                "output": str(args.output),
                "merged_sheet": str(args.merged_sheet),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
