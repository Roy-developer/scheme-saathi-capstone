"""Gate + runner for the team-override all-live-clauses extraction evaluate.

Default bar (team override): all unique live package clauses (n=13), gold =
approved packages. This is NOT a PDF unseen held-out claim.

Fails closed until the local case file matches the committed manifest hash.
With ``--yes``, invokes ``scheme_rules evaluate`` on that file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "eval" / "held_out" / "extraction" / "manifest.json"
STATUS_DOC = PROJECT_ROOT / "docs" / "e3_pdf_path_status_2026-11-13.md"
READY_STATUSES = frozenset({
    "ready_for_evaluate",
    "labels_complete",
    "team_override_ready",
})
GO_AHEAD_PHRASE = "Team-override all-live-clauses evaluate is **authorised**"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_failures(*, require_go_ahead: bool) -> list[str]:
    failures: list[str] = []
    if not MANIFEST.is_file():
        return ["missing eval/held_out/extraction/manifest.json"]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    status = manifest.get("status")
    if status not in READY_STATUSES:
        failures.append(
            f"manifest status is {status!r}; need one of {sorted(READY_STATUSES)}"
        )
    target = int(manifest.get("target_case_count") or 0)
    count = int(manifest.get("case_count") or 0)
    if count < target or count <= 0:
        failures.append(f"case_count {count} < target {target}")
    local_rel = manifest.get("local_file")
    local = PROJECT_ROOT / local_rel if local_rel else None
    if local is None or not local.is_file():
        failures.append(f"missing protected local file {local_rel!r}")
    elif manifest.get("sha256") and _sha256(local) != manifest["sha256"]:
        failures.append("local case file sha256 does not match manifest")
    labels = manifest.get("dual_labels") or {}
    label_ok = labels.get("status") in {
        "complete",
        "waived_package_gold_is_authority",
    }
    if not label_ok:
        failures.append(f"dual_labels.status is {labels.get('status')!r}")
    if require_go_ahead:
        text = STATUS_DOC.read_text(encoding="utf-8") if STATUS_DOC.is_file() else ""
        if GO_AHEAD_PHRASE not in text:
            failures.append(
                f"no go-ahead phrase in docs/e3_pdf_path_status_2026-11-13.md "
                f"(expected: {GO_AHEAD_PHRASE!r})"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Only print gate status.")
    parser.add_argument("--before", action="store_true", help="Evaluate with no playbook.")
    parser.add_argument("--after", action="store_true", help="Evaluate with playbook.")
    parser.add_argument("--playbook", default="1.1.2")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--yes", action="store_true", help="Send model calls.")
    args = parser.parse_args(argv)

    require_go_ahead = bool(args.yes) or (not args.dry_run and (args.before or args.after))
    if args.dry_run and not args.yes:
        require_go_ahead = False

    failures = gate_failures(require_go_ahead=require_go_ahead)
    if failures:
        print("all-live-clauses extraction evaluate blocked:")
        for item in failures:
            print(f"- {item}")
        print(
            "Rebuild with: python scripts/build_extraction_all_live_clauses.py\n"
            "See docs/e3_pdf_path_status_2026-11-13.md"
        )
        return 2

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cases_path = PROJECT_ROOT / manifest["local_file"]
    print(
        f"gate open: {manifest['case_count']} cases, "
        f"bar={manifest.get('bar')}, claim={manifest.get('override', {}).get('claim_level')}"
    )

    if args.dry_run and not (args.before or args.after):
        return 0

    if not (args.before or args.after):
        print("Pass --before and/or --after (with --yes) to run evaluate.")
        return 0

    if args.before and args.after:
        print("Run --before and --after as separate invocations.", file=sys.stderr)
        return 2

    cmd = [
        sys.executable,
        "-m",
        "src.rule_extraction_reflexion.scheme_rules",
        "evaluate",
        "--cases",
        str(cases_path),
        "--split",
        "team_override",
        "--runs",
        str(args.runs),
    ]
    if args.after:
        cmd.extend(["--playbook", args.playbook])
    if args.yes:
        cmd.append("--yes")

    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
