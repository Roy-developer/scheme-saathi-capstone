"""E4 team-override dual-label attach + κ (no smoke copy)."""

from __future__ import annotations

from pathlib import Path

from eval.harness.agreement import (
    agreement_report,
    attach_external_labels,
    normalize_sheet_result,
)
from eval.harness.runner import load_persona_evaluation_set
from scripts.evaluate_e4_label_agreement import attach_e4_dual_labels


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEV_SET = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"


def test_normalize_sheet_result_accepts_legacy_field() -> None:
    assert normalize_sheet_result({"model_assisted_label": "eligible"}) == "eligible"
    assert normalize_sheet_result({"result": "cant_tell"}) == "need_more_information"


def test_attach_external_labels_skips_unknown_schemes() -> None:
    evaluation_set = load_persona_evaluation_set(DEV_SET)
    persona_id = evaluation_set.personas[0].persona_id
    scheme_id = next(iter(evaluation_set.personas[0].expected_by_scheme))
    updated = attach_external_labels(
        evaluation_set,
        [
            {
                "persona_id": persona_id,
                "scheme_id": scheme_id,
                "result": "eligible",
            },
            {
                "persona_id": persona_id,
                "scheme_id": "NOT-A-SCHEME",
                "result": "eligible",
            },
        ],
        labeller_id="unit-test-labeller",
        note="unit test",
    )
    labels = [
        label
        for persona in updated.personas
        if persona.persona_id == persona_id
        for label in persona.labels
        if label.labeller_id == "unit-test-labeller"
    ]
    assert len(labels) == 1
    assert labels[0].scheme_id == scheme_id


def test_e4_dual_label_kappa_is_not_smoke_copy() -> None:
    evaluation_set = attach_e4_dual_labels(load_persona_evaluation_set(DEV_SET))
    report = agreement_report(
        evaluation_set,
        labeller_a="model-assisted-check",
        labeller_b="model-assisted-check-2",
    )
    assert report["smoke_copy"] is False
    assert report["paired_label_count"] == 46
    assert report["cohens_kappa"] == 1.0
    assert report["disagreement_count"] == 0
    assert "20+" in str(report["note"])
