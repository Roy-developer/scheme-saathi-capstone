"""Tests for the Role 5 development eligibility evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.harness.runner import (
    evaluate_persona_set,
    load_persona_evaluation_set,
)
from eval.schema import PersonaEvaluationSet


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEV_SET = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"


def test_development_set_loads_and_is_unprotected() -> None:
    evaluation_set = load_persona_evaluation_set(DEV_SET)

    assert evaluation_set.split == "development"
    assert evaluation_set.protected is False
    assert len(evaluation_set.personas) >= 30
    scheme_ids = {
        scheme_id
        for persona in evaluation_set.personas
        for scheme_id in persona.expected_by_scheme
    }
    assert scheme_ids == {"APY-IN", "IGNOAPS-MH", "IGNWPS-MH", "PM-KISAN-IN"}


def test_cant_tell_alias_normalizes_to_need_more_information() -> None:
    evaluation_set = load_persona_evaluation_set(DEV_SET)
    persona = next(
        item for item in evaluation_set.personas if item.persona_id == "IGNWPS-DEV-007"
    )
    assert persona.expected_by_scheme["IGNWPS-MH"].result == "need_more_information"


def test_harness_scores_development_set_perfectly() -> None:
    evaluation_set = load_persona_evaluation_set(DEV_SET)
    report = evaluate_persona_set(evaluation_set)

    assert report["case_count"] == len(evaluation_set.personas)
    assert report["incorrect"] == 0
    assert report["accuracy"] == 1.0
    assert report["missing_field_mismatches"] == 0


def test_harness_rejects_protected_sets(tmp_path: Path) -> None:
    payload = {
        "dataset_version": "test",
        "split": "held_out",
        "protected": True,
        "annotation_note": "must be rejected by in-repo harness",
        "personas": [
            {
                "persona_id": "HOLD-1",
                "boundary_family": "test",
                "split": "held_out",
                "protected": True,
                "description": "protected fixture",
                "profile": {"is_widow": True},
                "expected_by_scheme": {
                    "IGNWPS-MH": {"result": "eligible", "missing_fields": []}
                },
            }
        ],
    }
    path = tmp_path / "held.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unprotected development"):
        load_persona_evaluation_set(path)


def test_schema_rejects_development_protected_flag() -> None:
    with pytest.raises(ValueError, match="cannot be protected"):
        PersonaEvaluationSet.model_validate(
            {
                "dataset_version": "x",
                "split": "development",
                "protected": True,
                "annotation_note": "invalid",
                "personas": [
                    {
                        "persona_id": "X",
                        "boundary_family": "x",
                        "split": "development",
                        "protected": True,
                        "description": "x",
                        "profile": {},
                        "expected_by_scheme": {
                            "IGNWPS-MH": {"result": "eligible"}
                        },
                    }
                ],
            }
        )
