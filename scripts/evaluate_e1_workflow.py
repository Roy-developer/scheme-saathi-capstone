"""Run the offline full-workflow E1 comparison only with pinned development controls."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from uuid import uuid4

from eval.harness.e1_runner import (
    ARM_IDS,
    ArmControls,
    BudgetCeilings,
    CaseObservation,
    DevelopmentSetControls,
    DEVELOPMENT_CASE_IDS,
    DEVELOPMENT_SET_PATH,
    build_report,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "eval" / "experiments" / "e1_agent_cost.json"
COMPARISON_TEST = "tests/test_e1_workflow_comparison.py"
SCRIPTED_MODEL_ID = "e1-offline-script-v1"
LIVE_CREDENTIAL_NAMES = (
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_KEY_FREE",
    "OPEN_ROUTER_FREE",
    "OPENROUTER_EMBEDDING_API_KEY",
)
REQUIRED_BUDGET_KEYS = {
    "model_calls",
    "agent_tool_calls",
    "agent_steps",
    "domain_tool_calls",
    "total_token_reservation",
}


def _configuration_blockers(config: dict[str, object]) -> list[str]:
    """Reject the current stub, held-out data, and unpinned controls."""

    blockers: list[str] = []
    if config.get("status") == "config_stub_not_runnable":
        blockers.append("The E1 experiment configuration is still a non-runnable stub.")
    controls = config.get("controls")
    if not isinstance(controls, dict):
        return blockers + ["E1 controls must be an explicit object."]

    model_id = controls.get("model_id")
    if model_id != SCRIPTED_MODEL_ID:
        blockers.append(
            "This offline harness requires the same pinned scripted model "
            f"identifier ({SCRIPTED_MODEL_ID}) for C1 and C2."
        )
    if controls.get("model_mode") != "scripted":
        blockers.append("This offline harness accepts only scripted model mode.")

    tools = controls.get("tools")
    if isinstance(tools, dict):
        if set(tools) != set(ARM_IDS) or any(
            not isinstance(tools[arm], list)
            or not tools[arm]
            or any(not isinstance(tool, str) or not tool for tool in tools[arm])
            for arm in ARM_IDS
        ):
            blockers.append("Declare a nonempty capability list for every arm.")
        elif len({tuple(sorted(tools[arm])) for arm in ARM_IDS}) != 1:
            blockers.append("Configured domain-tool capabilities must match per arm.")
    elif (
        not isinstance(tools, (list, tuple))
        or not tools
        or any(not isinstance(tool, str) or not tool for tool in tools)
    ):
        blockers.append("Declare the comparable domain-tool capabilities explicitly.")

    budget = controls.get("budget")
    if not isinstance(budget, dict) or not budget:
        blockers.append("Pin every shared conversation-budget ceiling.")
    elif set(budget) != REQUIRED_BUDGET_KEYS:
        blockers.append(
            "Pin model-call, agent-tool, domain-tool, agent-step and token ceilings."
        )
    elif any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in budget.values()
    ):
        blockers.append("Budget ceilings must be positive integer values.")

    eval_set = controls.get("eval_set")
    if isinstance(eval_set, str):
        if eval_set.replace("\\", "/") != DEVELOPMENT_SET_PATH:
            blockers.append(
                "The offline E1 harness is pinned to the synthetic development set "
                f"{DEVELOPMENT_SET_PATH}."
            )
    elif isinstance(eval_set, dict):
        if (
            not isinstance(eval_set.get("path"), str)
            or eval_set["path"].replace("\\", "/") != DEVELOPMENT_SET_PATH
            or
            eval_set.get("split") != "development"
            or eval_set.get("protected") is not False
            or eval_set.get("synthetic_only") is not True
        ):
            blockers.append(
                "The evaluation set must be unprotected synthetic development data."
            )
    else:
        blockers.append("Pin an explicit synthetic development evaluation set.")
    return blockers


def _free_portal_url() -> str:
    """Select a currently free local portal port for the isolated test process."""

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def _clean_owned_path(path: Path) -> None:
    """Remove only files and directories created under this run's unique path."""

    if path.is_dir():
        for child in sorted(
            path.rglob("*"), key=lambda item: len(item.parts), reverse=True,
        ):
            if child.is_file():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                child.rmdir()
        path.rmdir()
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def _run_environment(run_id: str) -> tuple[dict[str, str], list[Path]]:
    """Build an offline environment with unique local databases and uploads."""

    environment = os.environ.copy()
    for name in LIVE_CREDENTIAL_NAMES:
        environment.pop(name, None)
    environment.update({
        "SCHEME_SAATHI_DISABLE_DOTENV": "1",
        "SCHEME_SAATHI_DISABLE_CROSS_ENCODER": "1",
        "SCHEME_SAATHI_PORTAL_URL": _free_portal_url(),
    })
    owned_paths = [
        ROOT / f".pytest-e1-{run_id}-journey.sqlite3",
        ROOT / f".pytest-e1-{run_id}-portal.sqlite3",
        ROOT / f".pytest-e1-{run_id}-uploads.sqlite3",
        ROOT / f".pytest-e1-{run_id}-uploads",
    ]
    environment.update({
        "SCHEME_SAATHI_CHECKPOINT_DB": str(owned_paths[0]),
        "SCHEME_SAATHI_APPLICATION_DB": str(owned_paths[1]),
        "SCHEME_SAATHI_UPLOAD_DB": str(owned_paths[2]),
        "SCHEME_SAATHI_UPLOAD_DIR": str(owned_paths[3]),
    })
    return environment, owned_paths


def _read_test_results(
    junit_path: Path,
) -> tuple[list[CaseObservation], dict[str, dict[str, object]], list[dict[str, str]]]:
    """Read observations and pinned runtime controls from focused pytest output."""

    observations: list[CaseObservation] = []
    metadata: dict[str, dict[str, object]] = {}
    failures: list[dict[str, str]] = []
    root = ET.parse(junit_path).getroot()
    for test_case in root.iter("testcase"):
        properties = {
            entry.attrib["name"]: entry.attrib["value"]
            for entry in test_case.findall("./properties/property")
        }
        for name, value in properties.items():
            if name == "e1_observation":
                observations.append(CaseObservation(**json.loads(value)))
            elif name in {
                "e1_capabilities", "e1_budget_ceilings", "e1_model_id",
                "e1_tool_calls", "e1_dataset_version",
            }:
                arm = test_case.attrib.get("name", "").split("[", 1)[-1]
                arm_id = next((candidate for candidate in ARM_IDS if candidate in arm), None)
                if arm_id is None:
                    failures.append({
                        "test": test_case.attrib.get("name", ""),
                        "detail": f"Could not identify E1 arm for property {name}.",
                    })
                else:
                    metadata.setdefault(arm_id, {})[name] = (
                        json.loads(value)
                        if name not in {"e1_model_id", "e1_dataset_version"}
                        else value
                    )
        for item in test_case:
            if item.tag in {"failure", "error", "skipped"}:
                failures.append({
                    "test": test_case.attrib.get("name", ""),
                    "detail": (item.text or item.attrib.get("message", ""))[-3000:],
                })
    return observations, metadata, failures


def _controls_from_metadata(
    metadata: dict[str, dict[str, object]],
) -> tuple[ArmControls, ...]:
    """Convert test-verified runtime controls into the comparison schema."""

    controls: list[ArmControls] = []
    for arm_id in ARM_IDS:
        arm_meta = metadata.get(arm_id, {})
        budget_data = arm_meta.get("e1_budget_ceilings")
        capabilities = arm_meta.get("e1_capabilities")
        model_id = arm_meta.get("e1_model_id")
        if (
            not isinstance(budget_data, dict)
            or not isinstance(capabilities, list)
            or not isinstance(model_id, str)
        ):
            continue
        controls.append(ArmControls(
            arm_id=arm_id,
            model_id=None if arm_id == "C0" else model_id,
            model_mode="none" if arm_id == "C0" else "scripted",
            capabilities=frozenset(str(item) for item in capabilities),
            budget=BudgetCeilings(
                model_calls=budget_data["model_calls"],
                agent_tool_calls=budget_data["agent_tool_calls"],
                domain_calls=budget_data["domain_tool_calls"],
                agent_steps=budget_data["agent_steps"],
                total_tokens=budget_data["total_token_reservation"],
            ),
            eligibility_decider="rule_engine",
            approval_policy="separate_exact_human_approval",
        ))
    return tuple(controls)


def main() -> int:
    """Run focused offline tests, then emit only observed and qualified metrics."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        sys.stdout.write(json.dumps({
            "experiment_id": "E1",
            "status": "blocked",
            "blockers": [f"Could not load E1 controls: {error}"],
        }, indent=2) + "\n")
        return 2

    blockers = _configuration_blockers(config)
    if blockers:
        sys.stdout.write(json.dumps({
            "experiment_id": "E1",
            "status": "blocked",
            "comparison_run_started": False,
            "blockers": blockers,
        }, indent=2) + "\n")
        return 2

    run_id = uuid4().hex
    environment, owned_paths = _run_environment(run_id)
    junit_path = ROOT / f".pytest-e1-{run_id}.xml"
    failures: list[dict[str, str]] = []
    try:
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                "--disable-warnings",
                "-o",
                "junit_family=legacy",
                f"--junitxml={junit_path}",
                COMPARISON_TEST,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            errors="replace",
        )
        if junit_path.exists():
            observations, metadata, failures = _read_test_results(junit_path)
        else:
            observations, metadata = [], {}
            failures.append({
                "test": "pytest",
                "detail": "The focused test run did not produce JUnit observations.",
            })
        arms = _controls_from_metadata(metadata)
        configured_budget = config["controls"]["budget"]
        for arm_id in ARM_IDS:
            runtime_budget = metadata.get(arm_id, {}).get("e1_budget_ceilings")
            if configured_budget != runtime_budget:
                report_blocker = (
                    "Configured budget ceilings do not match the runtime ceilings."
                )
                break
        else:
            report_blocker = None
        report = build_report(
            arms,
            DevelopmentSetControls(
                split="development",
                protected=False,
                synthetic_only=True,
                dataset_version=next(
                    (
                        str(values["e1_dataset_version"])
                        for values in metadata.values()
                        if isinstance(values.get("e1_dataset_version"), str)
                    ),
                    None,
                ),
                source=DEVELOPMENT_SET_PATH,
            ),
            tuple(observations),
            expected_case_ids=DEVELOPMENT_CASE_IDS,
        )
        if report_blocker is not None:
            report["status"] = "blocked"
            report["complete"] = False
            report["comparable"] = False
            report["blockers"] = list(report["blockers"]) + [report_blocker]
        if failures or run.returncode:
            report["status"] = "blocked"
            report["complete"] = False
            report["comparable"] = False
            report["blockers"] = list(report["blockers"]) + [
                "The focused integrated workflow tests did not all pass."
            ]
        report["pytest_exit_code"] = run.returncode
        report["test_failures"] = failures
        report["tool_inventory_by_arm"] = {
            arm_id: metadata.get(arm_id, {}).get("e1_tool_calls")
            for arm_id in ARM_IDS
        }
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return int(
            run.returncode != 0
            or not report["complete"]
            or not report["comparable"]
        )
    finally:
        junit_path.unlink(missing_ok=True)
        for path in owned_paths:
            _clean_owned_path(path)


if __name__ == "__main__":
    raise SystemExit(main())
