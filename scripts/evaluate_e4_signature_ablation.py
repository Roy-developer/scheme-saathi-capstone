"""Run E4 signature-ablation arms (dev by default; never live authority).

Offline (no model calls):
  - shadow stub agreement vs rules
  - planned vs fixed question-order counts

Optional live LLM arm (``--llm-arm --yes``):
  - isolated free-model eligibility proposals from package source text
  - optional ``--multilingual`` en/hi/mr agreement
  - proposals never write live state / never replace rule verdicts

Team override (``--team-override``):
  - Waives PDF ≥40 unseen held-out bar
  - Uses development personas under freeze pin + go-ahead phrase
  - Claim level remains team-override, not PDF held-out
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_SET = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "e4_signature_ablation_latest.json"
TEAM_OVERRIDE_OUTPUT = (
    PROJECT_ROOT / "eval" / "reports" / "e4_team_override_signature_ablation_2026-11-13.json"
)
FREEZE_MANIFEST = PROJECT_ROOT / "eval" / "freeze" / "manifest.json"
STATUS_DOC = PROJECT_ROOT / "docs" / "e4_team_override_status_2026-11-13.md"
GO_AHEAD_PHRASE = "Team-override E4 signature ablation is **authorised**"


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def team_override_gate_failures() -> list[str]:
    failures: list[str] = []
    if not FREEZE_MANIFEST.is_file():
        return ["missing eval/freeze/manifest.json"]
    manifest = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    pin = manifest.get("e4_team_override_freeze")
    if not isinstance(pin, dict):
        return ["missing e4_team_override_freeze pin in freeze manifest"]
    gate = pin.get("paid_run_gate") or {}
    if not gate.get("authorised"):
        failures.append("e4_team_override_freeze.paid_run_gate.authorised is not true")
    persona = pin.get("persona_set") or {}
    rel = persona.get("path")
    local = PROJECT_ROOT / rel if rel else None
    if local is None or not local.is_file():
        failures.append(f"missing persona set {rel!r}")
    elif persona.get("sha256") and _sha256(local) != persona["sha256"]:
        failures.append("persona set sha256 does not match e4_team_override_freeze pin")
    text = STATUS_DOC.read_text(encoding="utf-8") if STATUS_DOC.is_file() else ""
    if GO_AHEAD_PHRASE not in text:
        failures.append(
            f"no go-ahead phrase in docs/e4_team_override_status_2026-11-13.md "
            f"(expected: {GO_AHEAD_PHRASE!r})"
        )
    return failures


def _relpath(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--team-override",
        action="store_true",
        help="Use team-override bar (dev personas; waive PDF ≥40 HO).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only check team-override gate / print plan.",
    )
    parser.add_argument(
        "--held-out",
        action="store_true",
        help="Allow a protected held-out persona set (Role-5 custody only).",
    )
    parser.add_argument(
        "--shadow-stub",
        action="store_true",
        default=True,
        help="Run offline scripted shadow comparison (default on).",
    )
    parser.add_argument(
        "--no-shadow-stub",
        action="store_true",
        help="Skip offline shadow stub arm.",
    )
    parser.add_argument(
        "--question-order",
        action="store_true",
        default=True,
        help="Run offline planned vs fixed question-order ablation (default on).",
    )
    parser.add_argument(
        "--no-question-order",
        action="store_true",
        help="Skip offline rule/picker question-order ablation.",
    )
    parser.add_argument(
        "--journey-question-order",
        action="store_true",
        default=True,
        help="Run journey-facing planned vs fixed interview ablation (default on).",
    )
    parser.add_argument(
        "--no-journey-question-order",
        action="store_true",
        help="Skip journey-facing question-order ablation.",
    )
    parser.add_argument(
        "--live-citizen",
        action="store_true",
        help=(
            "With journey Q-order, use a different live OpenRouter model as the "
            "simulated citizen (needs --yes). Card remains authoritative."
        ),
    )
    parser.add_argument(
        "--llm-arm",
        action="store_true",
        help="Run isolated live LLM eligibility arm (needs --yes).",
    )
    parser.add_argument(
        "--multilingual",
        action="store_true",
        help="With --llm-arm, also measure en/hi/mr verdict agreement.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Send OpenRouter model calls for --llm-arm.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on LLM-arm cases (smoke / cost control).",
    )
    parser.add_argument(
        "--scheme",
        action="append",
        dest="schemes",
        default=None,
        help="Limit LLM arm to scheme ID(s); repeatable.",
    )
    parser.add_argument(
        "--pace-seconds",
        type=float,
        default=3.5,
        help="Sleep between live LLM calls (free-tier pacing).",
    )
    args = parser.parse_args(argv)

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from eval.harness import e4_journey_question_order, e4_llm_arm, e4_shadow

    if args.team_override and args.held_out:
        print("Refuse: --team-override and --held-out are mutually exclusive.", file=sys.stderr)
        return 2

    output = args.output
    if output is None:
        output = TEAM_OVERRIDE_OUTPUT if args.team_override else DEFAULT_OUTPUT

    if args.team_override:
        failures = team_override_gate_failures()
        if failures:
            print("E4 team-override evaluate blocked:")
            for item in failures:
                print(f"- {item}")
            return 2
        freeze = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))[
            "e4_team_override_freeze"
        ]
        args.eval_set = PROJECT_ROOT / freeze["persona_set"]["path"]
        print(
            f"gate open: team_override_dev_personas, "
            f"cases={freeze['persona_set']['case_count']}, "
            f"claim=team_override_dev_personas; not PDF held-out"
        )
        if args.dry_run:
            print(json.dumps({
                "dry_run": True,
                "eval_set": str(args.eval_set),
                "output": str(output),
                "llm_arm": args.llm_arm,
                "multilingual": args.multilingual,
                "yes": args.yes,
            }, indent=2))
            return 0

    run_shadow = args.shadow_stub and not args.no_shadow_stub
    run_qo = args.question_order and not args.no_question_order
    run_journey_qo = (
        args.journey_question_order and not args.no_journey_question_order
    )
    if args.held_out and (run_shadow or run_qo or run_journey_qo):
        print(
            "held-out mode currently supports --llm-arm only "
            "(pass --no-shadow-stub --no-question-order "
            "--no-journey-question-order).",
            file=sys.stderr,
        )
        return 2

    if args.dry_run and not args.team_override:
        print(json.dumps({
            "dry_run": True,
            "eval_set": str(args.eval_set),
            "output": str(output),
            "llm_arm": args.llm_arm,
            "multilingual": args.multilingual,
        }, indent=2))
        return 0

    claim_level = (
        "team_override_dev_personas"
        if args.team_override
        else ("held_out_role5_only" if args.held_out else "development_only")
    )
    report: dict = {
        "experiment_id": "E4",
        "title": "Scheme Saathi signature ablation",
        "when": datetime.now(timezone.utc).isoformat(),
        "eval_set": str(args.eval_set),
        "claim_level": claim_level,
        "bar": "team_override_dev_personas" if args.team_override else None,
        "notice": e4_llm_arm.NON_AUTHORITATIVE_NOTICE,
        "arms": {},
        "blocker": None,
    }

    if run_shadow:
        shadow = asyncio.run(e4_shadow.run_shadow_comparison(eval_path=args.eval_set))
        report["arms"]["shadow_stub"] = {
            "status": "ran",
            "case_count": shadow["case_count"],
            "agree": shadow["agree"],
            "disagree": shadow["disagree"],
            "notice": shadow["notice"],
        }

    if run_qo:
        qo = e4_shadow.run_question_order_ablation(eval_path=args.eval_set)
        report["arms"]["question_order"] = {
            "status": "ran",
            "path": "offline_rule_picker",
            "case_count": qo["case_count"],
            "fixed_questions_total": qo["fixed_questions_total"],
            "planned_questions_total": qo["planned_questions_total"],
            "verdict_match_count": qo["verdict_match_count"],
            "questions_per_conversation": {
                "fixed_mean": round(
                    qo["fixed_questions_total"] / qo["case_count"], 4,
                ) if qo["case_count"] else None,
                "planned_mean": round(
                    qo["planned_questions_total"] / qo["case_count"], 4,
                ) if qo["case_count"] else None,
            },
            "notice": qo["notice"],
        }

    if run_journey_qo:
        citizen_model = None
        citizen_model_name = None
        if args.live_citizen:
            if not args.yes:
                print(
                    "Live citizen requested but --yes was not given; "
                    "using offline card citizen.",
                    file=sys.stderr,
                )
            else:
                _load_dotenv()
                from src.llm_client import openrouter_chat_model
                from src.rule_extraction_reflexion.scheme_rules import (
                    DEFAULT_EXTRACTION_MODEL,
                    NEMOTRON_COMPLETION_TOKENS,
                )

                api_key = (
                    os.getenv("OPENROUTER_API_KEY_FREE")
                    or os.getenv("OPEN_ROUTER_FREE")
                )
                if not api_key:
                    raise SystemExit(
                        "OPENROUTER_API_KEY_FREE is not set in the project .env"
                    )
                eligibility_model_name = os.getenv(
                    "OPENROUTER_RULE_EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL,
                )
                # Different model from the eligibility arm (PDF: simulated citizen
                # is a different model). Override with OPENROUTER_E4_CITIZEN_MODEL.
                citizen_model_name = os.getenv(
                    "OPENROUTER_E4_CITIZEN_MODEL",
                    "google/gemma-3-4b-it:free",
                )
                if citizen_model_name == eligibility_model_name:
                    print(
                        "Refuse: citizen model must differ from eligibility model "
                        f"({eligibility_model_name}). Set OPENROUTER_E4_CITIZEN_MODEL.",
                        file=sys.stderr,
                    )
                    return 2
                citizen_model = openrouter_chat_model(
                    api_key,
                    citizen_model_name,
                    timeout=70,
                    max_completion_tokens=NEMOTRON_COMPLETION_TOKENS,
                    reasoning_effort="none",
                )
                print(
                    f"journey question-order: live citizen model={citizen_model_name}"
                )
        print("journey question-order: running interview graph ablation…")
        jqo = asyncio.run(
            e4_journey_question_order.run_journey_question_order_ablation(
                eval_path=args.eval_set,
                allow_held_out=bool(args.held_out),
                scheme_ids=set(args.schemes) if args.schemes else None,
                limit=args.limit,
                citizen_model=citizen_model,
                citizen_model_name=citizen_model_name,
            )
        )
        detail_path = output.with_name(output.stem + "_journey_qo_cases.json")
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        detail_path.write_text(
            json.dumps(jqo, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        report["arms"]["journey_question_order"] = {
            "status": "ran",
            "path": "journey_interview_graph",
            "citizen_mode": jqo.get("citizen_mode", "offline_card"),
            "citizen_model": jqo.get("citizen_model"),
            "case_count": jqo["case_count"],
            "fixed_questions_total": jqo["fixed_questions_total"],
            "planned_questions_total": jqo["planned_questions_total"],
            "verdict_match_count": jqo["verdict_match_count"],
            "questions_per_conversation": jqo["questions_per_conversation"],
            "detail": _relpath(detail_path),
            "notice": jqo["notice"],
        }

    if args.llm_arm:
        if not args.yes:
            print(
                "LLM arm requested but --yes was not given; nothing was sent.",
                file=sys.stderr,
            )
            report["arms"]["llm_eligibility"] = {"status": "blocked_needs_yes"}
            report["blocker"] = "Pass --llm-arm --yes to spend free-model calls."
        else:
            _load_dotenv()
            from src.llm_client import openrouter_chat_model
            from src.rule_extraction_reflexion.scheme_rules import (
                DEFAULT_EXTRACTION_MODEL,
                NEMOTRON_COMPLETION_TOKENS,
            )

            api_key = (
                os.getenv("OPENROUTER_API_KEY_FREE")
                or os.getenv("OPEN_ROUTER_FREE")
            )
            if not api_key:
                raise SystemExit(
                    "OPENROUTER_API_KEY_FREE is not set in the project .env"
                )
            model_name = os.getenv(
                "OPENROUTER_RULE_EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL,
            )
            model = openrouter_chat_model(
                api_key,
                model_name,
                timeout=70,
                max_completion_tokens=NEMOTRON_COMPLETION_TOKENS,
                reasoning_effort="none",
            )
            locales = ("en", "hi", "mr") if args.multilingual else ("en",)
            calls_hint = (args.limit or "all")
            print(
                f"LLM arm: locales={list(locales)}; up to {calls_hint} cases "
                f"× {len(locales)} call(s) using {model_name}."
            )
            scheme_ids = set(args.schemes) if args.schemes else None
            llm_report = asyncio.run(
                e4_llm_arm.run_llm_eligibility_ablation(
                    proposer=model,
                    eval_path=args.eval_set,
                    allow_held_out=bool(args.held_out),
                    scheme_ids=scheme_ids,
                    limit=args.limit,
                    model_name=model_name,
                    locales=locales,
                    pace_seconds=args.pace_seconds,
                )
            )
            detail_path = output.with_name(output.stem + "_llm_cases.json")
            detail_path.parent.mkdir(parents=True, exist_ok=True)
            detail_path.write_text(
                json.dumps(llm_report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            report["arms"]["llm_eligibility"] = {
                "status": "ran",
                "model": model_name,
                "locales": llm_report["locales"],
                "case_count": llm_report["case_count"],
                "scored_case_count": llm_report["scored_case_count"],
                "provider_error_count": llm_report["provider_error_count"],
                "model_calls": llm_report["model_calls"],
                "agree_llm_rules": llm_report["agree_llm_rules"],
                "disagree_llm_rules": llm_report["disagree_llm_rules"],
                "agree_llm_expected": llm_report["agree_llm_expected"],
                "boundary_error_count_llm": llm_report["boundary_error_count_llm"],
                "boundary_error_count_rules": llm_report[
                    "boundary_error_count_rules"
                ],
                "boundary_error_rate_llm": llm_report["boundary_error_rate_llm"],
                "boundary_error_rate_rules": llm_report[
                    "boundary_error_rate_rules"
                ],
                "verdict_agreement_hi_mr_en": llm_report[
                    "verdict_agreement_hi_mr_en"
                ],
                "cost": llm_report["cost"],
                "median_latency_ms": llm_report["median_latency_ms"],
                "p95_latency_ms": llm_report["p95_latency_ms"],
                "detail": _relpath(detail_path),
                "notice": llm_report["notice"],
            }
    else:
        report["arms"]["llm_eligibility"] = {
            "status": "skipped",
            "note": "Pass --llm-arm --yes to run the isolated live LLM arm.",
        }
        if report["blocker"] is None and not args.team_override:
            report["blocker"] = (
                "Live LLM arm not run; held-out E4 claim still blocked without "
                "custody + dual labels + simulated citizen."
            )

    if args.team_override and report["arms"].get("llm_eligibility", {}).get("status") == "ran":
        report["blocker"] = None
        report["notes"] = [
            "Team override waives PDF ≥40 unseen held-out personas.",
            "LLM proposals remain non-authoritative.",
        ]

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # Keep latest pointer when team-override full run completes.
    if args.team_override and output != DEFAULT_OUTPUT:
        DEFAULT_OUTPUT.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "output": str(output),
        "claim_level": claim_level,
        "arms": {
            name: {k: v for k, v in arm.items() if k != "cases"}
            for name, arm in report["arms"].items()
        },
        "blocker": report["blocker"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
