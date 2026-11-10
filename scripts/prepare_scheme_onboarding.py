"""Stage everything a scheme needs before `scheme_rules onboard`, for any gold scheme.

For each scheme this reads the reviewed gold rules (data/schemes/rule_gold_drafts),
the scheme's passages and the field catalog, and writes to
data/schemes/onboarding_staging/<SCHEME-ID>/:

    package.json      a rule package (status: pending human approval)
    source_file.json  the source file `scheme_rules extract/onboard` reads
    new_facts.json    fact definitions the registry does not have yet (all pending)
    REVIEW.md         a review sheet with the approval line left unsigned
    status.json       ready, or blocked with the reasons

It NEVER edits the live app: not the fact registry, bundles, packages, passages
or cases. Every file it writes is checked with the app's own RulePackage and
FactDefinition models. People still have to: approve the facts, review and sign
off the scheme, add the app-approval line, and write checklists and mock forms.

Usage:
    python -m scripts.prepare_scheme_onboarding --schemes NSAP-IGNOAPS-IN IGNWPS-IN
    python -m scripts.prepare_scheme_onboarding --all
    python -m scripts.prepare_scheme_onboarding --all --draft-missing   # paid: model drafts missing catalog fields
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

from src.rules.extraction import DraftRuleSet
from src.rules.facts import FactDefinition, FactRegistry
from src.rules.models import RulePackage

ROOT = Path(__file__).resolve().parents[1]
SCHEMES = ROOT / "data" / "schemes"
STAGING = SCHEMES / "onboarding_staging"
CATALOG = SCHEMES / "onboarding" / "field_catalog.json"
REGISTRY = ROOT / "src" / "rules" / "fact_registry.json"
BUNDLES = ROOT / "src" / "rules" / "bundle_registry.json"
SUPPORTED_OPERATORS = {"eq", "gte", "lte"}
# Operators flip when an exclusion ("must NOT be ...") is written as a rule on who qualifies.
NEGATED = {"gte": "lt", "lte": "gt", "gt": "lte", "lt": "gte"}
PRIVACY = {
    "policy_id": "synthetic-mock-minimum-data", "version": "1.0.0",
    "purpose": "Use only to evaluate the synthetic mock scheme rules.", "review_status": "pending",
}


def _norm(text: str) -> str:
    return " ".join(text.split())


def load_passages() -> dict[str, list[dict]]:
    by_scheme: dict[str, list[dict]] = {}
    for path in sorted((SCHEMES / "passages").glob("*.json")):
        for item in json.loads(path.read_text(encoding="utf-8"))["passages"]:
            by_scheme.setdefault(item["scheme_id"], []).append(item)
    return by_scheme


def gold_schemes() -> dict[str, Path]:
    selection = json.loads((SCHEMES / "rule_gold_selection.json").read_text(encoding="utf-8"))
    return {s["scheme_id"]: SCHEMES / s["draft_file"] for s in selection["schemes"]}


def fact_for(field: str, catalog: dict, registry_ids: set[str]) -> tuple[str | None, dict | None]:
    entry = catalog.get(field)
    if entry is None:
        return None, None
    if entry["action"] == "use_existing":
        return (entry["fact_id"] if entry["fact_id"] in registry_ids else None), entry
    return field, entry


def new_fact_definition(fact_id: str, entry: dict, source_url: str) -> dict:
    return {
        "fact_id": fact_id, "version": "1.0.0", "meaning": entry["meaning"],
        "source_refs": [source_url], "definition_review_status": "pending",
        "definition_reviewer": None, "definition_reviewed_at": None,
        "scope": entry["scope"], "value_type": entry["value_type"],
        "unit": entry.get("unit"), "period": None,
        "minimum": entry.get("minimum"), "maximum": entry.get("maximum"),
        "choices": [], "max_length": None, "display_only": False,
        "derived_from": [], "derivation": None,
        "questions": entry["questions"], "question_review_status": "pending",
        "privacy": {**PRIVACY, "sensitivity": entry["sensitivity"]},
        "legacy_profile_field": None,
    }


def stage_scheme(scheme_id: str, gold_path: Path, passages: list[dict], catalog: dict,
                 registry_ids: set[str]) -> dict:
    live = {b["scheme_id"] for b in json.loads(BUNDLES.read_text(encoding="utf-8"))["bundles"]}
    if scheme_id in live:
        return {"status": {"scheme_id": scheme_id, "already_in_app": True, "ready_for_review": False,
                           "package_rules": 0, "gold_rules": 0, "new_facts": [], "blockers": [],
                           "notes": ["Already in src/rules/bundle_registry.json; nothing to stage."]}}
    gold = DraftRuleSet.model_validate(json.loads(gold_path.read_text(encoding="utf-8")))
    by_id = {p["passage_id"]: p for p in passages}
    blockers: list[str] = []
    notes: list[str] = []
    rules, required, new_facts, checks = [], [], {}, []
    cases: dict[str, dict] = {}

    for rule in gold.rules:
        passage = by_id.get(rule.source_passage_id)
        if passage is None:
            blockers.append(f"{rule.rule_id}: passage {rule.source_passage_id} not found")
            continue
        fact_id, entry = fact_for(rule.field, catalog, registry_ids)
        if fact_id is None:
            blockers.append(f"{rule.rule_id}: field '{rule.field}' is not in the field catalog "
                            "(add it, or run with --draft-missing)")
            continue
        if entry.get("reviewer_check"):
            checks.append(f"{rule.field} -> {fact_id}: {entry['reviewer_check']}")
        operator, value = rule.operator, rule.value
        if rule.kind == "exclusion":
            if isinstance(value, bool) and operator == "eq":
                value = not value
            elif operator in NEGATED:
                operator = NEGATED[operator]
            else:
                blockers.append(f"{rule.rule_id}: cannot turn this exclusion into a qualifying rule")
                continue
        if operator not in SUPPORTED_OPERATORS:
            blockers.append(f"{rule.rule_id}: operator '{operator}' on {fact_id} is not supported "
                            "by rule packages (only eq, gte, lte)")
            continue
        if fact_id == "age" and not (isinstance(value, (int, float)) and float(value).is_integer()):
            blockers.append(f"{rule.rule_id}: age needs a whole number")
            continue
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        text = passage["text"]
        rules.append({
            "rule_id": rule.rule_id, "field": fact_id, "operator": operator, "value": value,
            **({"unit": rule.unit} if rule.unit else {}),
            "source_clause_id": rule.source_passage_id, "source_text": text,
            "source_location": passage["source"].get("locator"),
        })
        needed = ["date_of_birth", "application_date"] if fact_id == "age" else [fact_id]
        for n in needed:
            if n not in required:
                required.append(n)
        if entry["action"] == "new" and fact_id not in new_facts:
            new_facts[fact_id] = entry
        case = cases.setdefault(rule.source_passage_id, {
            "clause_id": rule.source_passage_id, "text": text,
            "location": passage["source"].get("locator"),
            "allowed_fact_ids": [], "kinds": set(),
        })
        case["kinds"].add(rule.kind)
        for n in needed:
            if n not in case["allowed_fact_ids"]:
                case["allowed_fact_ids"].append(n)

    if not rules:
        blockers.append("no rule could be built")
    first = next(iter(by_id.values()), None)
    source = first["source"] if first else {}
    status = {"scheme_id": scheme_id, "gold_rules": len(gold.rules), "package_rules": len(rules),
              "new_facts": sorted(new_facts), "reviewer_checks": checks, "blockers": blockers,
              "notes": notes}
    # Passages already in the corpus under another file name would be added a second
    # time by `onboard`; flag it so a person decides.
    status["notes"].append(
        f"{len(passages)} passage(s) for {scheme_id} are already in data/schemes/passages; "
        "`onboard` writes a new <scheme>_passages.json and would duplicate them unless that file name matches or the step is skipped."
    )
    if blockers or not first:
        status["ready_for_review"] = False
        return {"status": status}

    sources = {p["source"]["url"] for p in passages if p["passage_id"] in cases}
    url = sorted(sources)[0] if sources else first["source"]["url"]
    unresolved = list(gold.unresolved)
    package = {
        "package_version": "1.0.0", "scheme_id": scheme_id,
        "approval_status": "mock_baseline_pending_human_rule_approval",
        "reviewer_name": "Pending human review", "reviewed_at": date.today().isoformat(),
        "approval_scope": "synthetic_mock_portal_only",
        "source": {
            "publisher": source.get("publisher", "Unknown"), "source_url": url,
            "collected_at": source.get("collected_at", date.today().isoformat()),
            "official_eligibility_text": " ".join(c["text"] for c in cases.values()),
            "publication_date_status": "verified" if source.get("publication_date") else "not_confirmed",
        },
        "required_facts": required,
        **({"age_as_of": "application_date", "age_boundaries_inclusive": True} if "date_of_birth" in required else {}),
        "documents_status": "not_verified",
        "reasons": {
            "eligible": f"All reviewed mock conditions for {first['scheme_name']} are met.",
            "not_eligible": "One or more required mock scheme conditions are not met.",
            "need_more_information": "Some details are still needed before this mock check can be completed.",
        },
        "notice": (f"This mock result uses the published criteria of {source.get('publisher', 'the scheme owner')} "
                   f"(collected {source.get('collected_at', 'unknown date')}). It is not a government decision; "
                   "records and documents are not verified."),
        "unresolved_checks": unresolved,
        "rules": rules,
    }
    RulePackage.model_validate(package)
    unresolved_facts = sorted({f for f in required if f not in registry_ids and f not in new_facts})
    if unresolved_facts:
        status["blockers"].append(f"facts neither in the registry nor staged: {unresolved_facts}")
        status["ready_for_review"] = False
        return {"status": status}

    facts = []
    for fact_id, entry in sorted(new_facts.items()):
        definition = new_fact_definition(fact_id, entry, url)
        FactDefinition.model_validate(definition)
        facts.append(definition)

    source_file = {
        "scheme_id": scheme_id, "scheme_name": first["scheme_name"],
        "status": "source_text_for_drafting_only",
        "note": "Generated by scripts/prepare_scheme_onboarding.py from the reviewed gold rules and the passage corpus. Text is copied from the passages. Anything derived from this file is a draft for human review, never policy.",
        "source": {"publisher": source.get("publisher"), "source_url": url,
                   "retrieved": source.get("collected_at"), "page_last_updated": source.get("publication_date")},
        "reviewer_decisions": {"reviewer": None, "date": None,
                               "note": "A person must record policy the text does not state (age date, inclusive ends, what 'unknown' means)."},
        "onboarding": {
            "scheme_name": first["scheme_name"], "jurisdiction": first["jurisdiction"],
            "source_id": source.get("source_id"), "publication_date": source.get("publication_date"),
            "passages": [{"passage_id": p["passage_id"], "section": p["section"], "text": p["text"],
                          "locator": p["source"].get("locator"),
                          "review_status": "reviewed" if p["review_status"] == "reviewed" else "pending_review"}
                         for p in passages if p["language"] == "en"],
        },
        "cases": [{"clause_id": c["clause_id"], "text": c["text"], "location": c["location"],
                   "allowed_fact_ids": c["allowed_fact_ids"],
                   "topic_tags": ["exclusion_clause" if c["kinds"] == {"exclusion"} else "inclusion_clause"]}
                  for c in cases.values()],
    }
    out = STAGING / scheme_id
    out.mkdir(parents=True, exist_ok=True)
    write = lambda name, data: (out / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write("package.json", package)
    write("source_file.json", source_file)
    write("new_facts.json", facts)
    package_sha = hashlib.sha256((out / "package.json").read_bytes()).hexdigest()
    status.update(ready_for_review=True, package_sha256=package_sha)
    write("status.json", status)
    (out / "REVIEW.md").write_text(review_sheet(scheme_id, package, status, rules), encoding="utf-8")
    return {"status": status}


def review_sheet(scheme_id: str, package: dict, status: dict, rules: list[dict]) -> str:
    lines = [f"# {scheme_id}: rule review sheet (staged {date.today().isoformat()})", "",
             "Status: **not approved.** Generated from the reviewed gold rules; a person must check it.", "",
             "## Rules (each must match its official source text)", "",
             "| Rule | Fact | Operator | Value | Source clause |", "|---|---|---|---|---|"]
    lines += [f"| {r['rule_id']} | {r['field']} | {r['operator']} | {r['value']} | {r['source_clause_id']} |" for r in rules]
    lines += ["", "## New facts to approve", ""]
    lines += [f"- {f}" for f in status["new_facts"]] or ["- none"]
    lines += ["", "## Reviewer checks", ""] + ([f"- {c}" for c in status["reviewer_checks"]] or ["- none"])
    lines += ["", "## Not encoded (from the gold file)", ""] + ([f"- {u}" for u in package["unresolved_checks"]] or ["- none"])
    lines += ["", "## Notes", ""] + [f"- {n}" for n in status["notes"]]
    lines += ["", "## Sign-off (a person fills these in)", "",
              "- Evidence review: pending", "- Independent second review: pending",
              "- Human sign-off: pending", "",
              "App approval line (add only after sign-off; hash is of `package.json` as staged):", "",
              "```text", f"App approval: `{scheme_id}` approved by `<github-login>` on <YYYY-MM-DD> for package SHA-256 `{status['package_sha256']}`",
              "```", ""]
    return "\n".join(lines)


def draft_missing_fields(missing: set[str]) -> int:
    """Ask a model to draft catalog entries for unknown fields (paid; saved as 'new', pending review)."""
    import os
    from scripts.extract_scheme_rules import openrouter_complete
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required for --draft-missing")
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    system = ("You write registry fact definitions for a welfare-scheme eligibility app. Return JSON only: "
              '{"scope":"person|family","value_type":"boolean|integer|decimal","unit":null,"minimum":null,"maximum":null,'
              '"sensitivity":"ordinary|sensitive|highly_sensitive","meaning":"...","questions":{"en":{"text":"..."},"hi":{"text":"..."},"mr":{"text":"..."}}}. '
              "Questions are short yes/no or number questions to a citizen, in plain language.")
    added = 0
    for field in sorted(missing):
        raw = openrouter_complete(system, json.dumps({"field_name": field}))
        entry = json.loads(raw)
        entry["action"] = "new"
        entry["reviewer_check"] = "Drafted by a model: check meaning and all three languages."
        try:
            new_fact_definition(field, entry, "https://example.org/placeholder")
            FactDefinition.model_validate(new_fact_definition(field, entry, "https://example.org/placeholder"))
        except Exception as error:  # noqa: BLE001 - report and skip a bad draft
            print(f"  skipped {field}: {error}")
            continue
        data["fields"][field] = entry
        added += 1
    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return added


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schemes", nargs="*", help="Scheme IDs to stage.")
    parser.add_argument("--all", action="store_true", help="Stage every gold scheme.")
    parser.add_argument("--draft-missing", action="store_true",
                        help="Paid: have a model draft catalog entries for fields not in the catalog.")
    args = parser.parse_args()
    gold = gold_schemes()
    schemes = sorted(gold) if args.all else (args.schemes or [])
    if not schemes:
        parser.error("give --schemes ... or --all")
    unknown = [s for s in schemes if s not in gold]
    if unknown:
        parser.error(f"not gold schemes: {unknown}")

    passages = load_passages()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["fields"]
    registry_ids = {d.fact_id for d in FactRegistry.model_validate_json(REGISTRY.read_bytes()).definitions}

    if args.draft_missing:
        missing = set()
        for s in schemes:
            for rule in DraftRuleSet.model_validate(json.loads(gold[s].read_text(encoding="utf-8"))).rules:
                if rule.field not in catalog:
                    missing.add(rule.field)
        print(f"drafted {draft_missing_fields(missing)} of {len(missing)} missing catalog fields")
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["fields"]

    summary = {}
    for s in schemes:
        result = stage_scheme(s, gold[s], passages.get(s, []), catalog, registry_ids)["status"]
        summary[s] = result
        if result.get("already_in_app"):
            print(f"LIVE    {s}: already in the app, skipped")
            continue
        mark = "READY  " if result["ready_for_review"] else "BLOCKED"
        print(f"{mark} {s}: {result['package_rules']}/{result['gold_rules']} rules, "
              f"new facts {len(result['new_facts'])}" + ("" if result["ready_for_review"] else f" | {len(result['blockers'])} blocker(s)"))
        for b in result["blockers"][:4]:
            print(f"        - {b}")
    STAGING.mkdir(parents=True, exist_ok=True)
    (STAGING / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ready = sum(v["ready_for_review"] for v in summary.values())
    print(f"\n{ready} ready for human review, {len(summary) - ready} blocked. Output: {STAGING}")


if __name__ == "__main__":
    main()
