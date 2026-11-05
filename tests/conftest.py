"""Keep integration startup offline and away from saved demonstration databases."""

import os
from pathlib import Path
from uuid import uuid4

import pytest


# This must precede application imports during collection, not just test setup.
os.environ["SCHEME_SAATHI_DISABLE_DOTENV"] = "1"
os.environ["SCHEME_SAATHI_DISABLE_CROSS_ENCODER"] = "1"
for credential in (
    "OPENROUTER_API_KEY", "OPENROUTER_API_KEY_FREE", "OPEN_ROUTER_FREE",
    "OPENROUTER_EMBEDDING_API_KEY",
):
    os.environ.pop(credential, None)

_DATABASES = [
    Path.cwd() / f".pytest-{name}-{uuid4().hex}.sqlite3"
    for name in ("journey", "portal")
]
os.environ["SCHEME_SAATHI_CHECKPOINT_DB"] = str(_DATABASES[0])
# Leave PORTAL_DB unset so individual tests can override APPLICATION_DB.
os.environ.pop("SCHEME_SAATHI_PORTAL_DB", None)
os.environ["SCHEME_SAATHI_APPLICATION_DB"] = str(_DATABASES[1])


@pytest.fixture(scope="session", autouse=True)
def remove_test_databases():
    """Remove only this run's project-local SQLite artifacts after child shutdown."""

    yield
    for database in _DATABASES:
        for suffix in ("", "-wal", "-shm"):
            database.with_name(database.name + suffix).unlink(missing_ok=True)
