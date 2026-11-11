"""Run the rule-extraction Reflexion loop on demand, on approved scheme clauses.

Each command calls one function of ``src/rule_extraction_reflexion``; nothing
here re-implements prompts, checks or comparison.

    evaluate  measure extraction on cases (model calls; never learns) -> evaluate_cases
    learn     propose lessons from "learn" cases (model calls)    -> run_reflexion_case
    lessons   list stored lessons and their reviews (free)
    review    approve or reject one lesson (free)                -> review_lesson
    freeze    save approved lessons as a playbook version (free) -> freeze_playbook
    export-playbook  write a frozen playbook to a file for git (free) -> export_playbook
    extract   draft rules for a NEW scheme with no approved rules (model calls) -> extract_rules
    onboard   put a scheme into the app (free)    -> plan_onboarding

Examples (PowerShell, from the repo root):

    python -m src.rule_extraction_reflexion.scheme_rules evaluate --runs 3                 # prints call count, then:
    python -m src.rule_extraction_reflexion.scheme_rules evaluate --runs 3 --yes
    python -m src.rule_extraction_reflexion.scheme_rules learn --yes
    python -m src.rule_extraction_reflexion.scheme_rules lessons
    python -m src.rule_extraction_reflexion.scheme_rules review <lesson_id> --approve --reviewer Roy-developer --reason "..."
    python -m src.rule_extraction_reflexion.scheme_rules freeze 1.0.0
    python -m src.rule_extraction_reflexion.scheme_rules export-playbook 1.0.0
    python -m src.rule_extraction_reflexion.scheme_rules freeze 1.1.0 --base 1.0.0
    python -m src.rule_extraction_reflexion.scheme_rules extract data/schemes/rule_extraction_sources/ignoaps_mh.json --playbook 1.0.0 --yes
    python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check --playbook 1.0.0 --runs 3 --yes
    python -m src.rule_extraction_reflexion.scheme_rules onboard IGNOAPS-MH                # shows every change, then:
    python -m src.rule_extraction_reflexion.scheme_rules onboard IGNOAPS-MH --yes

Frozen playbooks are shared through data/schemes/playbooks/ and copied into the
local store the first time they are used, so a fresh clone needs no database.

Cases come from data/schemes/rule_extraction_cases_dev.json: one entry per
approved clause, with its topic tags and split. Clause text, approved rules and
allowed facts are read from the rule package itself. Lessons, reviews and
playbooks are kept in data/runtime/reflexion_lessons.sqlite3 (not committed).
Model calls use the free OpenRouter key and rule-extraction model from .env.
The default model is Nemotron 3.5 Lightning's free route. Calls are counted
before execution and nothing is sent until --yes is given.
"""

import argparse
import asyncio
import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.store.sqlite.aio import AsyncSqliteStore
from pydantic import ValidationError

from src.config import load_project_dotenv
from src.llm_client import openrouter_chat_model
from src.rules.facts import FactRegistry
from src.rules.models import RulePackage
from src.rule_extraction_reflexion.onboarding import (
    OnboardingPlan, ProjectPaths, apply_onboarding, plan_onboarding,
)
from src.rule_extraction_reflexion.evaluation import evaluate_cases
from src.rule_extraction_reflexion.lesson_store import (
    LESSON_NAMESPACE, REVIEW_NAMESPACE, review_lesson,
)
from src.rule_extraction_reflexion.models import (
    RuleExtractionCase, SourceClause,
)
from src.rule_extraction_reflexion.extractor import extract_rules
from src.rule_extraction_reflexion.playbook import (
    SharedPlaybookError, export_playbook, freeze_playbook, load_frozen_playbook,
    load_playbook, relevant_lessons,
)
from src.rule_extraction_reflexion.reflexion import run_reflexion_case

load_project_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = PROJECT_ROOT / "src" / "rules"
CASES_FILE = PROJECT_ROOT / "data" / "schemes" / "rule_extraction_cases_dev.json"
STORE_FILE = PROJECT_ROOT / "data" / "runtime" / "reflexion_lessons.sqlite3"
REPORT_DIR = PROJECT_ROOT / "data" / "runtime" / "reflexion_reports"
DRAFT_DIR = PROJECT_ROOT / "data" / "runtime" / "reflexion_drafts"
PLAYBOOK_DIR = PROJECT_ROOT / "data" / "schemes" / "playbooks"
SPLITS = ("learn", "check")
DEFAULT_EXTRACTION_MODEL = "nvidia/nemotron-3.5-lightning:free"
NEMOTRON_COMPLETION_TOKENS = 2048


def load_case_file(path: Path | None = None) -> dict:
    return json.loads((path or CASES_FILE).read_text(encoding="utf-8"))


def _load_case_package(entry: dict, rules_dir: Path) -> RulePackage:
    """Load a case's approved package.

    Live packages are in src/rules/packages. A package approved only as a
    Reflexion answer key (not registered in the app, which would refuse an
    unbundled file there) sets ``package_dir`` to a repo-relative folder and
    pins ``package_sha256`` so it cannot change unnoticed.
    """
    folder = PROJECT_ROOT / entry["package_dir"] if "package_dir" in entry else rules_dir / "packages"
    raw = (folder / entry["package"]).read_bytes()
    pinned = entry.get("package_sha256")
    if pinned and hashlib.sha256(raw).hexdigest() != pinned:
        raise ValueError(f"Package hash mismatch for {entry['package']}")
    return RulePackage.model_validate_json(raw)


def build_cases(
    split: str | None = None, *, path: Path | None = None, rules_dir: Path = RULES_DIR,
) -> list[RuleExtractionCase]:
    """Build one case per listed clause from its approved package.

    Args:
        split: "learn" or "check" to select that split only; None selects all.
    """
    data = load_case_file(path)
    known_tags = set(data["topic_tags"])
    contexts = data.get("contexts", {})
    cases = []
    for entry in data["cases"]:
        if entry["split"] not in (None, *SPLITS):
            raise ValueError(f"Unknown split for {entry['clause_id']}: {entry['split']}")
        if split is not None and entry["split"] != split:
            continue
        unknown = set(entry["topic_tags"]) - known_tags
        if unknown:
            raise ValueError(f"Undeclared topic tags for {entry['clause_id']}: {sorted(unknown)}")
        package = _load_case_package(entry, rules_dir)
        rules = tuple(r for r in package.rules if r.source_clause_id == entry["clause_id"])
        if not rules:
            raise ValueError(f"No approved rules cite clause {entry['clause_id']} in {entry['package']}")
        missing = [name for name in entry.get("context", []) if name not in contexts]
        if missing:
            raise ValueError(f"Unknown context for {entry['clause_id']}: {missing}")
        # A list item is shown after the headings it sits under in the source
        # (e.g. "shall not be eligible"), as a person reading the document sees it.
        # One clause, one ID, so the model cannot cite a heading instead.
        text = "\n".join(
            [contexts[name]["text"] for name in entry.get("context", [])] + [rules[0].source_text]
        )
        cases.append(RuleExtractionCase(
            case_id=entry["clause_id"],
            clauses=(SourceClause(
                clause_id=entry["clause_id"],
                text=text,
                location=rules[0].source_location,
            ),),
            expected_rules=rules,
            allowed_fact_ids=tuple(sorted({r.field for r in rules})),
            topic_tags=tuple(entry["topic_tags"]),
        ))
    return cases


def load_registry(rules_dir: Path = RULES_DIR) -> FactRegistry:
    return FactRegistry.model_validate_json((rules_dir / "fact_registry.json").read_bytes())


def project_model() -> tuple[BaseChatModel, str]:
    """Build the rule-extraction model with the free OpenRouter credential."""
    api_key = os.getenv("OPENROUTER_API_KEY_FREE") or os.getenv("OPEN_ROUTER_FREE")
    model_name = os.getenv(
        "OPENROUTER_RULE_EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL,
    )
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY_FREE is not set in the project .env")
    if model_name == DEFAULT_EXTRACTION_MODEL:
        return openrouter_chat_model(
            api_key,
            model_name,
            max_completion_tokens=NEMOTRON_COMPLETION_TOKENS,
            reasoning_effort="none",
        ), model_name
    return openrouter_chat_model(api_key, model_name), model_name


def rejection_detail(error: ValueError) -> str:
    """Explain a rejected answer, including exactly what the model wrote.

    Pydantic's own message shortens the model's answer ("{'rule_id': 'rule_1',
    'fi...sing_field_label': None}"), which hid the pension clause's problem.
    """
    if not isinstance(error, ValidationError):
        return str(error)
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'reply'}: {item['msg']} "
        f"| model wrote: {json.dumps(item.get('input'), ensure_ascii=False, default=str)}"
        for item in error.errors()
    )


def _rule_text(rule) -> str:
    return f"{rule.field} {rule.operator} {rule.value}{' ' + rule.unit if rule.unit else ''}"


async def evaluate(
    model: BaseChatModel, cases: list[RuleExtractionCase], registry: FactRegistry,
    *, runs: int, playbook_version: str | None, store_path: Path = STORE_FILE,
    report_dir: Path = REPORT_DIR,
) -> dict:
    """Measure extraction on each case ``runs`` times; never stores lessons."""
    playbook = None
    if playbook_version:
        async with AsyncSqliteStore.from_conn_string(str(store_path)) as store:
            await store.setup()
            playbook = await load_playbook(store, playbook_version, PLAYBOOK_DIR)
    rows = []
    for case in cases:
        for run in range(1, runs + 1):
            try:
                # One case per call so one rejected reply does not stop the others.
                report = await evaluate_cases(model, [case], registry, playbook=playbook)
                result = report.results[0]
                status = "exact" if result.exact_match else "different"
                detail = {d.rule_id: list(d.attributes) for d in result.differences}
            except ValueError as error:
                # Keep the whole message: it shows what the model actually wrote.
                status, detail = "rejected", rejection_detail(error)
            rows.append({"case": case.case_id, "run": run, "status": status, "detail": detail})
            print(f"{case.case_id:<40} run {run}: {status:<9} {detail or ''}")
    summary = {
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "playbook": playbook_version,
        "exact": sum(r["status"] == "exact" for r in rows),
        "total": len(rows),
        "rows": rows,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / f"evaluate_{summary['when'][:19].replace(':', '')}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nexact {summary['exact']}/{summary['total']}  (playbook: {playbook_version or 'none'})  -> {out}")
    return summary


async def learn(
    model: BaseChatModel, cases: list[RuleExtractionCase], registry: FactRegistry,
    *, store_path: Path = STORE_FILE,
) -> list[str]:
    """Run the Reflexion loop on learn cases; returns the new pending lesson IDs."""
    created = []
    async with AsyncSqliteStore.from_conn_string(str(store_path)) as store:
        await store.setup()
        for case in cases:
            try:
                result = await run_reflexion_case(model, case, registry, store)
            except ValueError as error:
                print(f"{case.case_id:<40} rejected: {rejection_detail(error)}")
                continue
            if result.pending_lesson is None:
                print(f"{case.case_id:<40} correct, no lesson")
                continue
            lesson = result.pending_lesson
            created.append(lesson.lesson_id)
            print(f"{case.case_id:<40} differences {result.differences}")
            print(f"  model wrote : {'; '.join(_rule_text(r) for r in result.proposed_rules) or '(no rules)'}")
            print(f"  lesson      : {lesson.lesson_id}")
            print(f"  instruction : {lesson.proposal.instruction}")
            print(f"  when        : {lesson.proposal.when_to_apply}")
            print(f"  tags        : {', '.join(lesson.proposal.tags)}")
    return created


async def list_lessons(*, store_path: Path = STORE_FILE) -> list[dict]:
    rows = []
    async with AsyncSqliteStore.from_conn_string(str(store_path)) as store:
        await store.setup()
        for item in await store.asearch(LESSON_NAMESPACE, limit=500):
            review = await store.aget(REVIEW_NAMESPACE, item.key)
            rows.append({
                "lesson_id": item.key,
                "case": item.value["source_case_id"],
                "instruction": item.value["proposal"]["instruction"],
                "tags": item.value["proposal"]["tags"],
                "review": review.value["decision"] if review else "pending",
            })
    for row in rows:
        print(f"{row['lesson_id']}  [{row['review']}]  {row['case']}  tags={row['tags']}")
        print(f"    {row['instruction']}")
    if not rows:
        print("No lessons stored.")
    return rows


async def review(
    lesson_id: str, *, approve: bool, reviewer: str, reason: str,
    authorized: Callable[[str], bool], store_path: Path = STORE_FILE,
) -> str:
    async with AsyncSqliteStore.from_conn_string(str(store_path)) as store:
        await store.setup()
        recorded = await review_lesson(
            store, lesson_id=lesson_id, decision="approved" if approve else "rejected",
            reviewer_id=reviewer, reason=reason, authorize_reviewer=authorized,
        )
    print(f"{lesson_id}: {recorded.decision} by {recorded.reviewer_id}")
    return recorded.decision


async def freeze(version: str, *, base: str | None = None, store_path: Path = STORE_FILE) -> int:
    if (PLAYBOOK_DIR / f"{version}.json").exists():
        raise SharedPlaybookError(f"Playbook {version} is already shared; freeze a new version.")
    async with AsyncSqliteStore.from_conn_string(str(store_path)) as store:
        await store.setup()
        base_playbook = await load_playbook(store, base, PLAYBOOK_DIR) if base else None
        snapshot = await freeze_playbook(store, version, base=base_playbook)
    print(f"playbook {snapshot.version}: {len(snapshot.lessons)} approved lesson(s), hash {snapshot.content_hash}")
    for lesson in snapshot.lessons:
        print(f"  [{', '.join(lesson.tags)}] {lesson.instruction}")
    return len(snapshot.lessons)


async def export(version: str, *, store_path: Path = STORE_FILE) -> Path:
    """Write a frozen playbook to the shared folder, ready to commit."""
    async with AsyncSqliteStore.from_conn_string(str(store_path)) as store:
        await store.setup()
        try:
            snapshot = await load_frozen_playbook(store, version)
        except KeyError as error:
            raise SharedPlaybookError(f"Playbook {version} is not frozen in the local store.") from error
    path = export_playbook(snapshot, PLAYBOOK_DIR)
    print(f"playbook {version}: {len(snapshot.lessons)} lesson(s), hash {snapshot.content_hash} -> {path}")
    return path


def build_source_cases(path: Path) -> tuple[dict, list[RuleExtractionCase]]:
    """Build cases with NO answer key from a new scheme's source file.

    The file holds the official clause text itself, because a new scheme has
    no approved package to read it from. Topic tags must be declared in the
    cases file, so lessons can be matched.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    known_tags = set(load_case_file()["topic_tags"])
    cases = []
    for entry in data["cases"]:
        unknown = set(entry["topic_tags"]) - known_tags
        if unknown:
            raise ValueError(f"Undeclared topic tags for {entry['clause_id']}: {sorted(unknown)}")
        cases.append(RuleExtractionCase(
            case_id=entry["clause_id"],
            clauses=(SourceClause(
                clause_id=entry["clause_id"], text=entry["text"], location=entry.get("location"),
            ),),
            expected_rules=(),
            allowed_fact_ids=tuple(entry["allowed_fact_ids"]),
            topic_tags=tuple(entry["topic_tags"]),
        ))
    return data, cases


async def extract(
    model: BaseChatModel, source: dict, cases: list[RuleExtractionCase], registry: FactRegistry,
    *, playbook_version: str | None, model_name: str = "", store_path: Path = STORE_FILE,
    draft_dir: Path = DRAFT_DIR,
) -> dict:
    """Draft rules for a new scheme; nothing is compared, learned or approved."""
    playbook = None
    if playbook_version:
        async with AsyncSqliteStore.from_conn_string(str(store_path)) as store:
            await store.setup()
            playbook = await load_playbook(store, playbook_version, PLAYBOOK_DIR)
    drafts = []
    for case in cases:
        used = relevant_lessons(playbook, case.topic_tags) if playbook else ()
        entry = {
            "clause_id": case.case_id,
            "source_text": case.clauses[0].text,
            "lessons_used": [lesson.instruction for lesson in used],
        }
        try:
            rules = await extract_rules(model, case, registry, playbook=playbook)
            entry["status"] = "drafted"
            entry["draft_rules"] = [
                rule.model_dump(mode="json", include={
                    "rule_id", "field", "operator", "value", "unit", "source_clause_id", "source_location",
                }) for rule in rules
            ]
            shown = "; ".join(_rule_text(rule) for rule in rules) or "(no rules)"
        except ValueError as error:
            entry["status"] = "rejected"
            entry["detail"] = rejection_detail(error)
            shown = f"rejected: {entry['detail']}"
        drafts.append(entry)
        print(f"{case.case_id}")
        print(f"  lessons used: {len(used)}")
        for lesson in used:
            print(f"    - {lesson.instruction}")
        print(f"  draft       : {shown}")
    record = {
        "status": "draft_for_human_review_not_policy",
        "scheme_id": source["scheme_id"],
        "source": source.get("source"),
        "model": model_name,
        "playbook": playbook_version,
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "clauses": drafts,
    }
    draft_dir.mkdir(parents=True, exist_ok=True)
    out = draft_dir / f"{source['scheme_id'].lower()}_{record['when'][:19].replace(':', '')}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDraft saved (for review, not policy) -> {out}")
    return record


def _run_test_suite() -> bool:
    """Run the offline test suite against the onboarded project."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"], cwd=PROJECT_ROOT, check=False,
    ).returncode == 0


def onboard(
    scheme_id: str, *, yes: bool, paths: ProjectPaths | None = None, run_tests: bool = True,
) -> OnboardingPlan:
    """Show every change for a scheme; write them only with ``yes``."""
    plan = plan_onboarding(scheme_id, paths or ProjectPaths(PROJECT_ROOT))
    print(f"Onboarding {scheme_id}")
    for line in plan.summary:
        print(f"  {line}")
    print("\nStill for people:")
    for line in plan.for_people:
        print(f"  - {line}")
    if not yes:
        print("\nNothing was written. Add --yes to apply it.")
        return plan
    apply_onboarding(plan)
    print(f"\nApplied: {len(plan.changes)} file(s) written. Nothing is committed.")
    if run_tests:
        # Kept even if tests fail: a new scheme can break tests that hard-code
        # the number of schemes or passages, and those need a person to read.
        print("Tests passed." if _run_test_suite() else "Tests FAILED: see the output above.")
    return plan


def _confirm_model_calls(calls: int, yes: bool) -> bool:
    """State the model-call count and run only with --yes."""
    model_name = os.getenv(
        "OPENROUTER_RULE_EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL,
    )
    print(f"This makes up to {calls} OpenRouter model call(s) using {model_name}.")
    if not yes:
        print("Nothing was sent. Add --yes to run it.")
    return yes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    evaluate_cmd = commands.add_parser("evaluate", help="Measure extraction with model calls; never learns.")
    evaluate_cmd.add_argument("--split", choices=SPLITS, help="Only this split (default: every case).")
    evaluate_cmd.add_argument("--playbook", help="Frozen playbook version to use.")
    evaluate_cmd.add_argument("--runs", type=int, default=1)
    evaluate_cmd.add_argument("--yes", action="store_true", help="Send the model calls.")

    learn_cmd = commands.add_parser("learn", help="Propose lessons from learn cases with model calls.")
    learn_cmd.add_argument("--yes", action="store_true", help="Send the model calls.")

    commands.add_parser("lessons", help="List stored lessons and reviews.")

    review_cmd = commands.add_parser("review", help="Approve or reject one lesson.")
    review_cmd.add_argument("lesson_id")
    decision = review_cmd.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    review_cmd.add_argument("--reviewer", required=True)
    review_cmd.add_argument("--reason", required=True)

    freeze_cmd = commands.add_parser("freeze", help="Save approved lessons as a playbook version.")
    freeze_cmd.add_argument("version", help="For example 1.0.0")
    freeze_cmd.add_argument("--base", help="Earlier playbook whose lessons are kept.")

    export_cmd = commands.add_parser("export-playbook", help="Write a frozen playbook to a file for git.")
    export_cmd.add_argument("version", help="For example 1.0.0")

    extract_cmd = commands.add_parser("extract", help="Draft rules for a new scheme with model calls; never policy.")
    extract_cmd.add_argument("source_file", type=Path, help="A file in data/schemes/rule_extraction_sources/")
    extract_cmd.add_argument("--playbook", help="Frozen playbook version to use.")
    extract_cmd.add_argument("--yes", action="store_true", help="Send the model calls.")

    onboard_cmd = commands.add_parser("onboard", help="Put a scheme into the app.")
    onboard_cmd.add_argument("scheme_id", help="For example IGNOAPS-MH")
    onboard_cmd.add_argument("--yes", action="store_true", help="Write the changes.")
    onboard_cmd.add_argument("--skip-tests", action="store_true", help="Do not run the test suite after writing.")

    args = parser.parse_args(argv)
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if args.command == "evaluate":
        cases = build_cases(args.split)
        if _confirm_model_calls(len(cases) * args.runs, args.yes):
            model, name = project_model()
            print(f"model: {name}\n")
            asyncio.run(evaluate(model, cases, load_registry(),
                                 runs=args.runs, playbook_version=args.playbook))
    elif args.command == "learn":
        cases = build_cases("learn")
        if not cases:
            raise SystemExit("No clause has split \"learn\" in rule_extraction_cases_dev.json. "
                             "Assign the split first; check clauses are never learned from.")
        # One extraction per case, plus one reflection call when it differs.
        if _confirm_model_calls(2 * len(cases), args.yes):
            model, name = project_model()
            print(f"model: {name}\n")
            asyncio.run(learn(model, cases, load_registry()))
    elif args.command == "lessons":
        asyncio.run(list_lessons())
    elif args.command == "review":
        reviewers = set(load_case_file()["authorized_reviewers"])
        asyncio.run(review(
            args.lesson_id, approve=args.approve, reviewer=args.reviewer, reason=args.reason,
            authorized=lambda reviewer_id: reviewer_id in reviewers,
        ))
    elif args.command == "freeze":
        asyncio.run(freeze(args.version, base=args.base))
    elif args.command == "export-playbook":
        asyncio.run(export(args.version))
    elif args.command == "extract":
        source, cases = build_source_cases(args.source_file)
        if _confirm_model_calls(len(cases), args.yes):
            model, name = project_model()
            print(f"model: {name}\n")
            asyncio.run(extract(model, source, cases, load_registry(),
                                playbook_version=args.playbook, model_name=name))
    elif args.command == "onboard":
        try:
            onboard(args.scheme_id, yes=args.yes, run_tests=not args.skip_tests)
        except ValueError as error:
            raise SystemExit(f"Refused: {error}") from error


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except SharedPlaybookError as error:
        raise SystemExit(f"Refused: {error}") from error
