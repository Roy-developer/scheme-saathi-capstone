"""Check every gate before a held-out run is allowed. This script never runs the run.

It reads only the freeze manifest, the threshold sign-off table and the manifest
hash of the held-out file. It does not open held-out case content. A passing
gate means the run may be requested; the paid run itself is a separate step.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FREEZE_MANIFEST = PROJECT_ROOT / "eval" / "freeze" / "manifest.json"
THRESHOLDS = PROJECT_ROOT / "eval" / "THRESHOLD_DECISIONS.md"
HELD_OUT_MANIFEST = PROJECT_ROOT / "eval" / "held_out" / "manifest.json"
REQUIRED_ROLES = ("R1", "R2", "R3", "R4", "R5", "R6")


def gate_failures() -> list[str]:
    """Return the reasons the gate fails. An empty list means every gate passes."""

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

    text = THRESHOLD_TABLE_TEXT()
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0][:2] in REQUIRED_ROLES:
            rows[cells[0][:2]] = cells
    for role in REQUIRED_ROLES:
        cells = rows.get(role)
        if not cells or not re.search(r"\d{4}-\d{2}-\d{2}", cells[2]) or not cells[3]:
            failures.append(f"{role} has not signed in the threshold table")

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


def THRESHOLD_TABLE_TEXT() -> str:
    """Read the threshold file as text only."""

    return THRESHOLDS.read_text(encoding="utf-8") if THRESHOLDS.exists() else ""


def main() -> int:
    """Print the gate status and return 0 only when every gate passes."""

    failures = gate_failures()
    if failures:
        print("HELD-OUT RUN BLOCKED. Failed gates:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("All gates pass. The held-out run may be requested. This check did not run it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
