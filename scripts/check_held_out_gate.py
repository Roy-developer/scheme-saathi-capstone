"""Check every gate before a held-out run is allowed. This script never runs the run.

Required approver: R5 (custodian) only, as decided by the project lead.

It reads only the freeze manifest, the threshold sign-off table and the manifest
hash of the held-out file. It does not open held-out case content.

A lead may override the SIGN-OFF gates with a logged reason. The override never
skips the held-out file integrity check, and it never runs anything.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FREEZE_MANIFEST = PROJECT_ROOT / "eval" / "freeze" / "manifest.json"
THRESHOLDS = PROJECT_ROOT / "eval" / "THRESHOLD_DECISIONS.md"
HELD_OUT_MANIFEST = PROJECT_ROOT / "eval" / "held_out" / "manifest.json"
OVERRIDE_LOG = PROJECT_ROOT / "eval" / "freeze" / "gate_overrides.log"
# Decided by the project lead: the custodian (R5) is the only required approver
# for a held-out run. Other owners' sign-offs are recorded but not required.
REQUIRED_ROLES = ()
SIGNOFF_PREFIXES = ("has not signed", "freeze is not approved", "no paid budget cap")


def threshold_table_text() -> str:
    """Read the threshold file as text only."""

    return THRESHOLDS.read_text(encoding="utf-8") if THRESHOLDS.exists() else ""


CUSTODIAN_LOGIN = "balajikondalrayal"
THRESHOLD_PR = 37


def custodian_approved() -> bool:
    """True when the custodian has an APPROVED review on the threshold PR.

    The approval is the custodian's own GitHub action. The script only reads it.
    If GitHub cannot be reached, this returns False, so the gate fails closed.
    """

    import subprocess

    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(THRESHOLD_PR), "--json", "reviews"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    reviews = json.loads(result.stdout or "{}").get("reviews", [])
    return any(
        r.get("author", {}).get("login") == CUSTODIAN_LOGIN and r.get("state") == "APPROVED"
        for r in reviews
    )


def gate_failures() -> list[str]:
    """Return every failed gate. An empty list means every gate passes."""

    failures: list[str] = []

    if not FREEZE_MANIFEST.exists():
        failures.append("freeze manifest is missing")
        approval = {}
    else:
        approval = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8")).get("approval", {})
    if approval.get("status") != "approved_by_project_lead":
        failures.append("freeze is not approved by the project lead")
    if not isinstance(approval.get("paid_budget_cap_usd"), (int, float)):
        failures.append("no paid budget cap recorded")

    rows: dict[str, list[str]] = {}
    for line in threshold_table_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0][:2] in REQUIRED_ROLES:
            rows[cells[0][:2]] = cells
    if not custodian_approved():
        failures.append("R5 (custodian) has not approved the threshold PR on GitHub")

    if not HELD_OUT_MANIFEST.exists():
        failures.append("held-out manifest is missing")
    else:
        held = json.loads(HELD_OUT_MANIFEST.read_text(encoding="utf-8"))
        local_file = PROJECT_ROOT / held.get("file", "")
        if not local_file.exists():
            failures.append("held-out case file is not present locally")
        elif hashlib.sha256(local_file.read_bytes()).hexdigest() != held.get("sha256"):
            failures.append("held-out case file does not match the manifest hash")

    return failures


def write_override_log(reason: str, failures: list[str]) -> None:
    """Append one audited entry per override: when, why, and which gates were skipped."""

    OVERRIDE_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "overridden_by": "project lead (Roy-developer)",
        "reason": reason,
        "skipped_gates": failures,
    }
    with OVERRIDE_LOG.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Print gate status. A lead may override sign-off gates with a logged reason."""

    args = list(sys.argv[1:] if argv is None else argv)
    lead_override: str | None = None
    if "--lead-override" in args:
        index = args.index("--lead-override")
        lead_override = args[index + 1] if index + 1 < len(args) else ""
        if not lead_override.strip():
            print('A reason is required: --lead-override "<reason>"')
            return 2

    failures = gate_failures()
    if not failures:
        print("All gates pass. The held-out run may be requested. This check did not run it.")
        return 0

    integrity = [f for f in failures if not any(p in f for p in SIGNOFF_PREFIXES)]
    if integrity:
        print("HELD-OUT RUN BLOCKED. Integrity gates cannot be overridden:")
        for item in integrity:
            print(f"  - {item}")
        return 1

    if lead_override is None:
        print("HELD-OUT RUN BLOCKED. Failed gates:")
        for item in failures:
            print(f"  - {item}")
        return 1

    write_override_log(lead_override.strip(), failures)
    print("LEAD OVERRIDE USED. Sign-off gates skipped and logged:")
    for item in failures:
        print(f"  - {item}")
    print(f"Reason recorded in {OVERRIDE_LOG.relative_to(PROJECT_ROOT)}.")
    print("Results from this run must be reported as NOT meeting the owner sign-off requirement.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
