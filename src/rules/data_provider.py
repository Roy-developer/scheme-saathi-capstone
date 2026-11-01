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
        root = (
            package_dir
            if package_dir is not None
            else resources.files("src.rules").joinpath("packages")
        )
        packages: dict[str, RulePackage] = {}
        package_files = sorted(
            (entry for entry in root.iterdir() if entry.name.endswith(".json")),
            key=lambda entry: entry.name,
        )
        if not package_files:
            raise ValueError("No scheme rule packages were found")

        for package_file in package_files:
            package = RulePackage.model_validate(
                json.loads(package_file.read_text(encoding="utf-8"))
            )
            if package.scheme_id in packages:
                raise ValueError(
                    f"Duplicate rule package for scheme: {package.scheme_id}"
                )
            packages[package.scheme_id] = package
        self._packages = packages

    @property
    def packages(self) -> Mapping[str, RulePackage]:
        """Return the read-only validated registry keyed by scheme ID."""

        return MappingProxyType(self._packages)

    def get(self, scheme_id: str) -> RulePackage:
        """Get a package by scheme ID or raise KeyError."""

        return self._packages[scheme_id]
