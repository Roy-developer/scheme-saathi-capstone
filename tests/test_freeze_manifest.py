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
    """Held-out cases must never be pinned or referenced by the freeze contract."""

    text = MANIFEST.read_text(encoding="utf-8").lower()
    assert "heldout" not in text
    assert "held_out" not in text
