"""MCP adapter for the independent synthetic HTTP portal service."""

import json
import urllib.error
import urllib.request
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, ValidationError, model_serializer
from pydantic.functional_serializers import SerializerFunctionWrapHandler

from src.mcp_servers.contracts import tool_error
from src.config import PORTAL_URL
from src.mcp_servers.tools.documents import DocumentStatus
from src.portal.repository import PortalAction, PortalInput, _portal_action


class PortalResponse(BaseModel):
    """Typed fields returned by draft, status, and trusted workflow actions."""

    model_config = ConfigDict(extra="forbid")

    draft_id: str | None = None
    journey_id: str | None = None
    scheme_id: str | None = None
    revision: int | None = None
    draft: dict[str, object] | None = None
    fingerprint: str | None = None
    approved: bool | None = None
    rejected: bool | None = None
    receipt_id: str | None = None
    approval_expires_at: str | None = None
    approval_expired: bool | None = None
    approval_token: str | None = None
    deleted: bool | None = None
    not_found: bool | None = None
    drafts: list[dict[str, object]] | None = None
    status: str | None = None
    stale: bool | None = None
    dependency_version: int | None = None
    blocked: bool | None = None

    @model_serializer(mode="wrap")
    def omit_empty_fields(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        """Keep older action clients' payloads free of unused null fields."""

        return {
            name: value
            for name, value in handler(self).items()
            if value is not None
            or (name == "receipt_id" and self.draft_id is not None)
        }


def _call_portal(data: dict[str, object]) -> PortalResponse:
    """Send one typed request over HTTP and turn safe service failures into MCP errors."""

    try:
        request = PortalInput.model_validate(data)
    except ValidationError as error:
        raise tool_error(
            "invalid_input", "Portal action did not match the expected schema."
        ) from error
    body = json.dumps(
        request.model_dump(mode="json", exclude_none=True)
    ).encode("utf-8")
    http_request = urllib.request.Request(
        f"{PORTAL_URL}/internal/actions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("detail", {})
        except (json.JSONDecodeError, AttributeError):
            detail = {}
        code = (
            "conflict"
            if error.code == 409
            else "not_found"
            if error.code == 404
            else "invalid_input"
        )
        message = detail.get("message", "The portal request was rejected.")
        raise tool_error(code, str(message)) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise tool_error(
            "service_unavailable", "The synthetic portal service is unavailable."
        ) from error
    try:
        return PortalResponse.model_validate(result)
    except (TypeError, ValueError) as error:
        raise tool_error(
            "internal_error", "The synthetic portal returned an invalid response."
        ) from error


def register_tools(mcp: MCPServer) -> None:
    """Register portal operations; write actions remain behind the HTTP boundary."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Create synthetic draft",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        )
    )
    def create_draft(
        journey_id: str,
        scheme_id: str,
        profile: dict[str, object],
        documents: dict[str, DocumentStatus],
        rule_package_version: str | None = None,
        deciding_rule_ids: list[str] | None = None,
        document_report_fingerprint: str | None = None,
        checklist_fingerprint: str | None = None,
        evidence_fingerprint: str | None = None,
        active_checklist_fingerprint: str | None = None,
        typed_facts: dict[str, object] | None = None,
        form_values: dict[str, object] | None = None,
        applicant_reference: str | None = None,
        district: str | None = None,
    ) -> PortalResponse:
        """Create a synthetic draft in the separate local portal service."""

        return _call_portal({
            "action": "create_draft",
            "journey_id": journey_id,
            "scheme_id": scheme_id,
            "profile": profile,
            "documents": documents,
            "rule_package_version": rule_package_version,
            "deciding_rule_ids": deciding_rule_ids,
            "document_report_fingerprint": document_report_fingerprint,
            "checklist_fingerprint": checklist_fingerprint,
            "evidence_fingerprint": evidence_fingerprint,
            "active_checklist_fingerprint": active_checklist_fingerprint,
            "typed_facts": typed_facts,
            "form_values": form_values,
            "applicant_reference": applicant_reference,
            "district": district,
        })

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Read synthetic draft",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def get_draft(journey_id: str, draft_id: str) -> PortalResponse:
        """Read a draft that belongs to the supplied synthetic journey."""

        return _call_portal({
            "action": "get_draft",
            "journey_id": journey_id,
            "draft_id": draft_id,
        })

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Read synthetic application status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def get_status(journey_id: str, draft_id: str) -> PortalResponse:
        """Read draft, approval, rejection, or mock submission status."""

        return _call_portal({
            "action": "get_status",
            "journey_id": journey_id,
            "draft_id": draft_id,
        })

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Submit approved synthetic draft",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def submit_draft(
        journey_id: str,
        draft_id: str,
        revision: int,
        fingerprint: str,
        approval_token: str,
    ) -> PortalResponse:
        """Submit only the exact revision and fingerprint already approved by a person."""

        return _call_portal({
            "action": "submit",
            "journey_id": journey_id,
            "draft_id": draft_id,
            "revision": revision,
            "fingerprint": fingerprint,
            "approval_token": approval_token,
        })

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Scoped synthetic portal action",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        )
    )
    def mock_portal(
        action: PortalAction,
        journey_id: str,
        scheme_id: str | None = None,
        draft_id: str | None = None,
        revision: int | None = None,
        fingerprint: str | None = None,
        profile: dict[str, object] | None = None,
        rule_package_version: str | None = None,
        deciding_rule_ids: list[str] | None = None,
        documents: dict[str, DocumentStatus] | None = None,
        applicant_reference: str | None = None,
        district: str | None = None,
        dependency_version: int | None = None,
        rules_fingerprint: str | None = None,
        document_report_fingerprint: str | None = None,
        checklist_fingerprint: str | None = None,
        evidence_fingerprint: str | None = None,
        active_checklist_fingerprint: str | None = None,
        typed_facts: dict[str, object] | None = None,
        form_values: dict[str, object] | None = None,
        approval_token: str | None = None,
    ) -> PortalResponse:
        """Route trusted workflow actions through the independent HTTP portal."""

        return _call_portal({
            "action": action,
            "journey_id": journey_id,
            "scheme_id": scheme_id,
            "draft_id": draft_id,
            "revision": revision,
            "fingerprint": fingerprint,
            "profile": profile,
            "rule_package_version": rule_package_version,
            "deciding_rule_ids": deciding_rule_ids,
            "documents": documents,
            "applicant_reference": applicant_reference,
            "district": district,
            "dependency_version": dependency_version,
            "rules_fingerprint": rules_fingerprint,
            "document_report_fingerprint": document_report_fingerprint,
            "checklist_fingerprint": checklist_fingerprint,
            "evidence_fingerprint": evidence_fingerprint,
            "active_checklist_fingerprint": active_checklist_fingerprint,
            "typed_facts": typed_facts,
            "form_values": form_values,
            "approval_token": approval_token,
        })
