"""Validate data-defined fields for the synthetic application form."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from src.config import PROJECT_ROOT, test_scheme_data_directory
from src.documents.checklists import LocalizedText, StrictModel, _reject_duplicate_json_keys
from src.rules.facts import FactRegistry, TypedFactStore
from src.rules.bundles import SchemeBundle, document_fact_allowlist, document_fact_values


FORM_DIRECTORY = (
    (test_scheme_data_directory() or (PROJECT_ROOT / "data" / "schemes"))
    / "mock_forms"
)
FORM_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
FIELD_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
_SUPPORTED_TYPES = frozenset({"boolean", "date", "integer", "decimal", "choice", "text"})


class MockFormField(StrictModel):
    """One typed destination on the fixed synthetic application form."""

    field_id: str = Field(pattern=FIELD_ID_PATTERN)
    labels: LocalizedText
    value_type: Literal["boolean", "date", "integer", "decimal", "choice", "text"]
    required: bool
    fact_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,79}$")
    extra_input: bool = False
    choices: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    max_length: int | None = Field(default=None, ge=1, le=2000)

    @model_validator(mode="after")
    def validate_mapping_shape(self) -> "MockFormField":
        """Disallow unmapped values and unsupported field behavior."""

        if self.fact_id is not None and self.extra_input:
            raise ValueError("A field cannot be both fact-mapped and manually entered.")
        if self.fact_id is None and not self.extra_input:
            raise ValueError("Every form field needs a registered fact or explicit input.")
        if self.value_type == "choice":
            if not self.choices or len(self.choices) != len(set(self.choices)):
                raise ValueError("Choice form fields require unique allowed values.")
        elif self.choices:
            raise ValueError("Only choice fields may declare allowed values.")
        if self.value_type == "text":
            if self.max_length is None:
                raise ValueError("Text fields require an explicit maximum length.")
        elif self.max_length is not None:
            raise ValueError("Only text fields may declare a maximum length.")
        if self.value_type not in {"integer", "decimal"} and (
            self.minimum is not None or self.maximum is not None
        ):
            raise ValueError("Only numeric fields may declare bounds.")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("A form field minimum cannot exceed its maximum.")
        return self


class MockFormMapping(StrictModel):
    """Versioned mapping of confirmed facts to fixed, localized form fields."""

    schema_version: Literal[1]
    scheme_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,79}$")
    form_version: str = Field(pattern=FORM_VERSION_PATTERN)
    fields: tuple[MockFormField, ...] = Field(min_length=1, max_length=100)
    status: Literal["demo_only", "pending_review", "approved"]

    @model_validator(mode="after")
    def validate_unique_fields(self) -> "MockFormMapping":
        """Require one unambiguous entry for every fixed field."""

        identifiers = [field.field_id for field in self.fields]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Form field IDs must be unique.")
        return self

    def validate_registry(
        self, registry: FactRegistry, bundle: SchemeBundle | None = None,
    ) -> None:
        """Require fact mappings to preserve exact registered type and choices."""

        allowed_facts = document_fact_allowlist(self.scheme_id, registry, bundle)
        for field in self.fields:
            if field.fact_id is None:
                continue
            if field.fact_id not in allowed_facts:
                raise ValueError("Form mapping references a fact outside its scheme bundle.")
            definition = registry.get(field.fact_id)
            if definition.value_type != field.value_type:
                raise ValueError(f"Form field type conflicts with fact {field.fact_id}.")
            if field.value_type == "choice" and field.choices != definition.choices:
                raise ValueError(f"Form field choices conflict with fact {field.fact_id}.")
            if field.value_type in {"integer", "decimal"}:
                if (
                    definition.minimum is not None
                    and field.minimum is not None
                    and field.minimum < definition.minimum
                ) or (
                    definition.maximum is not None
                    and field.maximum is not None
                    and field.maximum > definition.maximum
                ):
                    raise ValueError(f"Form field bounds exceed fact {field.fact_id}.")


class MockFormSnapshot(StrictModel):
    """Validated mapping plus an exact-content dependency fingerprint."""

    scheme_id: str
    mapping: MockFormMapping | None
    fingerprint: str
    notice: str


def load_mock_form_snapshot(
    scheme_id: str,
    registry: FactRegistry,
    *,
    form_directory: Path | None = None,
    bundle: SchemeBundle | None = None,
) -> MockFormSnapshot:
    """Load one strict form mapping under the shared checklist publication lock."""

    form_directory = form_directory or (
        (test_scheme_data_directory() or (PROJECT_ROOT / "data" / "schemes"))
        / "mock_forms"
    )
    from src.documents.publication import checklist_publication_lock

    path = form_directory / f"{scheme_id}.json"
    with checklist_publication_lock(form_directory.parent / "document_checklists"):
        try:
            content = path.read_bytes()
            _reject_duplicate_json_keys(content)
            mapping = MockFormMapping.model_validate_json(content)
            if mapping.scheme_id != scheme_id:
                raise ValueError("Form mapping belongs to a different scheme.")
            mapping.validate_registry(registry, bundle)
        except (OSError, UnicodeDecodeError, ValueError, ValidationError):
            return MockFormSnapshot(
                scheme_id=scheme_id,
                mapping=None,
                fingerprint=hashlib.sha256(
                    content if "content" in locals() else b"<missing-form>"
                ).hexdigest(),
                notice="The synthetic application form is not configured safely.",
            )
        return MockFormSnapshot(
            scheme_id=scheme_id,
            mapping=mapping,
            fingerprint=hashlib.sha256(content).hexdigest(),
            notice=(
                "Synthetic form mapping only; this is not an official government form."
            ),
        )


def publish_mock_form_file(
    filename: str,
    content: bytes,
    *,
    form_directory: Path | None = None,
) -> int:
    """Validate and publish one form mapping under the shared dependency lock."""

    form_directory = form_directory or (
        (test_scheme_data_directory() or (PROJECT_ROOT / "data" / "schemes"))
        / "mock_forms"
    )
    if not re.fullmatch(r"^[A-Z0-9][A-Z0-9-]{1,79}\.json$", filename):
        raise ValueError("Publish exactly one named mock form mapping.")
    if type(content) is not bytes:
        raise TypeError("Published mock form data must be encoded bytes.")
    from src.documents.publication import (
        REVISION_FILENAME,
        _atomic_replace,
        _read_revision,
        checklist_publication_lock,
    )
    from src.mcp_servers.rule_data import get_active_rule_data

    try:
        _reject_duplicate_json_keys(content)
        mapping = MockFormMapping.model_validate_json(content)
        if mapping.scheme_id != filename[:-5]:
            raise ValueError("Form mapping filename and scheme ID differ.")
        mapping.validate_registry(get_active_rule_data().registry)
    except (ValueError, ValidationError) as error:
        raise ValueError("The mock form mapping does not match its schema.") from error
    form_directory = form_directory.resolve()
    revision_path = form_directory.parent / REVISION_FILENAME
    target = form_directory / filename
    with checklist_publication_lock(form_directory.parent / "document_checklists"):
        revision = _read_revision(revision_path)
        next_revision = revision + 1
        form_directory.mkdir(parents=True, exist_ok=True)
        _atomic_replace(revision_path, str(next_revision).encode("ascii"))
        _atomic_replace(target, content)
        return next_revision


def build_form_fields(
    snapshot: MockFormSnapshot,
    registry: FactRegistry,
    facts: dict[str, object | None],
    extra_values: dict[str, object] | None = None,
    *,
    bundle: SchemeBundle | None = None,
    typed_store: TypedFactStore | None = None,
) -> tuple[dict[str, object], list[str]]:
    """Populate fixed form fields and report required facts or inputs still missing."""

    mapping = snapshot.mapping
    if mapping is None:
        raise ValueError(snapshot.notice)
    mapping.validate_registry(registry, bundle)
    if typed_store is not None:
        facts = document_fact_values(mapping.scheme_id, registry, typed_store, bundle)
    elif any(
        field.fact_id in facts and registry.get(field.fact_id).derived_from
        for field in mapping.fields if field.fact_id is not None
    ):
        raise ValueError("Derived form facts require confirmed typed inputs.")
    extras = extra_values or {}
    allowed_extra_ids = {
        field.field_id for field in mapping.fields if field.extra_input
    }
    if set(extras) - allowed_extra_ids:
        raise ValueError("An input is not allowed by the active mock form.")

    values: dict[str, object] = {}
    missing: list[str] = []
    for field in mapping.fields:
        candidate = facts.get(field.fact_id) if field.fact_id else extras.get(field.field_id)
        if candidate is None:
            if field.required:
                missing.append(field.field_id)
            continue
        candidate = _validate_form_value(field, candidate)
        values[field.field_id] = (
            str(candidate)
            if isinstance(candidate, Decimal)
            else candidate.isoformat()
            if isinstance(candidate, date)
            else candidate
        )
    return values, missing


def _validate_form_value(field: MockFormField, value: object) -> object:
    """Validate form values without coercion or float-based decimal rounding."""

    if field.value_type == "boolean":
        if type(value) is not bool:
            raise ValueError(f"{field.field_id} must be a boolean.")
    elif field.value_type == "date":
        if isinstance(value, str):
            try:
                value = date.fromisoformat(value)
            except ValueError as error:
                raise ValueError(f"{field.field_id} must be an ISO date.") from error
        if type(value) is not date:
            raise ValueError(f"{field.field_id} must be an ISO date.")
    elif field.value_type == "integer":
        if type(value) is str and re.fullmatch(r"[+-]?[0-9]+", value):
            value = int(value)
        if type(value) is not int:
            raise ValueError(f"{field.field_id} must be an integer.")
    elif field.value_type == "decimal":
        if type(value) not in (int, float, Decimal, str):
            raise ValueError(f"{field.field_id} must be a decimal.")
        try:
            value = Decimal(str(value))
        except (ArithmeticError, InvalidOperation) as error:
            raise ValueError(f"{field.field_id} must be a finite decimal.") from error
        if not value.is_finite():
            raise ValueError(f"{field.field_id} must be a finite decimal.")
    elif field.value_type == "choice":
        if type(value) is not str or value not in field.choices:
            raise ValueError(f"{field.field_id} is not an allowed choice.")
    elif field.value_type == "text":
        if type(value) is not str or len(value) > (field.max_length or 0):
            raise ValueError(f"{field.field_id} exceeds its text limit.")
    else:
        raise ValueError("Unsupported mock form value type.")

    if field.value_type in {"integer", "decimal"}:
        numeric = Decimal(value) if type(value) is int else (
            Decimal(str(value)) if isinstance(value, float) else value
        )
        if field.minimum is not None and numeric < Decimal(str(field.minimum)):
            raise ValueError(f"{field.field_id} is below its minimum.")
        if field.maximum is not None and numeric > Decimal(str(field.maximum)):
            raise ValueError(f"{field.field_id} is above its maximum.")
    return value
