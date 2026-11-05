"""Load local project configuration before application modules read it."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PORTAL_URL = os.getenv(
    "SCHEME_SAATHI_PORTAL_URL", "http://127.0.0.1:8765"
).rstrip("/")
PORTAL_HEALTH_PROOF_MESSAGE = b"scheme-saathi-portal-health-v1"


def portal_host_port() -> tuple[str, int]:
    """Return the host and port used to start the local HTTP portal service."""

    address = urlsplit(PORTAL_URL)
    if (
        address.scheme != "http"
        or address.hostname not in {"127.0.0.1", "localhost"}
        or address.port is None
    ):
        raise ValueError(
            "SCHEME_SAATHI_PORTAL_URL must use localhost and an explicit port."
        )
    return address.hostname, address.port


def portal_database_path() -> Path:
    """Return the portal DB path, honoring the legacy test/config variable."""

    configured_path = os.getenv("SCHEME_SAATHI_PORTAL_DB") or os.getenv(
        "SCHEME_SAATHI_APPLICATION_DB"
    )
    if configured_path is not None:
        path = Path(configured_path)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return PROJECT_ROOT / "data" / "runtime" / "portal.sqlite3"


def test_rule_package_directory() -> Path | None:
    """Return an explicitly injected development package directory only in pytest."""

    configured = os.getenv("SCHEME_SAATHI_TEST_RULE_PACKAGE_DIR")
    if configured is None:
        return None
    if "PYTEST_CURRENT_TEST" not in os.environ:
        raise ValueError("Test rule-package injection is available only under pytest.")
    path = Path(configured).resolve()
    fixtures = (PROJECT_ROOT / "tests" / "fixtures").resolve()
    if fixtures not in path.parents:
        raise ValueError("Test rule-package data must live under tests/fixtures.")
    return path


def test_scheme_data_directory() -> Path | None:
    """Return isolated synthetic documents paired with explicit test bundles."""

    package_directory = test_rule_package_directory()
    return package_directory.parent / "schemes" if package_directory else None


def load_project_dotenv() -> None:
    """Load local secrets unless this process is an isolated tool child."""

    if os.getenv("SCHEME_SAATHI_DISABLE_DOTENV") != "1":
        load_dotenv(PROJECT_ROOT / ".env", override=True)


def openrouter_chat_settings(default_model: str) -> tuple[str | None, str]:
    """Return the standard chat key and model after project config is loaded."""

    return (
        os.getenv("OPENROUTER_API_KEY"),
        os.getenv("OPENROUTER_CHAT_MODEL", default_model),
    )


load_project_dotenv()
