"""Build the team-override extraction case file from all live package clauses.

Writes gitignored:
  eval/held_out/extraction/local/cases_all_live_clauses_v1.json

Updates committed:
  eval/held_out/extraction/manifest.json  (IDs, sha256, n=13 override)

Claim boundary: this is NOT PDF unseen held-out. It is a team override to
evaluate every unique source_clause_id in src/rules/packages/ (currently 13).
Eleven of those IDs already appear in the development extraction file.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = PROJECT_ROOT / "src" / "rules" / "packages"
DEV_CASES = PROJECT_ROOT / "data" / "schemes" / "rule_extraction_cases_dev.json"
LOCAL_DIR = PROJECT_ROOT / "eval" / "held_out" / "extraction" / "local"
LOCAL_FILE = LOCAL_DIR / "cases_all_live_clauses_v1.json"
MANIFEST = PROJECT_ROOT / "eval" / "held_out" / "extraction" / "manifest.json"

# topic_tags for clauses not listed in the development case file
EXTRA_TAGS = {
    "APY-IN-ELIGIBILITY-01": ["inclusion_clause"],
    "APY-IN-EXCLUSION-01": ["exclusion_clause"],
}


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def main() -> int:
    dev = json.loads(DEV_CASES.read_text(encoding="utf-8"))
    by_clause = {c["clause_id"]: c for c in dev["cases"]}

    clauses: dict[str, dict] = {}
    for path in sorted(PACKAGE_DIR.glob("*.json")):
        raw = path.read_bytes()
        digest = _sha256_bytes(raw)
        package = json.loads(raw)
        for rule in package["rules"]:
            clause_id = rule["source_clause_id"]
            if clause_id in clauses:
                continue
            if clause_id in by_clause:
                entry = dict(by_clause[clause_id])
            else:
                entry = {
                    "package": path.name,
                    "clause_id": clause_id,
                    "context": [],
                    "topic_tags": EXTRA_TAGS[clause_id],
                }
            entry["package"] = path.name
            entry["package_sha256"] = digest
            entry["split"] = "team_override"
            entry["claim_note"] = (
                "team_override_all_live_clauses; not PDF unseen held-out"
            )
            clauses[clause_id] = entry

    cases = [clauses[cid] for cid in sorted(clauses)]
    payload = {
        "dataset_version": "team_override_all_live_v1",
        "purpose": (
            "Team override: every unique source_clause_id from live packages. "
            "Not an unseen PDF held-out set. Gold rules come from approved packages."
        ),
        "split_rules": (
            "team_override: measured only for the reduced-bar before/after; "
            "never used as learn. Not PDF held-out."
        ),
        "context_rules": dev["context_rules"],
        "topic_tags": dev["topic_tags"],
        "reviewer_rules": dev["reviewer_rules"],
        "authorized_reviewers": dev["authorized_reviewers"],
        "contexts": dev["contexts"],
        "cases": cases,
    }

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    LOCAL_FILE.write_text(text, encoding="utf-8")
    digest = _sha256_file(LOCAL_FILE)

    already_in_dev = sorted(cid for cid in clauses if cid in by_clause)
    only_here = sorted(cid for cid in clauses if cid not in by_clause)

    manifest = {
        "purpose": (
            "Team override: all live package clauses (n=13). "
            "Not PDF ≥40 unseen held-out."
        ),
        "status": "ready_for_evaluate",
        "bar": "team_override_all_live_clauses",
        "protected": True,
        "split": "team_override",
        "case_count": len(cases),
        "target_case_count": len(cases),
        "local_file": "eval/held_out/extraction/local/cases_all_live_clauses_v1.json",
        "sha256": digest,
        "cases": [{"id": c["clause_id"], "package": c["package"]} for c in cases],
        "overlap_with_development_extraction": {
            "already_in_dev_case_file": already_in_dev,
            "new_vs_dev_case_file": only_here,
            "note": (
                "Most clause IDs were already used in development learn/check. "
                "Do not claim PDF unseen held-out."
            ),
        },
        "dual_labels": {
            "required": False,
            "status": "waived_package_gold_is_authority",
            "note": (
                "Team override: expected rules are the approved package rules "
                "(Role 1 package approval), not a new dual-label pass."
            ),
            "labelers": [],
        },
        "live_package_clause_capacity": {
            "unique_source_clause_ids": len(cases),
            "note": "Override target equals live unique clause count.",
        },
        "blocker": None,
        "playbook_for_after_arm": "1.1.0",
        "updated_on": "2026-11-13",
        "override": {
            "replaces": "PDF-shaped ≥40 unseen extraction cases",
            "decided": "team override to use all 13 live clauses",
            "claim_level": "team_override_all_live_clauses; not PDF held-out",
        },
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"wrote {LOCAL_FILE} ({len(cases)} cases, sha256={digest})")
    print(f"wrote {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
