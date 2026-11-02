"""Load and validate the version-controlled scheme rule registry."""

import json
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from src.rules.models import RulePackage


class RulePackageProvider:
    """Load immutable rule packages once from the packaged or supplied folder."""

    def __init__(self, package_dir: Path | None = None) -> None:
        """Read, validate and index every ``*.json`` rule package.

        Args:
            package_dir: Folder to read. Tests pass a temporary folder;
                the app uses the installed ``src/rules/packages`` folder.

        Raises:
            ValueError or ValidationError if any file is invalid, so a broken
            rule file stops the app at startup instead of giving a wrong
            verdict later.
        """

        # importlib.resources finds the folder even when installed as a package.
        root = (
            package_dir
            if package_dir is not None
            else resources.files("src.rules").joinpath("packages")
        )
        packages: dict[str, RulePackage] = {}
        # Sort by name so the loading order is the same on every machine.
        package_files = sorted(
            (entry for entry in root.iterdir() if entry.name.endswith(".json")),
            key=lambda entry: entry.name,
        )
        if not package_files:
            raise ValueError("No scheme rule packages were found")

        for package_file in package_files:
            # model_validate runs every RulePackage and Rule check.
            package = RulePackage.model_validate(
                json.loads(package_file.read_text(encoding="utf-8"))
            )
            # One scheme must have exactly one active package.
            if package.scheme_id in packages:
                raise ValueError(
                    f"Duplicate rule package for scheme: {package.scheme_id}"
                )
            packages[package.scheme_id] = package
        self._packages = packages

    @property
    def packages(self) -> Mapping[str, RulePackage]:
        """Return the read-only validated registry keyed by scheme ID.

        MappingProxyType stops callers from adding or removing packages.
        """

        return MappingProxyType(self._packages)

    def get(self, scheme_id: str) -> RulePackage:
        """Get a package by scheme ID or raise KeyError."""

        return self._packages[scheme_id]
