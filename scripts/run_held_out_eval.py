"""Held-out evaluation run step. Dry run by default. Never makes a paid call.

The run is refused unless every gate in check_held_out_gate.py passes. The dry
run prints only counts per scheme and per intended category, never case content.
The live rule-engine evaluation is not implemented yet; asking for --execute
says so and exits without running anything.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from check_held_out_gate import gate_failures  # noqa: E402

HELD_OUT_FILE = PROJECT_ROOT / "eval" / "held_out" / "local" / "personas_held_out_v2.json"


def main(argv: list[str] | None = None) -> int:
    """Refuse unless the gate passes. Summarise counts only."""

    args = list(sys.argv[1:] if argv is None else argv)
    failures = gate_failures()
    if failures:
        print("HELD-OUT RUN REFUSED. Gates failed:")
        for item in failures:
            print(f"  - {item}")
        return 1

    cases = json.loads(HELD_OUT_FILE.read_text(encoding="utf-8"))["cases"]
    by_scheme = Counter(c["scheme_id"] for c in cases)
    by_intent = Counter(c["intended_category"] for c in cases)
    print(f"Gate passed. Held-out cases: {len(cases)}")
    print(f"  per scheme: {dict(by_scheme)}")
    print(f"  per intended category: {dict(by_intent)}")
    print("No paid calls are made by this step.")

    if "--execute" in args:
        print("LIVE RULE-ENGINE EVALUATION IS NOT IMPLEMENTED YET. Nothing was run.")
        return 2
    print("Dry run only. Add --execute once the live evaluation step is built.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
