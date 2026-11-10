"""Load and validate compatible fact registries and scheme rule bundles."""

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from src.rules.bundles import BundleRegistry, SchemeBundle
from src.rules.facts import FactRegistry
from src.rules.models import Rule, RulePackage


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build JSON objects while rejecting duplicate keys at every depth."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> tuple[object, bytes]:
    """Read strict UTF-8 JSON and retain exact bytes for content pinning."""

    raw = path.read_bytes()
    return json.loads(raw, object_pairs_hook=_unique_json_object), raw


def _digest(raw: bytes) -> str:
    """Return a lowercase content hash for an exact loaded file."""

    return hashlib.sha256(raw).hexdigest()


def _validate_rule(
    rule: Rule,
    registry: FactRegistry,
) -> None:
    """Check a rule's fact type, operator, and literal against its definition."""

    try:
        definition = registry.get(rule.field)
    except KeyError as error:
        raise ValueError(f"Rule references unregistered fact '{rule.field}'") from error
    if definition.value_type == "text":
        raise ValueError("Display-only text facts cannot be used in rules")
    if definition.derived_from and definition.derivation != "age_on_application_date":
        raise ValueError(f"Unsupported derivation for {rule.field}")
    if definition.value_type == "boolean":
        compatible = rule.operator == "eq" and type(rule.value) is bool
    elif definition.value_type == "choice":
        compatible = (
            rule.operator == "eq"
            and type(rule.value) is str
            and rule.value in definition.choices
        )
    elif definition.value_type == "date":
        compatible = False
        if rule.operator in {"eq", "gte", "lte"} and type(rule.value) is str:
            try:
                from datetime import date

                date.fromisoformat(rule.value)
                compatible = True
            except ValueError:
                compatible = False
    elif definition.value_type in {"integer", "decimal"}:
        compatible = (
            rule.operator in {"eq", "gte", "lte"}
            and type(rule.value) in (int, float)
        )
        if definition.value_type == "integer":
            compatible = compatible and type(rule.value) is int
        if definition.value_type == "decimal":
            compatible = compatible and (
                type(rule.value) in (int, float)
                and abs(float(rule.value)) != float("inf")
                and float(rule.value) == float(rule.value)
            )
        if compatible and definition.minimum is not None:
            compatible = rule.value >= definition.minimum
        if compatible and definition.maximum is not None:
            compatible = rule.value <= definition.maximum
        if compatible and rule.operator in {"gte", "lte"}:
            if definition.value_type == "integer":
                compatible = type(rule.value) is int
    else:
        compatible = False
    numeric_fact = definition.value_type in {"integer", "decimal"}
    if numeric_fact and definition.unit is not None:
        compatible = compatible and rule.unit == definition.unit
    elif rule.unit is not None:
        compatible = False
    if not compatible:
        raise ValueError(
            f"Unsupported operator or value for fact '{rule.field}'"
        )
    if rule.field == "age" and (
        definition.minimum is not None
        and type(rule.value) is int
        and rule.value < definition.minimum
    ):
        raise ValueError("Age rule is below the registered minimum")


def _validate_bundle(
    bundle: SchemeBundle,
    package: RulePackage,
    registry: FactRegistry,
    registry_hash: str,
) -> None:
    """Validate bundle references and compatibility before package activation."""

    if bundle.scheme_id != package.scheme_id:
        raise ValueError("Bundle scheme ID does not match its rule package")
    if bundle.package_version != package.package_version:
        raise ValueError(f"Incompatible package version for {package.scheme_id}")
    if bundle.registry_version != registry.registry_version:
        raise ValueError(f"Incompatible fact registry for {package.scheme_id}")
    if bundle.registry_sha256 != registry_hash:
        raise ValueError(f"Fact registry hash mismatch for {package.scheme_id}")
    clause_ids = {rule.source_clause_id for rule in package.rules}
    if set(bundle.source_clause_ids) != clause_ids:
        raise ValueError(f"Source clause references mismatch for {package.scheme_id}")
    package_source = str(package.source.source_url)
    referenced = set(package.required_facts)
    for rule in package.rules:
        _validate_rule(rule, registry)
        definition = registry.get(rule.field)
        referenced.update(definition.derived_from or (rule.field,))
    if not referenced <= set(bundle.fact_ids):
        raise ValueError(f"Bundle omits referenced facts for {package.scheme_id}")
    for fact_id in bundle.fact_ids:
        definition = registry.get(fact_id)
        if (
            fact_id in package.required_facts
            and package_source not in {str(url) for url in definition.source_refs}
        ):
            raise ValueError(
                f"Fact source references do not include package source: {fact_id}"
            )


class RulePackageProvider:
    """Load immutable packages only after registry and bundle checks pass."""

    def __init__(
        self,
        package_dir: Path | None = None,
        *,
        allow_development: bool = False,
    ) -> None:
        """Read all package files and validate their pinned dependencies.

        Args:
            package_dir: Folder of rule JSON files. Registry and bundle
                manifests are read from its parent folder.
            allow_development: Permit explicitly development-only bundles.
                Production callers should leave this false.

        Raises:
            ValueError or ValidationError: A package, registry, reference, or
                content hash is malformed or incompatible.
        """

        root = (
            Path(package_dir)
            if package_dir is not None
            else Path(__file__).parent / "packages"
        )
        package_files = sorted(root.glob("*.json"), key=lambda item: item.name)
        if not package_files:
            raise ValueError("No scheme rule packages were found")

        package_data: dict[str, tuple[RulePackage, bytes]] = {}
        packages_by_scheme: dict[str, RulePackage] = {}
        for package_file in package_files:
            raw_package, raw_bytes = _read_json(package_file)
            package = RulePackage.model_validate(raw_package)
            if package.scheme_id in packages_by_scheme:
                raise ValueError(
                    f"Duplicate rule package for scheme: {package.scheme_id}"
                )
            package_data[package_file.name] = (package, raw_bytes)
            packages_by_scheme[package.scheme_id] = package

        registry_path = root.parent / "fact_registry.json"
        bundle_path = root.parent / "bundle_registry.json"
        raw_registry, registry_bytes = _read_json(registry_path)
        registry = FactRegistry.model_validate(raw_registry)
        raw_bundles, _ = _read_json(bundle_path)
        bundle_registry = BundleRegistry.model_validate(raw_bundles)
        bundles_by_scheme = {bundle.scheme_id: bundle for bundle in bundle_registry.bundles}
        if set(bundles_by_scheme) != set(packages_by_scheme):
            raise ValueError("Every rule package must have exactly one bundle")

        for bundle in bundle_registry.bundles:
            entry = package_data.get(bundle.package_file)
            if entry is None:
                raise ValueError(
                    f"Bundle package file is missing: {bundle.package_file}"
                )
            package, raw_bytes = entry
            if _digest(raw_bytes) != bundle.package_sha256:
                raise ValueError(f"Rule package hash mismatch for {package.scheme_id}")
            _validate_bundle(
                bundle,
                package,
                registry,
                _digest(registry_bytes),
            )
        if not allow_development and any(
            bundle.activation_state == "development_only"
            for bundle in bundle_registry.bundles
        ):
            raise ValueError("Development-only bundles cannot be activated")
        self._packages = packages_by_scheme
        self._bundles = bundles_by_scheme
        self._registry = registry

    @property
    def packages(self) -> Mapping[str, RulePackage]:
        """Return the read-only validated packages keyed by scheme ID."""

        return MappingProxyType(self._packages)

    @property
    def bundles(self) -> Mapping[str, SchemeBundle]:
        """Return the read-only validated bundle manifests."""

        return MappingProxyType(self._bundles)

    @property
    def registry(self) -> FactRegistry:
        """Return the fact registry that was pinned by every active bundle."""

        return self._registry

    def get(self, scheme_id: str) -> RulePackage:
        """Get a package by scheme ID or raise ``KeyError``."""

        return self._packages[scheme_id]

    def get_bundle(self, scheme_id: str) -> SchemeBundle:
        """Get the validated bundle for a scheme ID or raise ``KeyError``."""

        return self._bundles[scheme_id]
