"""Start and stop the private local HTTP process used by the mock portal MCP."""

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from src.config import (
    PORTAL_HEALTH_PROOF_MESSAGE,
    PORTAL_URL,
    PROJECT_ROOT,
    portal_host_port,
    test_rule_package_directory,
)


# Python/FastAPI imports can exceed ten seconds during a cold, resource-bound start.
PORTAL_STARTUP_TIMEOUT_SECONDS = 60
PORTAL_STARTUP_POLL_SECONDS = 0.1


def start_portal_service(database_path: Path) -> subprocess.Popen[bytes]:
    """Start the independent portal API and wait until its health route responds."""

    host, port = portal_host_port()
    startup_token = secrets.token_urlsafe(32)
    expected_proof = hmac.new(
        startup_token.encode("utf-8"),
        PORTAL_HEALTH_PROOF_MESSAGE,
        hashlib.sha256,
    ).hexdigest()
    environment = {
        "SCHEME_SAATHI_DISABLE_DOTENV": "1",
        "SCHEME_SAATHI_PORTAL_DB": str(database_path),
        "SCHEME_SAATHI_PORTAL_HEALTH_TOKEN": startup_token,
        "SCHEME_SAATHI_PORTAL_URL": PORTAL_URL,
        "PYTHONPATH": os.pathsep.join(sys.path),
    }
    for name in ("PATH", "SYSTEMROOT", "WINDIR"):
        if value := os.getenv(name):
            environment[name] = value
    if test_packages := test_rule_package_directory():
        environment["SCHEME_SAATHI_TEST_RULE_PACKAGE_DIR"] = str(test_packages)
        environment["PYTEST_CURRENT_TEST"] = os.environ["PYTEST_CURRENT_TEST"]
    # Keep the child's output in a temp log so a startup failure shows its cause.
    log_descriptor, log_name = tempfile.mkstemp(prefix="portal-startup-", suffix=".log")
    with os.fdopen(log_descriptor, "w", encoding="utf-8", errors="replace") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.portal.app:app",
                "--host",
                host,
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    deadline = time.monotonic() + PORTAL_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            with open(log_name, encoding="utf-8", errors="replace") as captured:
                tail = captured.read()[-2000:]
            raise RuntimeError(
                "The mock portal service exited during startup.\n" + tail
            )
        try:
            health_request = urllib.request.Request(
                f"{PORTAL_URL}/health",
                headers={"X-Scheme-Saathi-Startup-Token": startup_token},
            )
            with urllib.request.urlopen(health_request, timeout=1) as response:
                if response.status == 200:
                    try:
                        body = json.loads(response.read().decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        body = {}
                    proof = body.get("proof") if isinstance(body, dict) else None
                    if isinstance(proof, str) and hmac.compare_digest(
                        proof, expected_proof
                    ):
                        return process
        except (urllib.error.URLError, TimeoutError):
            time.sleep(PORTAL_STARTUP_POLL_SECONDS)
    process.terminate()
    process.wait(timeout=5)
    raise RuntimeError("The mock portal service did not become ready.")


def stop_portal_service(process: subprocess.Popen[bytes]) -> None:
    """Stop the private portal child process and reap it."""

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
