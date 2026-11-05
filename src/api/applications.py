"""Typed contracts and MCP client helpers for synthetic applications."""

from datetime import date
import hashlib
import json
from typing import Any, Literal

from mcp import Client
from pydantic import BaseModel, ConfigDict, Field

from src.workflow.errors import MCPToolError


DocumentStatus = Literal["available", "missing", "unknown", "mismatch"]
ApprovalAction = Literal["approve", "reject", "submit"]


class StrictApplicationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentMetadata(StrictApplicationModel):
    """Synthetic name/date fields entered by a person for comparison only."""

    name: str | None = Field(default=None, max_length=120)
    date_of_birth: date | None = None


class DocumentAssessmentRequest(StrictApplicationModel):
    scheme_id: str = Field(min_length=1, max_length=80)
    documents: dict[str, DocumentStatus] = Field(default_factory=dict)
    profile_name: str | None = Field(default=None, max_length=120)
    document_metadata: dict[str, DocumentMetadata] = Field(default_factory=dict)


class DraftCreateRequest(StrictApplicationModel):
    scheme_id: str = Field(min_length=1, max_length=80)
    documents: dict[str, DocumentStatus]
    profile_name: str | None = Field(default=None, max_length=120)
    document_metadata: dict[str, DocumentMetadata] = Field(default_factory=dict)
    applicant_reference: str = Field(default="Synthetic applicant", min_length=1, max_length=80)
    district: str = Field(default="Synthetic district", min_length=1, max_length=80)
    form_values: dict[str, object] = Field(default_factory=dict)


class DraftEditRequest(StrictApplicationModel):
    revision: int = Field(ge=1)
    applicant_reference: str = Field(min_length=1, max_length=80)
    district: str = Field(min_length=1, max_length=80)


class DraftApprovalRequest(StrictApplicationModel):
    action: ApprovalAction
    revision: int = Field(ge=1)
    fingerprint: str = Field(min_length=64, max_length=64)


def document_input_fingerprint(
    scheme_id: str,
    documents: dict[str, str],
    profile_name: str | None,
    profile_date_of_birth: date | str | None,
    document_metadata: dict[str, dict[str, object]],
    checklist_fingerprint: str = "",
    evidence_fingerprint: str = "",
    active_checklist_fingerprint: str = "",
    profile_conditions: dict[str, bool | None] | None = None,
    typed_facts: dict[str, object] | None = None,
    bundle_fingerprint: str = "",
) -> str:
    """Hash the exact synthetic metadata report without persisting its values."""

    def normalized(value: object) -> object:
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            return value.strip() or None
        return value

    canonical = {
        "scheme_id": scheme_id,
        "documents": documents,
        "profile_name": normalized(profile_name),
        "profile_date_of_birth": normalized(profile_date_of_birth),
        "document_metadata": {
            document_id: {
                key: value
                for key, raw_value in fields.items()
                if (value := normalized(raw_value)) is not None
            }
            for document_id, fields in document_metadata.items()
        },
        "checklist_fingerprint": checklist_fingerprint,
        "evidence_fingerprint": evidence_fingerprint,
        "active_checklist_fingerprint": active_checklist_fingerprint,
        "profile_conditions": profile_conditions or {},
        "typed_facts": typed_facts or {},
        "bundle_fingerprint": bundle_fingerprint,
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def call_application_tool(
    client: Client,
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Call an application MCP tool and reject any malformed/error response."""

    try:
        result = await client.call_tool(tool, arguments)
    except Exception as error:
        raise MCPToolError(f"Could not call the MCP {tool} tool.") from error
    if result.is_error or result.structured_content is None:
        raise MCPToolError(f"The MCP {tool} tool returned an error.")
    if not isinstance(result.structured_content, dict):
        raise MCPToolError(f"The MCP {tool} tool returned an invalid response.")
    return result.structured_content
