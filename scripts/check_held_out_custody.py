"""Fail CI if protected held-out persona files are tracked in the repository."""

from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTECTED_PATH = "eval/held_out/local"
DOCKER_PROTECTED_PATHS = ("eval", "data/heldout")


def docker_context_errors(project_root: Path) -> list[str]:
    """Require every Docker build context to exclude evaluation fixtures."""

    ignore_files = [project_root / ".dockerignore"]
    ignore_files.extend(sorted(project_root.glob("Dockerfile*.dockerignore")))
    errors: list[str] = []
    for ignore_file in ignore_files:
        if not ignore_file.is_file():
            errors.append(f"Missing Docker ignore file: {ignore_file.name}")
            continue
        patterns = {
            line.strip().replace("\\", "/").strip("/")
            for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for protected in DOCKER_PROTECTED_PATHS:
            if protected not in patterns:
                errors.append(
                    f"{ignore_file.name} must exclude {protected!r}."
                )
    return errors


def main() -> int:
    errors = docker_context_errors(PROJECT_ROOT)
    if errors:
        print("Docker build-context custody check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    result = subprocess.run(
        ["git", "ls-files", "--", PROTECTED_PATH],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = [path for path in result.stdout.splitlines() if path]
    if tracked:
        print(
            "Protected held-out files must not be tracked: "
            + ", ".join(tracked)
        )
        return 1
    print("No protected held-out persona files are tracked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
