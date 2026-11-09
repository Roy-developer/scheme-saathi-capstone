"""Read-only document checklist assessment over user-entered synthetic fields."""

from datetime import date
import unicodedata
from typing import Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.documents.checklists import (
    ChecklistSnapshot,
    RequirementGroup,
    condition_applies,
    load_checklist_snapshot,
)
from src.rules.facts import FactRegistry, HouseholdProfile
from src.rules.bundles import SchemeBundle, document_fact_values
from src.mcp_servers.contracts import tool_error


DocumentStatus = Literal["available", "missing", "unknown", "mismatch"]


class SyntheticDocumentMetadata(BaseModel):
    """User-entered comparison fields; no file or OCR content is accepted."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    date_of_birth: date | None = None


class DocumentDiscrepancy(BaseModel):
    """A deterministic field mismatch without echoing either value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    code: Literal["name_mismatch", "date_of_birth_mismatch"]


class DocumentCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme_id: str = Field(min_length=1, max_length=80)
    documents: dict[str, DocumentStatus] = Field(default_factory=dict)
    profile_name: str | None = Field(default=None, max_length=120)
    profile_date_of_birth: date | None = None
    profile_conditions: dict[str, bool | None] = Field(default_factory=dict)
    profile_facts: dict[str, object | None] = Field(default_factory=dict)
    typed_facts: dict[str, object] | None = None
    document_metadata: dict[str, SyntheticDocumentMetadata] = Field(
        default_factory=dict
    )


class DocumentChecklistItem(BaseModel):
    """One synthetic checklist status; it is not proof of authenticity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    requirement_id: str
    label: str
    labels: dict[str, str]
    status: DocumentStatus


class DocumentRequirementGroup(BaseModel):
    """One required group and the statuses of its any-one alternatives."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    label: str
    labels: dict[str, str]
    condition: dict[str, object]
    applicable: bool | None
    status: Literal[
        "available", "missing", "unknown", "mismatch", "not_applicable"
    ]
    alternatives: list[DocumentChecklistItem]


class DocumentAssessment(BaseModel):
    """Typed report from metadata-only checklist evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme_id: str
    status: Literal[
        "checklist_complete",
        "mismatch",
        "missing_items",
        "unknown_items",
        "requirements_unverified",
    ]
    requirements_status: Literal[
        "demo_only_unverified",
        "approved_source_backed",
        "requirements_unverified",
        "conflict",
        "superseded",
    ]
    trust_status: Literal[
        "demo_only_unverified",
        "approved_source_backed",
        "requirements_unverified",
        "conflict",
        "superseded",
    ]
    demo_only: bool
    checklist_version: str | None
    checklist_fingerprint: str
    evidence_fingerprint: str
    active_fingerprint: str
    requirements: list[DocumentChecklistItem]
    groups: list[DocumentRequirementGroup]
    citations: list[dict[str, object]]
    discrepancies: list[DocumentDiscrepancy] = Field(default_factory=list)
    message: str


def _group_status(
    items: list[dict[str, object]], applicable: bool | None
) -> Literal["available", "missing", "unknown", "mismatch", "not_applicable"]:
    """Apply the any-one alternative rule without promoting unknown data."""

    if applicable is False:
        return "not_applicable"
    if applicable is None:
        return "unknown"
    statuses = {str(item["status"]) for item in items}
    if "available" in statuses:
        return "available"
    if "unknown" in statuses:
        return "unknown"
    if "mismatch" in statuses:
        return "mismatch"
    if "missing" in statuses:
        return "missing"
    return "unknown"


def _normalized_name(value: str) -> str:
    """Compare entered names without punctuation, spacing, or case differences."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def assess_document_metadata(
    data: dict[str, object],
    *,
    snapshot: ChecklistSnapshot | None = None,
    registry: FactRegistry | None = None,
    bundle: SchemeBundle | None = None,
) -> dict[str, object]:
    """Compare user-entered synthetic fields; never inspect files or authenticity."""

    request = DocumentCheckInput.model_validate(data)
    if registry is None:
        from src.mcp_servers.rule_data import get_active_rule_data

        registry = get_active_rule_data().registry
    profile_facts = dict(request.profile_facts)
    if any(registry.get(fact_id).derived_from for fact_id in profile_facts):
        raise ValueError("Derived document facts cannot be supplied directly.")
    if request.typed_facts is not None:
        store = HouseholdProfile.from_wire(request.typed_facts, registry)
        profile_facts.update(document_fact_values(
            request.scheme_id, registry, store, bundle,
        ))
    active = snapshot or load_checklist_snapshot(
        request.scheme_id, registry=registry, bundle=bundle
    )
    if active.scheme_id != request.scheme_id:
        raise ValueError("The checklist snapshot does not match the requested scheme.")
    if not active.usable or active.checklist is None:
        return {
            "scheme_id": request.scheme_id,
            "status": "requirements_unverified",
            "requirements_status": "requirements_unverified",
            "trust_status": active.trust_status,
            "demo_only": active.trust_status == "demo_only_unverified",
            "checklist_version": active.checklist_version,
            "checklist_fingerprint": active.checklist_fingerprint,
            "evidence_fingerprint": active.evidence_fingerprint,
            "active_fingerprint": active.active_fingerprint,
            "requirements": [],
            "groups": [],
            "citations": [],
            "discrepancies": [],
            "message": active.notice,
        }

    requirements = active.checklist.requirements
    active.checklist.validate_registry(registry, bundle)
    required_ids = {
        alternative.document_id
        for requirement in requirements
        for alternative in requirement.alternatives
    }
    if (
        (set(request.documents) | set(request.document_metadata)) - required_ids
    ):
        raise ValueError("A document ID is not in this scheme's active checklist.")
    discrepancies: list[dict[str, str]] = []
    groups: list[dict[str, object]] = []
    items: list[dict[str, object]] = []

    for requirement in requirements:
        applies = condition_applies(
            requirement.condition, request.profile_conditions, profile_facts
        )
        group_items = [
            _assessed_item(
                request,
                alternative.document_id,
                requirement.requirement_id,
                alternative.labels.en,
                discrepancies,
                alternative.labels.model_dump(),
            )
            for alternative in requirement.alternatives
        ]
        if applies is False:
            for item in group_items:
                item["status"] = "unknown"
        items.extend(group_items)
        groups.append({
            "requirement_id": requirement.requirement_id,
            "label": requirement.labels.en,
            "labels": requirement.labels.model_dump(),
            "condition": requirement.condition.model_dump(),
            "applicable": applies,
            "status": _group_status(group_items, applies),
            "alternatives": group_items,
        })
    applicable_statuses = {
        str(group["status"])
        for group in groups
        if group["status"] != "not_applicable"
    }
    overall = (
        "checklist_complete"
        if applicable_statuses <= {"available"}
        else "mismatch"
        if "mismatch" in applicable_statuses
        else "missing_items"
        if "missing" in applicable_statuses
        else "unknown_items"
    )
    return {
        "scheme_id": request.scheme_id,
        "status": overall,
        "requirements_status": active.trust_status,
        "trust_status": active.trust_status,
        "demo_only": active.trust_status == "demo_only_unverified",
        "checklist_version": active.checklist_version,
        "checklist_fingerprint": active.checklist_fingerprint,
        "evidence_fingerprint": active.evidence_fingerprint,
        "active_fingerprint": active.active_fingerprint,
        "requirements": items,
        "groups": groups,
        "citations": [
            passage.model_dump(mode="json") for passage in active.citations
        ],
        "discrepancies": discrepancies,
        "message": f"{active.notice} Entered fields were compared deterministically. "
        "No files were uploaded, read, or authenticated.",
    }


def _assessed_item(
    request: DocumentCheckInput,
    document_id: str,
    requirement_id: str,
    label: str,
    discrepancies: list[dict[str, str]],
    labels: dict[str, str],
) -> dict[str, object]:
    """Return one checklist result and append any code-owned field mismatch."""

    status = request.documents.get(document_id, "unknown")
    metadata = request.document_metadata.get(document_id)
    if metadata is not None:
        if metadata.name and request.profile_name:
            if _normalized_name(metadata.name) != _normalized_name(request.profile_name):
                discrepancies.append({
                    "document_id": document_id, "code": "name_mismatch",
                })
                status = "mismatch"
        elif metadata.name and not request.profile_name:
            status = "unknown"
        if metadata.date_of_birth is not None and request.profile_date_of_birth:
            if metadata.date_of_birth != request.profile_date_of_birth:
                discrepancies.append({
                    "document_id": document_id, "code": "date_of_birth_mismatch",
                })
                status = "mismatch"
        elif metadata.date_of_birth is not None and not request.profile_date_of_birth:
            status = "unknown"
    return {
        "document_id": document_id,
        "requirement_id": requirement_id,
        "label": label,
        "labels": labels,
        "status": status,
    }


def register_tools(mcp: MCPServer) -> None:
    """Register the document checker independently from mock-portal tools."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Check synthetic document metadata",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def check_documents(
        scheme_id: str,
        documents: dict[str, DocumentStatus],
        profile_name: str | None = None,
        profile_date_of_birth: date | None = None,
        document_metadata: dict[str, SyntheticDocumentMetadata] | None = None,
        profile_conditions: dict[str, bool | None] | None = None,
        profile_facts: dict[str, object | None] | None = None,
        typed_facts: dict[str, object] | None = None,
    ) -> DocumentAssessment:
        """Check user-entered document statuses against the active checklist."""

        try:
            result = assess_document_metadata({
                "scheme_id": scheme_id,
                "documents": documents,
                "profile_name": profile_name,
                "profile_date_of_birth": profile_date_of_birth,
                "document_metadata": document_metadata or {},
                "profile_conditions": profile_conditions or {},
                "profile_facts": profile_facts or {},
                "typed_facts": typed_facts,
            })
            return DocumentAssessment.model_validate(result)
        except ValidationError as error:
            raise tool_error(
                "invalid_input", "Document metadata did not match the expected schema."
            ) from error
        except ValueError as error:
            raise tool_error("invalid_input", str(error)) from error
