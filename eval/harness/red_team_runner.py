"""Offline execution of runnable red-team checks against current defences."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
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


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVIEWED_TESTS = {
    "RT-INFLATE-001": (
        "tests/test_apy_eligibility.py::"
        "test_rt_inflate_001_age_claim_does_not_replace_date_of_birth"
    ),
    "RT-MEMORY-001": (
        "tests/test_household_memory.py::"
        "test_rt_memory_001_cross_household_profile_is_not_loaded"
    ),
    "RT-MEMORY-002": (
        "tests/test_cross_journey_isolation.py::"
        "test_one_conversation_cannot_access_another_conversations_draft"
    ),
    "RT-MEMORY-003": (
        "tests/test_application_tools.py::"
        "test_rt_memory_003_approval_token_cannot_be_replayed"
    ),
    "RT-OTHER-001": (
        "tests/test_application_tools.py::"
        "test_submit_requires_approval_and_is_idempotent"
    ),
    "RT-OTHER-002": (
        "tests/test_cascading_failure_isolation.py::"
        "test_model_claiming_eligible_cannot_override_the_rule_engine"
    ),
    "RT-OTHER-005": (
        "tests/test_household_memory.py::"
        "test_rt_other_005_household_alias_cannot_load_memory"
    ),
}


def load_red_team_suite(path: Path) -> RedTeamSuite:
    """Load and validate a red-team suite JSON file."""

    try:
        return RedTeamSuite.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except ValidationError as error:
        raise ValueError(f"Invalid red-team suite: {error}") from error


def run_red_team_check(
    attack: RedTeamCase,
    live_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one offline check or return its suite-level test result."""

    if attack.status != "runnable" or attack.check is None:
        return {
            "attack_id": attack.attack_id,
            "category": attack.category,
            "status": "skipped_stub",
            "passed": None,
            "detail": "No offline check declared",
        }

    check = attack.check
    if check.kind == "pytest_case":
        if live_result is not None:
            return live_result
        return {
            "attack_id": attack.attack_id,
            "category": attack.category,
            "status": "not_run",
            "passed": None,
            "detail": "Reviewed local test not requested",
            "check_kind": check.kind,
        }

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
                facts = profile_from_mapping(check.profile or {}, provider.registry)
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


def _run_reviewed_tests(suite: RedTeamSuite) -> dict[str, dict[str, Any]]:
    """Run the allowlisted reviewed scenarios together and map JUnit results."""

    selected = [
        attack for attack in suite.attacks
        if attack.status == "runnable"
        and attack.check is not None
        and attack.check.kind == "pytest_case"
    ]
    if not selected:
        return {}

    references = {
        attack.attack_id: REVIEWED_TESTS.get(attack.attack_id)
        for attack in selected
    }
    unknown = [attack_id for attack_id, ref in references.items() if ref is None]
    if unknown:
        return {
            attack_id: {
                "attack_id": attack_id,
                "category": next(
                    attack.category for attack in selected
                    if attack.attack_id == attack_id
                ),
                "status": "error",
                "passed": False,
                "detail": "No allowlisted local integration test",
                "check_kind": "pytest_case",
            }
            for attack_id in unknown
        }

    with tempfile.TemporaryDirectory(prefix="saathi-red-team-") as temp_dir:
        junit_path = Path(temp_dir) / "results.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"--junitxml={junit_path}",
            *[ref for ref in references.values() if ref is not None],
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )
        except OSError as error:
            return {
                attack.attack_id: {
                    "attack_id": attack.attack_id,
                    "category": attack.category,
                    "status": "error",
                    "passed": False,
                    "detail": f"Could not run local tests: {error}",
                    "check_kind": "pytest_case",
                    "test_reference": references[attack.attack_id],
                }
                for attack in selected
            }
        test_results: dict[str, dict[str, Any]] = {}
        if junit_path.exists():
            root = ET.parse(junit_path).getroot()
            for testcase in root.iter("testcase"):
                name = testcase.attrib.get("name", "")
                for attack_id, reference in references.items():
                    if reference is None or not reference.endswith(f"::{name}"):
                        continue
                    failures = [
                        node for node in testcase
                        if node.tag in {"failure", "error", "skipped"}
                    ]
                    passed = not failures
                    detail = (
                        f"pytest {reference}"
                        if passed
                        else (failures[0].attrib.get("message") or
                              (failures[0].text or "").strip() or
                              f"pytest {reference} failed")
                    )
                    test_results[attack_id] = {
                        "attack_id": attack_id,
                        "category": next(
                            attack.category for attack in selected
                            if attack.attack_id == attack_id
                        ),
                        "status": "passed" if passed else "failed",
                        "passed": passed,
                        "detail": detail,
                        "check_kind": "pytest_case",
                        "test_reference": reference,
                    }

        for attack in selected:
            if attack.attack_id in test_results:
                continue
            reference = references[attack.attack_id]
            output = (completed.stdout + "\n" + completed.stderr).strip()
            test_results[attack.attack_id] = {
                "attack_id": attack.attack_id,
                "category": attack.category,
                "status": "error",
                "passed": False,
                "detail": (
                    f"pytest did not report {reference}; "
                    f"exit_code={completed.returncode}; output={output[-4000:]}"
                ),
                "check_kind": "pytest_case",
                "test_reference": reference,
            }
        return test_results


def evaluate_red_team_suite(
    suite: RedTeamSuite,
    *,
    run_reviewed_tests: bool = False,
) -> dict[str, Any]:
    """Run offline attacks and, optionally, all reviewed local pytest cases."""

    reviewed_results = _run_reviewed_tests(suite) if run_reviewed_tests else {}
    results = []
    for attack in suite.attacks:
        result = run_red_team_check(
            attack, reviewed_results.get(attack.attack_id)
        )
        if suite.ai_review is not None:
            ai_decision = suite.ai_review.decisions.get(attack.attack_id)
            if ai_decision is not None:
                result["ai_review"] = {
                    "reviewer": suite.ai_review.reviewer,
                    "review_date": suite.ai_review.review_date,
                    "decision": ai_decision.decision,
                    "note": ai_decision.note,
                    "scope_note": suite.ai_review.scope_note,
                }
        if attack.author is not None:
            result.update({
                "author": attack.author,
                "reviewed_by": attack.reviewed_by,
                "review_status": attack.review_status,
            })
        results.append(result)
    runnable = [item for item in results if item["passed"] is not None]
    passed = sum(1 for item in runnable if item["passed"])
    failed = sum(1 for item in runnable if item["passed"] is False)
    skipped = sum(1 for item in results if item["passed"] is None)
    return {
        "suite_version": suite.suite_version,
        "attack_count": len(suite.attacks),
        "runnable_count": len(runnable),
        "ai_reviewed_count": len(suite.ai_review.decisions) if suite.ai_review else 0,
        "reviewed_test_count": len(reviewed_results),
        "reviewed_test_passed": sum(
            1 for item in reviewed_results.values() if item["passed"]
        ),
        "reviewed_test_failed": sum(
            1 for item in reviewed_results.values() if item["passed"] is False
        ),
        "stub_skipped": skipped,
        "passed": passed,
        "failed": failed,
        "pass_rate": (passed / len(runnable)) if runnable else None,
        "per_attack": results,
    }
