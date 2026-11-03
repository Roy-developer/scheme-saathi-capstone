"""Typed contracts and MCP client helpers for synthetic applications."""

from typing import Any, Literal

from mcp import Client
from pydantic import BaseModel, ConfigDict, Field

from src.workflow.errors import MCPToolError


DocumentStatus = Literal["available", "missing", "unknown", "mismatch"]
ApprovalAction = Literal["approve", "reject", "submit"]


class StrictApplicationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentAssessmentRequest(StrictApplicationModel):
    scheme_id: str = Field(min_length=1, max_length=80)
    documents: dict[str, DocumentStatus] = Field(default_factory=dict)


class DraftCreateRequest(StrictApplicationModel):
    scheme_id: str = Field(min_length=1, max_length=80)
    documents: dict[str, DocumentStatus]
    applicant_reference: str = Field(default="Synthetic applicant", min_length=1, max_length=80)
    district: str = Field(default="Synthetic district", min_length=1, max_length=80)


class DraftEditRequest(StrictApplicationModel):
    revision: int = Field(ge=1)
    applicant_reference: str = Field(min_length=1, max_length=80)
    district: str = Field(min_length=1, max_length=80)


class DraftApprovalRequest(StrictApplicationModel):
    action: ApprovalAction
    revision: int = Field(ge=1)
    fingerprint: str = Field(min_length=64, max_length=64)


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
