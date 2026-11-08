"""Validate versioned document checklists and their evidence without ranking."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    model_validator,
)

from src.config import PROJECT_ROOT, test_scheme_data_directory
from src.rules.bundles import SchemeBundle, document_fact_allowlist
from src.rules.facts import FactRegistry


Locale = Literal["en", "hi", "mr"]
_SCHEME_DATA_DIRECTORY = test_scheme_data_directory() or (
    PROJECT_ROOT / "data" / "schemes"
)
CHECKLIST_DIRECTORY = _SCHEME_DATA_DIRECTORY / "document_checklists"
EVIDENCE_FILE = _SCHEME_DATA_DIRECTORY / "document_evidence.json"
ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,79}$")
VERSION_PATTERN = re.compile(r"^v[1-9][0-9]*$")


class StrictModel(BaseModel):
    """Reject unchecked fields in persisted checklist records."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LocalizedText(StrictModel):
    """A user-facing label in every supported application language."""

    en: str = Field(min_length=1, max_length=240)
    hi: str = Field(min_length=1, max_length=240)
    mr: str = Field(min_length=1, max_length=240)


class UnconditionalCondition(StrictModel):
    """A requirement group that always applies."""

    kind: Literal["unconditional"]


class ProfileBooleanCondition(StrictModel):
    """A narrow, code-evaluated condition over a confirmed profile boolean."""

    kind: Literal["profile_boolean"]
    field: Literal["is_widow", "bpl_card_shown"]
    equals: bool


class RegisteredFactCondition(StrictModel):
    """A comparison over one confirmed, registered fact."""

    kind: Literal["registered_fact"]
    fact_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    operator: Literal["eq", "gte", "lte"]
    value: str | int | float | bool


RequirementCondition = Annotated[
    UnconditionalCondition | ProfileBooleanCondition | RegisteredFactCondition,
    Field(discriminator="kind"),
]


class DocumentAlternative(StrictModel):
    """One document accepted as an alternative within a required group."""

    document_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    labels: LocalizedText


class RequirementGroup(StrictModel):
    """A required group whose alternatives are satisfied by any one item."""

    requirement_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    labels: LocalizedText
    alternatives: list[DocumentAlternative] = Field(min_length=1, max_length=20)
    condition: RequirementCondition = Field(
        default_factory=lambda: UnconditionalCondition(kind="unconditional")
    )
    evidence_passage_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_alternatives(self) -> RequirementGroup:
        """Require distinct stable document IDs inside each group."""

        identifiers = [alternative.document_id for alternative in self.alternatives]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Alternative document IDs must be unique.")
        return self


class ChecklistApproval(StrictModel):
    """Review state and exact content versions covered by human approval."""

    status: Literal[
        "demo_only", "pending_review", "approved", "conflict", "superseded"
    ]
    checklist_version: str
    checklist_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    evidence_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    reviewer_role: str | None = Field(default=None, min_length=1, max_length=120)
    review_reference: str | None = Field(default=None, min_length=1, max_length=240)
    reviewed_on: date | None = None


class DocumentChecklist(StrictModel):
    """Versioned structured requirements for one scheme."""

    schema_version: Literal[1]
    scheme_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,79}$")
    checklist_version: str = Field(pattern=VERSION_PATTERN)
    requirements: list[RequirementGroup] = Field(min_length=1, max_length=100)
    approval: ChecklistApproval

    @model_validator(mode="after")
    def unique_requirement_ids(self) -> DocumentChecklist:
        """Require distinct stable groups and evidence links."""

        identifiers = [item.requirement_id for item in self.requirements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Requirement IDs must be unique.")
        passage_ids = [
            passage_id
            for item in self.requirements
            for passage_id in item.evidence_passage_ids
        ]
        if any(not ID_PATTERN.fullmatch(passage_id) for passage_id in passage_ids):
            raise ValueError("Evidence passage IDs must use stable identifiers.")
        document_ids = [
            alternative.document_id
            for requirement in self.requirements
            for alternative in requirement.alternatives
        ]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Document IDs must be unique across the checklist.")
        if self.approval.status == "approved" and any(
            not requirement.evidence_passage_ids
            for requirement in self.requirements
        ):
            raise ValueError("Every approved requirement needs linked evidence.")
        return self

    def validate_registry(
        self, registry: FactRegistry, bundle: SchemeBundle | None = None,
    ) -> None:
        """Reject unknown or type-incompatible registered fact conditions."""

        allowed = document_fact_allowlist(self.scheme_id, registry, bundle)
        for requirement in self.requirements:
            condition = requirement.condition
            if isinstance(condition, ProfileBooleanCondition):
                if bundle is None:
                    from src.mcp_servers.rule_data import get_active_rule_data

                    try:
                        bundle = get_active_rule_data().get_bundle(self.scheme_id)
                    except KeyError as error:
                        raise ValueError("Checklist requires an active scheme bundle.") from error
                if not any(
                    fact_id in allowed and field == condition.field
                    for fact_id, field in bundle.legacy_profile_mapping.items()
                ):
                    raise ValueError("Checklist condition is outside its scheme bundle.")
                continue
            if not isinstance(condition, RegisteredFactCondition):
                continue
            if condition.fact_id not in allowed:
                raise ValueError("Checklist condition is outside its scheme bundle.")
            try:
                definition = registry.get(condition.fact_id)
            except (AttributeError, KeyError) as error:
                raise ValueError(
                    f"Checklist references unknown fact '{condition.fact_id}'."
                ) from error
            value = condition.value
            fact_type = definition.value_type
            if fact_type == "text":
                raise ValueError("Display-only facts cannot control requirements.")
            if fact_type == "boolean":
                compatible = condition.operator == "eq" and type(value) is bool
            elif fact_type == "choice":
                compatible = (
                    condition.operator == "eq"
                    and type(value) is str
                    and value in definition.choices
                )
            elif fact_type == "date":
                try:
                    date.fromisoformat(value)
                    compatible = (
                        condition.operator in {"eq", "gte", "lte"}
                        and type(value) is str
                    )
                except (TypeError, ValueError):
                    compatible = False
            elif fact_type == "integer":
                compatible = (
                    condition.operator in {"eq", "gte", "lte"}
                    and type(value) is int
                )
            elif fact_type == "decimal":
                try:
                    Decimal(value)
                    compatible = (
                        condition.operator in {"eq", "gte", "lte"}
                        and type(value) is str
                        and Decimal(value).is_finite()
                    )
                except (ArithmeticError, TypeError, ValueError):
                    compatible = False
            else:
                compatible = False
            if not compatible:
                raise ValueError(
                    f"Checklist condition is incompatible with fact '{condition.fact_id}'."
                )
            if fact_type in {"integer", "decimal"}:
                numeric = Decimal(str(value))
                if definition.minimum is not None and numeric < Decimal(
                    str(definition.minimum)
                ):
                    raise ValueError("Checklist condition is below the fact minimum.")
                if definition.maximum is not None and numeric > Decimal(
                    str(definition.maximum)
                ):
                    raise ValueError("Checklist condition exceeds the fact maximum.")


class EvidencePassage(StrictModel):
    """Exact source evidence and the team's recorded review status."""

    passage_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{1,79}$")
    scheme_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,79}$")
    section: Literal["documents"]
    exact_quote: str = Field(min_length=1, max_length=12000)
    source_url: HttpUrl
    source_locator: str = Field(min_length=1, max_length=500)
    language: str = Field(min_length=2, max_length=20)
    collected_on: date
    publication_date: date | None = None
    review_status: Literal[
        "pending_review", "reviewed", "rejected", "conflict", "superseded"
    ]


class EvidenceCorpus(StrictModel):
    """All locally recorded document evidence passages."""

    schema_version: Literal[1]
    passages: list[EvidencePassage] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def unique_passage_ids(self) -> EvidenceCorpus:
        """Require unique passage IDs in the evidence corpus."""

        identifiers = [passage.passage_id for passage in self.passages]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Evidence passage IDs must be unique.")
        return self


TrustStatus = Literal[
    "demo_only_unverified",
    "approved_source_backed",
    "requirements_unverified",
    "conflict",
    "superseded",
]


class ChecklistSnapshot(StrictModel):
    """One freshly read active checklist, its trust state and stable fingerprints."""

    scheme_id: str
    checklist: DocumentChecklist | None
    evidence: list[EvidencePassage]
    citations: list[EvidencePassage]
    trust_status: TrustStatus
    checklist_version: str | None
    publication_revision: int
    checklist_fingerprint: str
    evidence_fingerprint: str
    active_fingerprint: str
    notice: str

    @property
    def usable(self) -> bool:
        """Return whether these checked requirements may be used for a report."""

        return self.checklist is not None and self.trust_status in {
            "demo_only_unverified",
            "approved_source_backed",
        }


def _sha256(content: bytes) -> str:
    """Return a stable digest of exact file content."""

    return hashlib.sha256(content).hexdigest()


def _canonical_digest(value: object) -> str:
    """Hash canonical JSON for the checklist fields covered by approval."""

    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256(encoded)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys whose meaning can vary between JSON consumers."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def _reject_duplicate_json_keys(content: bytes) -> None:
    """Validate JSON object keys before the schema parser reads the same bytes."""

    json.loads(content, object_pairs_hook=_unique_json_object)


def _load_bytes(path: Path) -> bytes | None:
    """Read one data file without exposing operating-system details."""

    try:
        return path.read_bytes()
    except OSError:
        return None


def _failure_snapshot(
    scheme_id: str,
    checklist_bytes: bytes | None,
    evidence_bytes: bytes | None,
    *,
    checklist_version: str | None = None,
    publication_revision: int = 0,
    status: TrustStatus = "requirements_unverified",
    notice: str = "Document requirements are not verified.",
) -> ChecklistSnapshot:
    """Build a fail-closed snapshot while retaining mutation-sensitive hashes."""

    checklist_fingerprint = _sha256(
        checklist_bytes if checklist_bytes is not None else b"<missing-checklist>"
    )
    evidence_fingerprint = _sha256(
        evidence_bytes if evidence_bytes is not None else b"<missing-evidence>"
    )
    active_fingerprint = _canonical_digest({
        "scheme_id": scheme_id,
        "checklist": checklist_fingerprint,
        "evidence": evidence_fingerprint,
        "trust_status": status,
        "publication_revision": publication_revision,
    })
    return ChecklistSnapshot(
        scheme_id=scheme_id,
        checklist=None,
        evidence=[],
        citations=[],
        trust_status=status,
        checklist_version=checklist_version,
        publication_revision=publication_revision,
        checklist_fingerprint=checklist_fingerprint,
        evidence_fingerprint=evidence_fingerprint,
        active_fingerprint=active_fingerprint,
        notice=notice,
    )


def load_checklist_snapshot(
    scheme_id: str,
    *,
    checklist_directory: Path | None = None,
    evidence_file: Path | None = None,
    registry: FactRegistry | None = None,
    bundle: SchemeBundle | None = None,
) -> ChecklistSnapshot:
    """Read and validate the active checklist and its exact referenced evidence.

    Args:
        scheme_id: Stable scheme ID; lookups are direct and never ranked.
        checklist_directory: Optional data directory for isolated tests.
        evidence_file: Optional evidence corpus path for isolated tests.
    """

    checklist_directory = checklist_directory or CHECKLIST_DIRECTORY
    evidence_file = evidence_file or EVIDENCE_FILE
    from src.documents.publication import checklist_publication_lock

    with checklist_publication_lock(checklist_directory):
        return _load_checklist_snapshot_unlocked(
            scheme_id, checklist_directory, evidence_file, registry, bundle
        )


def _load_checklist_snapshot_unlocked(
    scheme_id: str,
    checklist_directory: Path,
    evidence_file: Path,
    registry: FactRegistry | None = None,
    bundle: SchemeBundle | None = None,
) -> ChecklistSnapshot:
    """Read checklist files while the caller owns the publication lock."""

    revision_path = checklist_directory.parent / ".document_checklists.revision"
    try:
        revision_bytes = revision_path.read_bytes()
    except FileNotFoundError:
        publication_revision = 0
    except OSError:
        return _failure_snapshot(
            scheme_id, None, None,
            notice="Checklist publication state is unavailable; requirements are not verified.",
        )
    else:
        try:
            revision_text = revision_bytes.decode("ascii")
            if not revision_text.isdigit():
                raise ValueError("Invalid publication revision.")
            publication_revision = int(revision_text)
        except (UnicodeDecodeError, ValueError):
            return _failure_snapshot(
                scheme_id, None, None,
                notice="Checklist publication state is invalid; requirements are not verified.",
            )
    if not re.fullmatch(r"^[A-Z0-9][A-Z0-9-]{1,79}$", scheme_id):
        return _failure_snapshot(scheme_id, None, None)
    checklist_path = checklist_directory / f"{scheme_id}.json"
    checklist_bytes = _load_bytes(checklist_path)
    evidence_bytes = _load_bytes(evidence_file)
    return _snapshot_from_bytes(
        scheme_id, checklist_bytes, evidence_bytes, publication_revision, registry, bundle
    )


def _snapshot_from_bytes(
    scheme_id: str,
    checklist_bytes: bytes | None,
    evidence_bytes: bytes | None,
    publication_revision: int,
    registry: FactRegistry | None = None,
    bundle: SchemeBundle | None = None,
) -> ChecklistSnapshot:
    """Validate a checklist/evidence pair already read from storage."""

    if checklist_bytes is None:
        return _failure_snapshot(
            scheme_id, None, evidence_bytes,
            publication_revision=publication_revision,
            notice="No document checklist is configured; requirements are not verified.",
        )
    try:
        _reject_duplicate_json_keys(checklist_bytes)
        raw_checklist = json.loads(checklist_bytes)
        checklist = DocumentChecklist.model_validate_json(checklist_bytes)
    except (
        UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError
    ):
        return _failure_snapshot(
            scheme_id, checklist_bytes, evidence_bytes,
            publication_revision=publication_revision,
        )
    if checklist.scheme_id != scheme_id:
        return _failure_snapshot(
            scheme_id, checklist_bytes, evidence_bytes,
            checklist_version=checklist.checklist_version,
            publication_revision=publication_revision,
            notice="The checklist is linked to a different scheme; requirements are not verified.",
        )
    if checklist.approval.checklist_version != checklist.checklist_version:
        return _failure_snapshot(
            scheme_id, checklist_bytes, evidence_bytes,
            checklist_version=checklist.checklist_version,
            publication_revision=publication_revision,
        )
    try:
        if registry is None:
            from src.mcp_servers.rule_data import get_active_rule_data

            registry = get_active_rule_data().registry
        checklist.validate_registry(registry, bundle)
    except (KeyError, ValueError):
        return _failure_snapshot(
            scheme_id, checklist_bytes, evidence_bytes,
            checklist_version=checklist.checklist_version,
            publication_revision=publication_revision,
        )
    if evidence_bytes is None:
        return _failure_snapshot(
            scheme_id, checklist_bytes, None,
            checklist_version=checklist.checklist_version,
            publication_revision=publication_revision,
        )
    try:
        _reject_duplicate_json_keys(evidence_bytes)
        corpus = EvidenceCorpus.model_validate_json(evidence_bytes)
    except (ValidationError, ValueError):
        return _failure_snapshot(
            scheme_id, checklist_bytes, evidence_bytes,
            checklist_version=checklist.checklist_version,
            publication_revision=publication_revision,
        )
    evidence_by_id = {passage.passage_id: passage for passage in corpus.passages}
    referenced_ids = {
        passage_id
        for requirement in checklist.requirements
        for passage_id in requirement.evidence_passage_ids
    }
    if any(
        passage_id not in evidence_by_id
        or evidence_by_id[passage_id].scheme_id != scheme_id
        for passage_id in referenced_ids
    ):
        return _failure_snapshot(
            scheme_id, checklist_bytes, evidence_bytes,
            checklist_version=checklist.checklist_version,
            publication_revision=publication_revision,
            notice="Checklist evidence is missing or linked to another scheme; requirements are not verified.",
        )
    references = [evidence_by_id[item] for item in sorted(referenced_ids)]
    approval_status = checklist.approval.status
    status: TrustStatus
    if approval_status == "conflict" or any(
        passage.review_status == "conflict" for passage in references
    ):
        status = "conflict"
    elif approval_status == "superseded" or any(
        passage.review_status == "superseded" for passage in references
    ):
        status = "superseded"
    elif approval_status == "demo_only":
        if referenced_ids:
            return _failure_snapshot(
                scheme_id, checklist_bytes, evidence_bytes,
                checklist_version=checklist.checklist_version,
                publication_revision=publication_revision,
            )
        status = "demo_only_unverified"
    elif approval_status != "approved":
        status = "requirements_unverified"
    else:
        core = dict(raw_checklist)
        core.pop("approval", None)
        approved_checklist_digest = _canonical_digest(core)
        approved_evidence_digest = _sha256(evidence_bytes)
        approval = checklist.approval
        source_reviews_complete = bool(referenced_ids) and all(
            passage.review_status == "reviewed" for passage in references
        )
        approval_complete = all((
            approval.checklist_content_sha256 == approved_checklist_digest,
            approval.evidence_content_sha256 == approved_evidence_digest,
            bool(approval.reviewer_role),
            bool(approval.review_reference),
            approval.reviewed_on is not None,
        ))
        if source_reviews_complete and approval_complete:
            status = "approved_source_backed"
        else:
            status = "requirements_unverified"
    citations = references if status == "approved_source_backed" else []
    active_fingerprint = _canonical_digest({
        "scheme_id": scheme_id,
        "checklist": _sha256(checklist_bytes),
        "evidence": _sha256(evidence_bytes),
        "trust_status": status,
        "publication_revision": publication_revision,
    })
    notice = (
        "Demo checklist only; these items are not verified official requirements."
        if status == "demo_only_unverified"
        else "Requirements are supported by reviewed, approved source evidence."
        if status == "approved_source_backed"
        else "Requirements are not verified; ask a human caseworker."
    )
    return ChecklistSnapshot(
        scheme_id=scheme_id,
        checklist=checklist,
        evidence=corpus.passages,
        citations=citations,
        trust_status=status,
        checklist_version=checklist.checklist_version,
        publication_revision=publication_revision,
        checklist_fingerprint=_sha256(checklist_bytes),
        evidence_fingerprint=_sha256(evidence_bytes),
        active_fingerprint=active_fingerprint,
        notice=notice,
    )


def condition_applies(
    condition: RequirementCondition,
    profile_conditions: dict[str, bool | None],
    profile_facts: dict[str, object | None] | None = None,
) -> bool | None:
    """Evaluate supported comparisons; missing registered facts stay unknown."""

    if condition.kind == "unconditional":
        return True
    if condition.kind == "profile_boolean":
        value = profile_conditions.get(condition.field)
        expected = condition.equals
    else:
        value = (profile_facts or {}).get(condition.fact_id)
        expected = condition.value
    if value is None:
        return None
    if condition.kind == "registered_fact" and condition.operator in {"gte", "lte"}:
        if isinstance(value, date):
            left = value
            right = date.fromisoformat(str(expected))
        else:
            left = Decimal(str(value))
            right = Decimal(str(expected))
        return left >= right if condition.operator == "gte" else left <= right
    return value == expected
