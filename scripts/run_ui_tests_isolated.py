"""Run each UI integration test in its own pytest process with its own portal port.

The module-scoped UI fixture and one scholarship test each start an API lifespan,
and two lifespans in one process collide on the mock portal port. Running each
test in a separate process avoids that. Each process gets a loopback port that
was free when it was picked (bind to port 0 by the OS).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_FILES = ("tests/test_ui_app.py", "tests/test_ui_integration.py")


def free_loopback_url() -> str:
    """Return a loopback portal URL on a port that is free right now."""

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def collect_node_ids(test_file: str) -> list[str]:
    """List pytest node IDs for one file without running the tests."""

    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "--collect-only", "-q"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if "::" in line]


def main() -> int:
    """Run every collected UI test in its own process and report failures."""

    failures: list[str] = []
    for test_file in TEST_FILES:
        for node_id in collect_node_ids(test_file):
            environment = dict(os.environ)
            environment["SCHEME_SAATHI_PORTAL_URL"] = free_loopback_url()
            environment["SCHEME_SAATHI_DISABLE_CROSS_ENCODER"] = "1"
            result = subprocess.run(
                [sys.executable, "-m", "pytest", node_id, "-q", "--tb=short"],
                cwd=PROJECT_ROOT, env=environment, check=False,
            )
            if result.returncode != 0:
                failures.append(node_id)
    if failures:
        print("FAILED in isolation:")
        for node_id in failures:
            print(f"  {node_id}")
        return 1
    print("All UI tests passed when each ran in its own process.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
