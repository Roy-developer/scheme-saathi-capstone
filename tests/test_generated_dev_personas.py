"""Checks for the generated development persona set (not held-out)."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

from eval.harness.runner import load_persona_evaluation_set, typed_fact_store
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "generate_dev_personas.py"
PERSONA_FILE = REPO_ROOT / "eval" / "development" / "personas_generated_v2.json"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_dev_personas", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _file_document() -> dict:
    return json.loads(PERSONA_FILE.read_text(encoding="utf-8"))


def test_file_reproduces_from_generator():
    generated = _load_generator().build_document()
    assert generated == _file_document()


def test_no_duplicate_persona_ids():
    ids = [persona["persona_id"] for persona in _file_document()["personas"]]
    duplicates = [pid for pid, count in Counter(ids).items() if count > 1]
    assert not duplicates
    assert all(pid.startswith("GEN-") for pid in ids)


def test_all_cases_are_development_and_unprotected():
    document = _file_document()
    assert document["split"] == "development"
    assert document["protected"] is False
    assert "NOT HELD-OUT" in document["annotation_note"]
    for persona in document["personas"]:
        assert persona["split"] == "development", persona["persona_id"]
        assert persona["protected"] is False, persona["persona_id"]


def test_expected_results_match_current_rule_engine():
    registry_packages = RulePackageProvider()
    registry = registry_packages.registry
    packages = registry_packages.packages
    document = _file_document()
    for persona in document["personas"]:
        profile = typed_fact_store(persona["typed_facts"], registry)
        for scheme_id, expected in persona["expected_by_scheme"].items():
            actual = evaluate_mock_eligibility(
                profile, packages[scheme_id], registry=registry,
            )
            assert actual.result == expected["result"], persona["persona_id"]
            assert list(actual.missing_fields) == expected["missing_fields"], (
                persona["persona_id"]
            )
            assert list(actual.deciding_rule_ids) == expected["deciding_rule_ids"], (
                persona["persona_id"]
            )


def test_file_loads_as_unprotected_development_set():
    evaluation_set = load_persona_evaluation_set(PERSONA_FILE)
    assert evaluation_set.split == "development"
    assert evaluation_set.protected is False
    assert len(evaluation_set.personas) == len(_file_document()["personas"])
