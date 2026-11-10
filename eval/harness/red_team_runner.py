"""Offline execution of runnable red-team checks against current defences."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from eval.harness.runner import typed_fact_store
from eval.schema import RedTeamCase, RedTeamSuite, profile_from_mapping
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.workflow.agent_runtime import mask_sensitive_text
from src.workflow.injection_guard import screen_free_text
from src.workflow.scam_screen import screen_scam_text


def load_red_team_suite(path: Path) -> RedTeamSuite:
    """Load and validate a red-team suite JSON file."""

    try:
        return RedTeamSuite.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except ValidationError as error:
        raise ValueError(f"Invalid red-team suite: {error}") from error


def run_red_team_check(attack: RedTeamCase) -> dict[str, Any]:
    """Execute one runnable attack check; stubs return skipped."""

    if attack.status != "runnable" or attack.check is None:
        return {
            "attack_id": attack.attack_id,
            "category": attack.category,
            "status": "skipped_stub",
            "passed": None,
            "detail": "No offline check declared",
        }

    check = attack.check
    try:
        if check.kind == "injection_screen":
            screened = screen_free_text(attack.attack_input)
            passed = screened.flagged is bool(check.expect_flagged)
            detail = (
                f"flagged={screened.flagged} "
                f"patterns={list(screened.matched_patterns)}"
            )
        elif check.kind == "scam_screen":
            screened = screen_scam_text(attack.attack_input)
            passed = screened.flagged is bool(check.expect_flagged)
            detail = (
                f"flagged={screened.flagged} "
                f"patterns={list(screened.matched_patterns)}"
            )
        elif check.kind == "id_mask":
            masked = mask_sensitive_text(attack.attack_input)
            leaks = [token for token in check.must_not_contain if token in masked]
            passed = not leaks
            detail = f"leaks={leaks!r}" if leaks else "identifiers masked"
        elif check.kind == "eligibility_truthful":
            provider = RulePackageProvider()
            package = provider.packages[check.scheme_id]  # type: ignore[index]
            if check.typed_facts is not None:
                facts = typed_fact_store(check.typed_facts, provider.registry)
            else:
                facts = profile_from_mapping(check.profile or {})
            verdict = evaluate_mock_eligibility(
                facts, package, registry=provider.registry
            )
            passed = verdict.result == check.expect_result
            detail = f"result={verdict.result} expected={check.expect_result}"
        else:
            return {
                "attack_id": attack.attack_id,
                "category": attack.category,
                "status": "error",
                "passed": False,
                "detail": f"Unknown check kind {check.kind!r}",
            }
    except Exception as error:  # noqa: BLE001 — report per-attack failures
        return {
            "attack_id": attack.attack_id,
            "category": attack.category,
            "status": "error",
            "passed": False,
            "detail": f"{type(error).__name__}: {error}",
        }

    return {
        "attack_id": attack.attack_id,
        "category": attack.category,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "detail": detail,
        "check_kind": check.kind,
    }


def evaluate_red_team_suite(suite: RedTeamSuite) -> dict[str, Any]:
    """Run every attack; stubs are skipped, runnable checks are scored."""

    results = [run_red_team_check(attack) for attack in suite.attacks]
    runnable = [item for item in results if item["passed"] is not None]
    passed = sum(1 for item in runnable if item["passed"])
    failed = sum(1 for item in runnable if item["passed"] is False)
    skipped = sum(1 for item in results if item["passed"] is None)
    return {
        "suite_version": suite.suite_version,
        "attack_count": len(suite.attacks),
        "runnable_count": len(runnable),
        "stub_skipped": skipped,
        "passed": passed,
        "failed": failed,
        "pass_rate": (passed / len(runnable)) if runnable else None,
        "per_attack": results,
    }
