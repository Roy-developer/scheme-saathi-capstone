"""Load local project configuration before application modules read it."""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_dotenv() -> None:
    """Load local secrets unless this process is an isolated tool child."""

    if os.getenv("SCHEME_SAATHI_DISABLE_DOTENV") != "1":
        load_dotenv(PROJECT_ROOT / ".env", override=True)


load_project_dotenv()
