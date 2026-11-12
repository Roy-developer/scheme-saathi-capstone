"""Label synthetic development cases with a same-family, non-independent model panel."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.label_dev_personas_llm import (  # noqa: E402
    CHAT_URL, KEY_NAME, LABELS, PERSONA_FILES, build_prompt, load_cases,
    load_passages, parse_structured,
)

MODELS = (
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
)
DISCLAIMER = "model-panel substitute, not independent, not human-validated, single model family"
OUTPUT = ROOT / "eval" / "reports" / "llm_panel_dev.json"
MAX_CALLS = 320
RESUME_MAX_CALLS = 240
FINISH_MAX_CALLS = 64
MAX_CONSECUTIVE_FAILURES = 5
MAX_REPORTED_COST = 0.50
MAX_TOKENS = 1024
BOUNDARY_TERMS = ("age", "boundary", "lower", "upper", "exact", "below", "above")
EXCLUSION_TERMS = (
    "exclusion", "tax", "pension", "institutional", "professional", "government",
    "nri", "office", "widow", "bpl", "citizen", "disability", "gov-employee",
)


class PanelFailure(Exception):
    """A failed request, with any cost supplied by the provider."""

    def __init__(self, reason: str, cost: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.cost = cost


class PanelStop(Exception):
    """A response that prevents any further request in the panel."""

    def __init__(self, reason: str, cost: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.cost = cost


def call_model(model: str, api_key: str, prompt: str) -> tuple[str, float | None]:
    """Send one request and preserve reported cost even for a malformed answer."""

    request = urllib.request.Request(
        CHAT_URL,
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": MAX_TOKENS,
            "reasoning": {"effort": "none"},
        }).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "scheme-saathi-dev-panel",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise PanelFailure(f"http_{error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PanelFailure("transport_error") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise PanelFailure("response_json") from None
    if not isinstance(payload, dict):
        raise PanelFailure("response_schema")
    usage = payload.get("usage")
    cost = usage.get("cost") if isinstance(usage, dict) else None
    if cost is not None:
        try:
            cost = float(cost)
        except (ValueError, TypeError, OverflowError):
            raise PanelStop("invalid_reported_cost") from None
        if not math.isfinite(cost) or cost < 0:
            raise PanelStop("invalid_reported_cost")
        if cost > MAX_REPORTED_COST:
            raise PanelStop("cost_above_limit", cost)
    try:
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("missing content")
        return parse_structured(content)["label"], cost
    except (KeyError, IndexError, TypeError, ValueError):
        raise PanelFailure("invalid_model_response", cost) from None


def summarize(rows: list[dict]) -> dict:
    """Count complete-panel agreement and strict majorities of successful answers."""

    full = unanimous = compared = matching = 0
    disagreements = []
    for row in rows:
        if row["rule_expected"] == "cant_tell":
            row["rule_expected"] = "need_more_information"
        labels = [label for label in row["labels"].values() if label in LABELS]
        counts = Counter(labels)
        top, count = counts.most_common(1)[0] if counts else (None, 0)
        row["successful_models"] = len(labels)
        row["majority"] = top if count > len(labels) / 2 else "no_majority"
        row["unanimous_all_four"] = len(labels) == len(MODELS) and len(counts) == 1
        full += len(labels) == len(MODELS)
        unanimous += row["unanimous_all_four"]
        if row["majority"] != "no_majority":
            compared += 1
            matching += row["majority"] == row["rule_expected"]
        family = (row["boundary_family"] or "").lower()
        groups = []
        if any(term in family for term in BOUNDARY_TERMS):
            groups.append("boundary")
        if any(term in family for term in EXCLUSION_TERMS):
            groups.append("exclusion")
        if groups and (
            len(counts) > 1
            or (row["majority"] != "no_majority" and row["majority"] != row["rule_expected"])
        ):
            disagreements.append({
                "source_file": row["source_file"], "persona_id": row["persona_id"],
                "scheme_id": row["scheme_id"], "boundary_family": row["boundary_family"],
                "groups": groups, "labels": row["labels"], "majority": row["majority"],
                "rule_expected": row["rule_expected"],
            })
    return {
        "complete_four_model_cases": full,
        "unanimous_four_model_cases": unanimous,
        "non_unanimous_four_model_cases": full - unanimous,
        "majority_vs_rule": {
            "compared": compared, "agree": matching, "disagree": compared - matching,
            "no_majority": len(rows) - compared,
        },
        "boundary_exclusion_disagreements": disagreements,
        "note": (
            "Strict majority among successful answers; even one successful model can yield "
            "a majority. Unanimity requires all four answers. Same-family agreement is not "
            "independent validation or a measure of correctness."
        ),
    }


def save_report(report: dict, rows: list[dict]) -> None:
    """Persist only synthetic case identifiers, labels, and non-secret metrics."""

    report["agreement"] = summarize(rows)
    report["cases"] = rows
    target = Path(report.get("output_path", str(OUTPUT)))
    target.parent.mkdir(parents=True, exist_ok=True)
    for fallback in (False, True):
        if fallback:
            target = OUTPUT.with_name("llm_panel_dev_retry.json")
            for index in range(1, 1000):
                if not target.exists():
                    break
                target = OUTPUT.with_name(f"llm_panel_dev_retry_{index}.json")
            else:
                raise OSError("No available fallback report filename")
            report["output_path"] = str(target)
        temporary = target.with_suffix(".json.tmp")
        try:
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for attempt in range(5):
                try:
                    temporary.replace(target)
                    return
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.25)
        except OSError:
            if fallback:
                raise
    raise OSError("Could not save report")


def load_resume(cases: list[dict], *, finish_lightning: bool = False) -> dict:
    """Validate the prior development checkpoint before retaining its answers."""

    report = json.loads(OUTPUT.read_text(encoding="utf-8"))
    rows = report["cases"]
    if report.get("disclaimer") != DISCLAIMER or report.get("model_ids") != list(MODELS):
        raise ValueError("The previous report is not this development panel")
    if len(rows) != len(cases):
        raise ValueError("The prior case count differs from the development inputs")
    for case, row in zip(cases, rows):
        if any(case[key] != row[key] for key in ("source_file", "persona_id", "scheme_id", "boundary_family")):
            raise ValueError("Prior case ordering or identity differs from development inputs")
        if row["rule_expected"] != ("need_more_information" if case["rule_expected"] == "cant_tell" else case["rule_expected"]):
            raise ValueError("Prior rule expectation differs from development inputs")
        if set(row["labels"]) != set(MODELS) or any(
            label is not None and label not in LABELS for label in row["labels"].values()
        ):
            raise ValueError("Prior model labels are invalid")
    if finish_lightning:
        if any(row["labels"][model] is None for row in rows for model in MODELS[1:]):
            raise ValueError("Other panel models must already have answered all cases")
        if report["calls"] != sum(report["models"][model]["calls"] for model in MODELS):
            raise ValueError("Previous panel call counters are inconsistent")
    else:
        if report["calls"] != 10 or any(report["models"][model]["calls"] != 0 for model in MODELS[1:]):
            raise ValueError("Previous call history does not match the authorized resume")
        if sum(row["labels"][MODELS[0]] is not None for row in rows) != 10:
            raise ValueError("Previous Lightning answers do not match the authorized resume")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    continuation = parser.add_mutually_exclusive_group()
    continuation.add_argument("--resume", action="store_true")
    continuation.add_argument("--finish-lightning", action="store_true")
    args = parser.parse_args()
    cases = load_cases()
    passages = load_passages()
    missing = sorted({case["scheme_id"] for case in cases} - passages.keys())
    if missing:
        print(f"Missing passages for: {', '.join(missing)}")
        return 2
    prior = load_resume(cases, finish_lightning=args.finish_lightning) if (
        args.resume or args.finish_lightning
    ) else None
    if args.finish_lightning:
        remaining = sum(row["labels"][MODELS[0]] is None for row in prior["cases"])
        print(f"cases={len(cases)} lightning_missing={remaining} "
              f"planned_calls={min(remaining, FINISH_MAX_CALLS)} new_call_cap={FINISH_MAX_CALLS}")
    elif prior:
        print(f"cases={len(cases)} three_models_planned_calls={len(cases) * 3} "
              f"lightning_missing=66 new_call_cap={RESUME_MAX_CALLS}")
    else:
        print(f"cases={len(cases)} models={len(MODELS)} planned_calls={len(cases) * len(MODELS)} cap={MAX_CALLS}")
    if args.dry_run:
        print("dry run: no network requests")
        return 0
    api_key = os.getenv(KEY_NAME)
    if not api_key or api_key.lower().startswith(("your_", "placeholder", "changeme", "<")):
        print(f"Repository .env key {KEY_NAME} missing or placeholder; no requests made.")
        return 2

    rows = prior["cases"] if prior else [{
        "source_file": case["source_file"], "persona_id": case["persona_id"],
        "scheme_id": case["scheme_id"], "boundary_family": case["boundary_family"],
        "rule_expected": case["rule_expected"], "labels": {model: None for model in MODELS},
    } for case in cases]
    metrics = prior["models"] if prior else {model: {
        "calls": 0, "successes": 0, "failures": 0, "stop_reason": "not_started",
        "reported_cost_usd": None, "cost_unreported_calls": 0,
        "failure_reasons": {},
    } for model in MODELS}
    report = prior if prior else {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "running", "model_ids": list(MODELS), "key_name": KEY_NAME,
        "inputs": [path.name for path in PERSONA_FILES], "cases_total": len(cases),
        "calls": 0, "models": metrics, "stop_reason": None,
        "reported_cost_usd": None, "cost_unreported_calls": 0,
        "cost_note": "Sum of provider-reported costs only; missing amounts are unknown.",
    }
    report["status"] = "running"
    report["stop_reason"] = None
    report["output_path"] = str(OUTPUT)
    if args.finish_lightning:
        report["finish_previous_calls"] = report["calls"]
        report["finish_new_calls"] = 0
        report["finish_new_failures"] = 0
        report["finish_call_cap"] = FINISH_MAX_CALLS
        report["finish_disclaimer"] = DISCLAIMER
    elif prior:
        report["previous_calls"] = report["calls"]
        report["new_calls"] = 0
        report["new_call_cap"] = RESUME_MAX_CALLS
        report["resume_disclaimer"] = DISCLAIMER
        report["previous_stop_reason"] = "report_write_error"
        for arm in metrics.values():
            arm["new_calls"] = 0
            arm["new_failures"] = 0
    save_report(report, rows)

    def account(cost: float | None, arm: dict) -> None:
        if cost is None:
            arm["cost_unreported_calls"] += 1
            report["cost_unreported_calls"] += 1
        else:
            arm["reported_cost_usd"] = (arm["reported_cost_usd"] or 0) + cost
            report["reported_cost_usd"] = (report["reported_cost_usd"] or 0) + cost

    global_stop = None
    execution_order = (MODELS[0],) if args.finish_lightning else (
        (*MODELS[1:], MODELS[0]) if prior else MODELS
    )
    for model in execution_order:
        arm = metrics[model]
        arm["stop_reason"] = "completed"
        print(f"Starting model: {model}", flush=True)
        consecutive = 0
        for index, case in enumerate(cases):
            if rows[index]["labels"][model] is not None:
                continue
            for attempt in range(2):
                limit_reached = (
                    report["finish_new_calls"] >= FINISH_MAX_CALLS if args.finish_lightning
                    else report["new_calls"] >= RESUME_MAX_CALLS if prior
                    else report["calls"] >= MAX_CALLS
                )
                if limit_reached:
                    global_stop = "max_calls_reached"
                    break
                report["calls"] += 1
                if args.finish_lightning:
                    report["finish_new_calls"] += 1
                elif prior:
                    report["new_calls"] += 1
                    arm["new_calls"] += 1
                arm["calls"] += 1
                try:
                    label, cost = call_model(model, api_key, build_prompt(case, passages[case["scheme_id"]]))
                except PanelStop as error:
                    account(error.cost, arm)
                    arm["failures"] += 1
                    if args.finish_lightning:
                        report["finish_new_failures"] += 1
                    elif prior:
                        arm["new_failures"] += 1
                    global_stop = error.reason
                    break
                except PanelFailure as error:
                    account(error.cost, arm)
                    arm["failures"] += 1
                    if args.finish_lightning:
                        report["finish_new_failures"] += 1
                    elif prior:
                        arm["new_failures"] += 1
                    arm["failure_reasons"][error.reason] = arm["failure_reasons"].get(error.reason, 0) + 1
                    consecutive += 1
                    if report["reported_cost_usd"] is not None and report["reported_cost_usd"] > MAX_REPORTED_COST:
                        global_stop = "cost_above_limit"
                        break
                    if consecutive >= MAX_CONSECUTIVE_FAILURES:
                        arm["stop_reason"] = "five_consecutive_failures"
                        break
                    save_report(report, rows)
                    if attempt == 0:
                        time.sleep(1)
                    continue
                account(cost, arm)
                arm["successes"] += 1
                rows[index]["labels"][model] = label
                consecutive = 0
                if report["reported_cost_usd"] is not None and report["reported_cost_usd"] > MAX_REPORTED_COST:
                    global_stop = "cost_above_limit"
                break
            save_report(report, rows)
            if global_stop or arm["stop_reason"] != "completed":
                break
        if arm["stop_reason"] == "completed" and any(row["labels"][model] is None for row in rows):
            arm["stop_reason"] = "completed_with_unlabeled_cases"
        if global_stop:
            arm["stop_reason"] = global_stop
        print(f"Finished model: {model} calls={arm['calls']} failures={arm['failures']} "
              f"stop={arm['stop_reason']}", flush=True)
        if global_stop:
            break
    report["status"] = "stopped" if global_stop else "completed"
    report["stop_reason"] = global_stop or "all_models_processed"
    if prior:
        report["lightning_missing"] = sum(row["labels"][MODELS[0]] is None for row in rows)
    save_report(report, rows)
    print(json.dumps({
        "disclaimer": DISCLAIMER, "calls": report["calls"], "stop_reason": report["stop_reason"],
        "reported_cost_usd": report["reported_cost_usd"],
        "cost_unreported_calls": report["cost_unreported_calls"],
        "models": metrics, "agreement": {key: value for key, value in report["agreement"].items()
                                         if key != "boundary_exclusion_disagreements"},
        "output": report["output_path"],
    }, ensure_ascii=False))
    return 0 if global_stop is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
