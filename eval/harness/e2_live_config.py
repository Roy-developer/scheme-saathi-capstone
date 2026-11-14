"""Free-route settings for the E2 live-model run (development only).

Reads OPENROUTER_API_KEY_FREE and OPENROUTER_CHAT_MODEL_FREE from the
environment or the project .env file. Never prints the key.
The default OPENROUTER_CHAT_MODEL in .env and in code is not changed.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_VAR = "OPENROUTER_API_KEY_FREE"
MODEL_VAR = "OPENROUTER_CHAT_MODEL_FREE"


def _dotenv_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def free_route_settings(env_file: Path | None = None) -> tuple[str, str]:
    """Return (api_key, model) for the free route, or raise if either is missing."""
    file_values = _dotenv_values(env_file or ROOT / ".env")
    # The project .env is the agreed source; a shell variable with the same
    # name is ignored for this run (it has been seen holding a 6-character value).
    api_key = file_values.get(KEY_VAR) or os.environ.get(KEY_VAR, "")
    model = file_values.get(MODEL_VAR) or os.environ.get(MODEL_VAR, "")
    if not api_key:
        raise RuntimeError(f"{KEY_VAR} is not set (environment or .env).")
    if not model:
        raise RuntimeError(f"{MODEL_VAR} is not set (environment or .env).")
    return api_key, model
