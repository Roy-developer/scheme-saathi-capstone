"""Strict metadata contracts for compatible, version-pinned scheme bundles."""

import hashlib
import json
import re
from typing import Literal

from pydantic import Field, model_validator

from src.rules.facts import FactRegistry, StrictDataModel, TypedFactStore


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SCHEME_ID = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")


class SchemeBundle(StrictDataModel):
    """Exact references needed to activate one rules/facts version together."""

    scheme_id: str = Field(min_length=1, max_length=80)
    bundle_version: str = Field(min_length=1, max_length=40)
    # legacy_compatibility: the two original pilots, pinned in code.
    # development_only: test bundles; refused by the live loader.
    # approved: a live scheme, checked for consistency but not pinned in code.
    activation_state: Literal["legacy_compatibility", "development_only", "approved"]
    package_file: str = Field(min_length=1, max_length=120)
    package_version: str = Field(min_length=1, max_length=40)
    package_sha256: str
    registry_version: str = Field(min_length=1, max_length=40)
    registry_sha256: str
    fact_ids: tuple[str, ...] = Field(min_length=1)
    legacy_profile_mapping: dict[str, str] = Field(default_factory=dict)
    source_clause_ids: tuple[str, ...] = Field(min_length=1)
    checklist_version: str | None = None
    mock_form_version: str | None = None

    @model_validator(mode="after")
    def validate_references(self) -> "SchemeBundle":
        """Reject ambiguous IDs, file paths, and malformed content hashes."""

        if not _SCHEME_ID.fullmatch(self.scheme_id):
            raise ValueError(f"Invalid scheme ID: {self.scheme_id}")
        for version in (
            self.bundle_version,
            self.package_version,
            self.registry_version,
        ):
            if not _VERSION.fullmatch(version):
                raise ValueError("Bundle references must use numeric semver")
        for version in (self.checklist_version, self.mock_form_version):
            if version is not None and not _VERSION.fullmatch(version):
                raise ValueError("Checklist and form versions must use numeric semver")
        if self.package_file != self.package_file.rsplit("\\", 1)[-1]:
            raise ValueError("Bundle package_file must be a filename")
        if self.package_file != self.package_file.rsplit("/", 1)[-1]:
            raise ValueError("Bundle package_file must be a filename")
        if not _SHA256.fullmatch(self.package_sha256):
            raise ValueError("Invalid rule-package SHA-256")
        if not _SHA256.fullmatch(self.registry_sha256):
            raise ValueError("Invalid fact-registry SHA-256")
        if len(self.fact_ids) != len(set(self.fact_ids)):
            raise ValueError("Bundle fact IDs must be unique")
        if len(self.source_clause_ids) != len(set(self.source_clause_ids)):
            raise ValueError("Bundle source clause IDs must be unique")
        if len(set(self.legacy_profile_mapping.values())) != len(
            self.legacy_profile_mapping
        ):
            raise ValueError("Legacy profile mappings must be unambiguous")
        return self


class BundleRegistry(StrictDataModel):
    """Versioned set of bundle manifests activated with one fact registry."""

    schema_version: Literal["1.0"]
    bundles: tuple[SchemeBundle, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_schemes(self) -> "BundleRegistry":
        """Require one bundle per active scheme ID."""

        scheme_ids = [bundle.scheme_id for bundle in self.bundles]
        if len(scheme_ids) != len(set(scheme_ids)):
            raise ValueError("Duplicate scheme bundle")
        return self


def bundle_fingerprint(bundle: SchemeBundle) -> str:
    """Hash the exact pinned rule, registry, and bundle dependency record."""

    encoded = json.dumps(
        bundle.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def document_fact_allowlist(
    scheme_id: str,
    registry: FactRegistry,
    bundle: SchemeBundle | None = None,
) -> frozenset[str]:
    """Resolve scheme-scoped facts from a validated active bundle, not global IDs.

    Args:
        scheme_id: Scheme whose document data is being validated.
        registry: Registry used to interpret field and condition values.
        bundle: Trusted provider bundle, or an explicitly injected development fixture.
    """

    active_registry = None
    if bundle is None:
        from src.mcp_servers.rule_data import get_active_rule_data

        try:
            provider = get_active_rule_data()
            bundle = provider.get_bundle(scheme_id)
            active_registry = provider.registry
        except KeyError as error:
            raise ValueError("Documents require an active scheme bundle.") from error
    if bundle.scheme_id != scheme_id or bundle.registry_version != registry.registry_version:
        raise ValueError("Documents use an incompatible scheme bundle or registry.")
    for fact_id in bundle.fact_ids:
        try:
            definition = registry.get(fact_id)
        except KeyError as error:
            raise ValueError("Documents use an incompatible scheme fact registry.") from error
        if active_registry is not None and definition != active_registry.get(fact_id):
            raise ValueError("Documents use an incompatible scheme fact definition.")
        if set(definition.derived_from) - set(bundle.fact_ids):
            raise ValueError("Derived document fact dependencies are outside its scheme bundle.")
    return frozenset(bundle.fact_ids)


def document_fact_values(
    scheme_id: str,
    registry: FactRegistry,
    store: TypedFactStore,
    bundle: SchemeBundle | None = None,
) -> dict[str, object | None]:
    """Resolve only authorized raw and derived document facts from a trusted store.

    Args:
        scheme_id: Scheme whose document values are being populated.
        registry: Validated definitions used by the store.
        store: Confirmed typed inputs; derived inputs cannot be supplied directly.
        bundle: Trusted active bundle or explicitly injected development fixture.
    """

    allowed = document_fact_allowlist(scheme_id, registry, bundle)
    store.validate_against(registry)
    return {fact_id: store.value(fact_id, registry) for fact_id in allowed}
