"""Model-assisted labelling of DEVELOPMENT personas (not independent, not human-validated).

For each development persona and each scheme it covers, ask one OpenRouter model
to judge eligibility from the public passage text and the persona's synthetic
facts. Rule-engine expected results are used only for the agreement report.

Usage:
  .venv/Scripts/python.exe scripts/label_dev_personas_llm.py --dry-run
  .venv/Scripts/python.exe scripts/label_dev_personas_llm.py --live
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Do not allow an inherited standard or free key to be used by this script.
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY_FREE", None)

from src.config import load_project_dotenv  # noqa: E402

load_project_dotenv()

MODEL_ID = "nvidia/nemotron-3.5-lightning:free"
KEY_NAME = "OPENROUTER_API_KEY_FREE"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
PERSONA_FILES = [
    PROJECT_ROOT / "eval" / "development" / "personas_v1.json",
    PROJECT_ROOT / "eval" / "development" / "personas_generated_v2.json",
]
PASSAGE_DIR = PROJECT_ROOT / "data" / "schemes" / "passages"
OUTPUT = PROJECT_ROOT / "eval" / "reports" / "llm_labels_dev.json"
LABELS = ("eligible", "not_eligible", "need_more_information")
MAX_CALLS = 107
STOP_COST_USD = 0.50
CONSECUTIVE_FAILURE_LIMIT = 5
PASSAGE_CHAR_LIMIT = 2000
DISCLAIMER = "model-assisted, not independent, not human-validated"


class StopRun(Exception):
    def __init__(self, reason: str, cost: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.cost = cost


class ModelResponseError(ValueError):
    """Keep the reported cost even when a model response cannot be labeled."""

    def __init__(self, reason: str, cost: float | None = None) -> None:
        super().__init__(reason)
        self.cost = cost


def load_passages() -> dict[str, str]:
    """Concatenate public passage text per scheme_id (no rule-engine content)."""

    texts: dict[str, list[str]] = {}
    for path in sorted(PASSAGE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for passage in data.get("passages", []):
            texts.setdefault(passage["scheme_id"], []).append(passage["text"])
    return {scheme: " ".join(parts)[:PASSAGE_CHAR_LIMIT] for scheme, parts in texts.items()}


def load_cases() -> list[dict]:
    cases = []
    for path in PERSONA_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("split") != "development" or data.get("protected") is not False:
            raise ValueError(f"{path.name} is not an unprotected development set")
        for persona in data["personas"]:
            if persona.get("split") != "development" or persona.get("protected") is not False:
                raise ValueError(f"{path.name} contains a non-development persona")
            facts = persona.get("typed_facts") or persona.get("profile") or {}
            for scheme_id, expected in persona["expected_by_scheme"].items():
                cases.append(
                    {
                        "source_file": path.name,
                        "persona_id": persona["persona_id"],
                        "boundary_family": persona.get("boundary_family"),
                        "scheme_id": scheme_id,
                        "facts": facts,
                        "rule_expected": expected["result"],
                    }
                )
    return cases


def build_prompt(case: dict, passage: str) -> str:
    facts = json.dumps(case["facts"], ensure_ascii=False, sort_keys=True)
    return (
        "You judge a synthetic test person against a public scheme criteria text.\n"
        f"Scheme: {case['scheme_id']}\n"
        f"Criteria text: {passage}\n"
        f"Synthetic person facts (JSON): {facts}\n\n"
        "Answer with ONLY a JSON object, no other text, in this form:\n"
        '{"label": "eligible" | "not_eligible" | "need_more_information", '
        '"reason": "<one sentence>"}\n'
        "Use need_more_information when a needed fact is absent."
    )


def _request(
    api_key: str, prompt: str, *, max_tokens: int = 200, disable_reasoning: bool = False,
) -> urllib.request.Request:
    payload: dict = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if disable_reasoning:
        payload["reasoning"] = {"effort": "none"}
    body = json.dumps(payload).encode("utf-8")
    return urllib.request.Request(
        CHAT_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "scheme-saathi-dev-labelling",
        },
    )
def call_model(api_key: str, prompt: str) -> tuple[dict, float | None]:
    """Return (parsed_json_message, reported_cost_or_None). Raises on HTTP/transport error."""

    with urllib.request.urlopen(
        _request(api_key, prompt, max_tokens=1024, disable_reasoning=True), timeout=90,
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    cost = None
    usage = payload.get("usage") or {}
    if isinstance(usage, dict) and usage.get("cost") is not None:
        try:
            cost = float(usage["cost"])
        except (ValueError, TypeError, OverflowError) as error:
            raise StopRun("invalid_reported_cost") from error
        if not math.isfinite(cost) or cost < 0:
            raise StopRun("invalid_reported_cost")
        if cost > STOP_COST_USD:
            raise StopRun("cost_above_limit", cost)
    try:
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("missing content")
        return parse_structured(content), cost
    except (ValueError, IndexError, KeyError, TypeError) as error:
        raise ModelResponseError("invalid_model_response", cost) from error


def probe_response(raw: bytes) -> dict:
    """Classify a response without exposing prompts, output, or credentials."""

    result: dict = {"stage": "response_json", "cost_usd_reported": None}
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return result
    if not isinstance(payload, dict):
        result["stage"] = "response_schema"
        return result
    usage = payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    cost = usage.get("cost")
    if cost is not None:
        try:
            cost = float(cost)
        except (ValueError, TypeError, OverflowError):
            result["stage"] = "cost_parse"
            return result
        if not math.isfinite(cost) or cost < 0:
            result["stage"] = "cost_parse"
            return result
        result["cost_usd_reported"] = cost
        if cost > STOP_COST_USD:
            result["stage"] = "cost_above_limit"
            return result
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        result["stage"] = "response_schema"
        return result
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        result["stage"] = "response_schema"
        return result
    content = message.get("content")
    finish = choice.get("finish_reason")
    result.update({
        "finish_reason": finish if finish in ("stop", "length", "content_filter", "tool_calls") else "other_or_missing",
        "content_type": type(content).__name__,
        "content_length": len(content) if isinstance(content, str) else None,
        "reasoning_present": bool(message.get("reasoning") or message.get("reasoning_details")),
        "completion_tokens": usage.get("completion_tokens") if type(usage.get("completion_tokens")) is int else None,
    })
    if not isinstance(content, str):
        result["stage"] = "structured_output"
        return result
    try:
        parse_structured(content)
    except ValueError:
        result["stage"] = "structured_output"
        return result
    result["stage"] = "success"
    return result


def run_probe() -> int:
    """Make one development-only request and print safe response metadata."""

    api_key = os.getenv(KEY_NAME)
    if not api_key or api_key.lower().startswith(("your_", "placeholder", "changeme", "<")):
        print("probe blocked: repository free key missing or placeholder")
        return 2
    cases = load_cases()
    passages = load_passages()
    if not cases or cases[0]["scheme_id"] not in passages:
        print("probe blocked: development case or passage missing")
        return 2
    prompt = build_prompt(cases[0], passages[cases[0]["scheme_id"]])
    try:
        with urllib.request.urlopen(
            _request(api_key, prompt, max_tokens=1024, disable_reasoning=True), timeout=90,
        ) as response:
            result = probe_response(response.read())
    except urllib.error.HTTPError as error:
        result = {"stage": "http_error", "http_status": error.code, "cost_usd_reported": None}
    except (urllib.error.URLError, TimeoutError, OSError):
        result = {"stage": "transport_error", "cost_usd_reported": None}
    print(json.dumps({"calls": 1, "model_id": MODEL_ID, "key_name": KEY_NAME, **result}))
    return 0 if result["stage"] == "success" else 1


def parse_structured(content: str) -> dict:
    """Extract a strict label object from plain, fenced, or prefaced JSON."""

    text = (content or "").strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("label") not in LABELS:
            continue
        reason = obj.get("reason")
        if isinstance(reason, str) and reason.strip():
            return {"label": obj["label"], "reason": reason.strip()[:300]}
    raise ValueError("structured_output_error: no valid label JSON object")


def run(live: bool) -> int:
    passages = load_passages()
    cases = load_cases()
    missing = sorted({c["scheme_id"] for c in cases} - set(passages))
    if missing:
        print(f"ERROR: no passage text for schemes {missing}")
        return 2

    print(f"cases={len(cases)} max_calls={MAX_CALLS} model={MODEL_ID}")
    if not live:
        print("dry run: no network calls made")
        print(f"planned calls={min(len(cases), MAX_CALLS)} (one per case; retries may use remaining cap)")
        return 0
    api_key = os.getenv(KEY_NAME)
    if not api_key or api_key.lower().startswith(("your_", "placeholder", "changeme", "<")):
        print(f"ERROR: {KEY_NAME} is not configured in the repository .env")
        report = {
            "disclaimer": DISCLAIMER,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "blocked",
            "model_id": MODEL_ID,
            "key_name": KEY_NAME,
            "inputs": [p.name for p in PERSONA_FILES],
            "cases_total": len(cases),
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "cases_not_run": len(cases),
            "stop_reason": "missing_repository_free_key",
            "cost_usd_reported": None,
            "cost_note": "No request was made; no cost was reported.",
            "agreement": {
                "compared": 0,
                "agree": 0,
                "disagree": 0,
                "model_label_counts": {},
                "rule_expected_counts": {},
                "note": "No labels available; no kappa or calibration claimed.",
            },
            "cases": [],
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote blocked-run record {OUTPUT}")
        return 2

    prior_report = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    prior_activity = {
        "labeling_calls": prior_report.get("calls", 0),
        "labeling_attempts": prior_report.get("run_attempts", []),
        "diagnostic_probes": [
            prior_report[key]
            for key in ("diagnostic_probe", "diagnostic_probe_retry", "diagnostic_probe_corrected")
            if key in prior_report
        ],
    }
    if prior_activity["labeling_calls"] != 10 or len(prior_activity["diagnostic_probes"]) != 3:
        print("ERROR: prior call count differs from the authorized 13-call history")
        return 2
    calls = success = failure = 0
    successful_calls = failed_calls = 0
    cost_total = 0.0
    cost_reported = False
    consecutive_failures = 0
    stop_reason = None
    results = []
    calls_before_case = 0

    try:
        for case in cases:
            calls_before_case = calls
            prompt = build_prompt(case, passages[case["scheme_id"]])
            outcome = None
            for attempt in (1, 2):  # one retry at most per case
                if calls >= MAX_CALLS:
                    raise StopRun("max_calls_reached")
                calls += 1
                try:
                    parsed, cost = call_model(api_key, prompt)
                    if cost is not None:
                        cost_reported = True
                        cost_total += cost
                        if cost_total > STOP_COST_USD:
                            raise StopRun("cost_above_limit")
                    consecutive_failures = 0
                    successful_calls += 1
                    outcome = parsed
                    break
                except StopRun as stop:
                    if stop.cost is not None:
                        cost_reported = True
                        cost_total += stop.cost
                    raise
                except ModelResponseError as error:
                    if error.cost is not None:
                        cost_reported = True
                        cost_total += error.cost
                        if cost_total > STOP_COST_USD:
                            raise StopRun("cost_above_limit") from error
                    consecutive_failures += 1
                    failed_calls += 1
                    print(f"call {calls} attempt {attempt} failed: invalid model response")
                    if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                        failure += 1
                        results.append({
                            **_case_out(case), "model_label": None,
                            "model_reason": None, "status": "failed",
                        })
                        raise StopRun("five_consecutive_failures") from error
                except urllib.error.HTTPError as error:
                    consecutive_failures += 1
                    failed_calls += 1
                    print(f"call {calls} attempt {attempt} HTTP {error.code}")
                    if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                        failure += 1
                        results.append({
                            **_case_out(case), "model_label": None,
                            "model_reason": None, "status": "failed",
                        })
                        raise StopRun("five_consecutive_failures")
                except ValueError as error:
                    consecutive_failures += 1
                    failed_calls += 1
                    print(f"call {calls} attempt {attempt} failed: {type(error).__name__}")
                    if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                        failure += 1
                        results.append({
                            **_case_out(case), "model_label": None,
                            "model_reason": None, "status": "failed",
                        })
                        raise StopRun("five_consecutive_failures") from error
                except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as error:
                    consecutive_failures += 1
                    failed_calls += 1
                    print(f"call {calls} attempt {attempt} failed: {type(error).__name__}")
                    if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                        failure += 1
                        results.append({
                            **_case_out(case), "model_label": None,
                            "model_reason": None, "status": "failed",
                        })
                        raise StopRun("five_consecutive_failures") from error
                time.sleep(1)
            if outcome is None:
                failure += 1
                results.append({**_case_out(case), "model_label": None, "model_reason": None,
                                "status": "failed"})
            else:
                success += 1
                results.append({**_case_out(case), "model_label": outcome["label"],
                                "model_reason": outcome["reason"], "status": "ok"})
    except StopRun as stop:
        stop_reason = stop.reason
        if calls > calls_before_case and len(results) < len(cases):
            last_case = _case_out(case)
            if not results or any(results[-1][key] != last_case[key] for key in ("source_file", "persona_id", "scheme_id")):
                failure += 1
                results.append({**last_case, "model_label": None, "model_reason": None,
                                "status": "stopped"})
        print(f"STOP: {stop_reason}")

    done = [r for r in results if r["status"] == "ok"]
    agree = sum(1 for r in done if r["model_label"] == r["rule_expected"])
    report = {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "completed" if stop_reason is None else "stopped",
        "model_id": MODEL_ID,
        "key_name": KEY_NAME,
        "inputs": [p.name for p in PERSONA_FILES],
        "cases_total": len(cases),
        "calls": calls,
        "prior_activity": prior_activity,
        "total_calls_including_prior": calls + 13,
        "successes": success,
        "failures": failure,
        "successful_calls": successful_calls,
        "failed_calls": failed_calls,
        "cases_not_run": len(cases) - len(results),
        "stop_reason": stop_reason,
        "cost_usd_reported": round(cost_total, 6) if cost_reported else None,
        "cost_note": "reported by OpenRouter usage.cost" if cost_reported
        else "OpenRouter did not return usage.cost; reported cost unavailable.",
        "agreement": {
            "compared": len(done),
            "agree": agree,
            "disagree": len(done) - agree,
            "model_label_counts": dict(Counter(r["model_label"] for r in done)),
            "rule_expected_counts": dict(Counter(r["rule_expected"] for r in done)),
            "note": "rule-engine expected is for information only; no kappa or calibration claimed",
        },
        "cases": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"calls={calls} success_cases={success} failed_cases={failure} "
        f"failed_calls={failed_calls} stop={stop_reason} "
        f"cost_reported={report['cost_usd_reported']} compared={len(done)} agree={agree}"
    )
    print(f"wrote {OUTPUT}")
    return 0


def _case_out(case: dict) -> dict:
    return {
        "source_file": case["source_file"],
        "persona_id": case["persona_id"],
        "boundary_family": case["boundary_family"],
        "scheme_id": case["scheme_id"],
        "rule_expected": case["rule_expected"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe:
        return run_probe()
    return run(live=args.live)


if __name__ == "__main__":
    raise SystemExit(main())
