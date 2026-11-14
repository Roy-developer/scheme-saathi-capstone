"""The committed freeze manifest matches its generator and names no held-out data."""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "eval" / "freeze" / "manifest.json"


def test_committed_freeze_manifest_matches_the_generator() -> None:
    """A changed prompt, rule package or attack suite must be re-pinned explicitly."""

    result = subprocess.run(
        [sys.executable, "scripts/build_freeze_manifest.py", "--check"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_freeze_manifest_references_no_held_out_path() -> None:
    """Held-out case payloads must never be pinned as freeze eval inputs.

    Status notes may mention held-out being blocked; forbid local custody
    persona/case file paths and unprotected held-out dataset pins.
    """

    text = MANIFEST.read_text(encoding="utf-8").lower()
    forbidden = (
        "eval/held_out/local",
        "held_out/personas",
        "personas_held_out",
        "heldout/personas",
    )
    for needle in forbidden:
        assert needle not in text, needle
