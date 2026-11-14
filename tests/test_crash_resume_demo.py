import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_journey_survives_hard_process_crash_and_resumes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "demo_crash_resume.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
