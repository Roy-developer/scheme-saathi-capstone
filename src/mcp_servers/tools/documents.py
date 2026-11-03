"""Read-only synthetic document checklist MCP tool."""

from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DocumentStatus = Literal["available", "missing", "unknown", "mismatch"]

# These demo prompts are not official or source-verified requirements.
DEMO_REQUIREMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "IGNWPS-MH": (
        ("identity_proof", "Identity proof (synthetic demo item)"),
        ("age_proof", "Age proof (synthetic demo item)"),
        ("widow_status_proof", "Widow status proof (synthetic demo item)"),
        ("bpl_proof", "BPL proof (synthetic demo item)"),
    ),
    "PM-KISAN-IN": (
        ("identity_proof", "Identity proof (synthetic demo item)"),
        ("land_record", "Land record (synthetic demo item)"),
        ("bank_account_proof", "Bank account proof (synthetic demo item)"),
    ),
}


class DocumentCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme_id: str = Field(min_length=1, max_length=80)
    documents: dict[str, DocumentStatus] = Field(default_factory=dict)


def assess_document_metadata(data: dict) -> dict:
    """Assess user-reported metadata only; never inspect document contents."""

    request = DocumentCheckInput.model_validate(data)
    requirements = DEMO_REQUIREMENTS.get(request.scheme_id)
    if requirements is None:
        return {
            "scheme_id": request.scheme_id,
            "status": "requirements_unverified",
            "demo_only": True,
            "requirements": [],
            "message": "No document requirements are configured for this scheme.",
        }

    required_ids = {item_id for item_id, _ in requirements}
    if set(request.documents) - required_ids:
        raise ValueError("A document ID is not in this scheme's demo checklist.")
    items = [
        {
            "document_id": item_id,
            "label": label,
            "status": request.documents.get(item_id, "unknown"),
        }
        for item_id, label in requirements
    ]
    statuses = {item["status"] for item in items}
    overall = (
        "checklist_complete"
        if statuses == {"available"}
        else "mismatch"
        if "mismatch" in statuses
        else "missing_items"
        if "missing" in statuses
        else "unknown_items"
    )
    return {
        "scheme_id": request.scheme_id,
        "status": overall,
        "demo_only": True,
        "requirements": items,
        "message": (
            "Demo checklist only; these items are not verified official "
            "requirements and no documents were uploaded or authenticated."
        ),
    }


def register_tools(mcp: MCPServer) -> None:
    """Register the document checker independently from mock-portal tools."""

    @mcp.tool()
    def check_documents(
        scheme_id: str,
        documents: dict[str, str],
    ) -> dict[str, Any]:
        """Check synthetic document metadata against demo checklist items."""

        try:
            return assess_document_metadata({
                "scheme_id": scheme_id,
                "documents": documents,
            })
        except (ValidationError, ValueError) as error:
            raise ToolError(str(error)) from error
