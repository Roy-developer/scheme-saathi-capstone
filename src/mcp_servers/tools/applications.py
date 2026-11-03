"""Synthetic document checks and an approval-gated local mock portal."""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.mcp_servers.tools.documents import (
    DEMO_REQUIREMENTS,
    DocumentStatus,
    assess_document_metadata,
)

PortalAction = Literal[
    "list_drafts",
    "create_draft",
    "get_draft",
    "edit_draft",
    "approve",
    "reject",
    "submit",
    "delete_journey",
]

class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortalInput(StrictInput):
    action: PortalAction
    journey_id: str = Field(min_length=1, max_length=80)
    scheme_id: str | None = Field(default=None, max_length=80)
    draft_id: str | None = Field(default=None, max_length=80)
    revision: int | None = Field(default=None, ge=1)
    fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    profile: dict[str, Any] | None = None
    rule_package_version: str | None = Field(default=None, max_length=80)
    deciding_rule_ids: list[str] | None = None
    documents: dict[str, DocumentStatus] | None = None
    applicant_reference: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)


def _database_path() -> Path:
    return Path(os.getenv(
        "SCHEME_SAATHI_APPLICATION_DB",
        "data/runtime/applications.sqlite3",
    ))


def _connect() -> sqlite3.Connection:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS application_drafts (
            draft_id TEXT PRIMARY KEY,
            journey_id TEXT NOT NULL,
            scheme_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            payload TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            approved_revision INTEGER,
            approved_fingerprint TEXT,
            rejected INTEGER NOT NULL DEFAULT 0,
            submitted_receipt TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return connection


def _canonical_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "draft_id": row["draft_id"],
        "journey_id": row["journey_id"],
        "scheme_id": row["scheme_id"],
        "revision": row["revision"],
        "draft": json.loads(row["payload"]),
        "fingerprint": row["fingerprint"],
        "approved": (
            row["approved_revision"] == row["revision"]
            and row["approved_fingerprint"] == row["fingerprint"]
        ),
        "rejected": bool(row["rejected"]),
        "receipt_id": row["submitted_receipt"],
    }


def _get_row(
    connection: sqlite3.Connection, draft_id: str, journey_id: str
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM application_drafts WHERE draft_id=? AND journey_id=?",
        (draft_id, journey_id),
    ).fetchone()
    if row is None:
        raise ValueError("Draft was not found for this journey.")
    return row


def _portal_action(data: dict[str, Any]) -> dict[str, Any]:
    request = PortalInput.model_validate(data)
    now = datetime.now(timezone.utc).isoformat()
    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if request.action == "create_draft":
            if request.scheme_id not in DEMO_REQUIREMENTS:
                raise ValueError("This scheme has no supported demo draft.")
            if request.profile is None or request.documents is None:
                raise ValueError("A profile and document report are required.")
            if not (request.applicant_reference or "Synthetic applicant").strip():
                raise ValueError("Applicant reference cannot be blank.")
            if not (request.district or "Synthetic district").strip():
                raise ValueError("District cannot be blank.")
            document_result = assess_document_metadata({
                "scheme_id": request.scheme_id,
                "documents": request.documents,
            })
            if document_result["status"] != "checklist_complete":
                raise ValueError("The demo document checklist is not complete.")
            payload = {
                "scheme_id": request.scheme_id,
                "profile": request.profile,
                "rule_package_version": request.rule_package_version,
                "deciding_rule_ids": request.deciding_rule_ids or [],
                "documents": document_result["requirements"],
                "applicant_reference": request.applicant_reference or "Synthetic applicant",
                "district": request.district or "Synthetic district",
                "declaration": (
                    "This is a synthetic demonstration draft. "
                    "It is not a government application."
                ),
            }
            draft_id = str(uuid4())
            fingerprint = _canonical_fingerprint(payload)
            connection.execute(
                """
                INSERT INTO application_drafts
                    (draft_id, journey_id, scheme_id, revision, payload,
                     fingerprint, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    draft_id, request.journey_id, request.scheme_id,
                    json.dumps(payload, ensure_ascii=False), fingerprint, now, now,
                ),
            )
            row = _get_row(connection, draft_id, request.journey_id)
            connection.commit()
            return _safe_record(row)

        if request.action == "delete_journey":
            connection.execute(
                "DELETE FROM application_drafts WHERE journey_id=?",
                (request.journey_id,),
            )
            connection.commit()
            return {"deleted": True}

        if request.action == "list_drafts":
            rows = connection.execute(
                "SELECT * FROM application_drafts WHERE journey_id=? ORDER BY created_at",
                (request.journey_id,),
            ).fetchall()
            connection.commit()
            return {"drafts": [_safe_record(row) for row in rows]}

        if not request.draft_id:
            raise ValueError("draft_id is required.")
        if request.action == "get_draft":
            row = connection.execute(
                "SELECT * FROM application_drafts WHERE draft_id=? AND journey_id=?",
                (request.draft_id, request.journey_id),
            ).fetchone()
            if row is None:
                connection.commit()
                return {"not_found": True}
            connection.commit()
            return _safe_record(row)
        row = _get_row(connection, request.draft_id, request.journey_id)

        if request.action == "edit_draft":
            if request.revision != row["revision"]:
                raise RuntimeError("The draft revision is stale.")
            if request.applicant_reference is None or request.district is None:
                raise ValueError("Applicant reference and district are required.")
            if not request.applicant_reference.strip() or not request.district.strip():
                raise ValueError("Applicant reference and district cannot be blank.")
            payload = json.loads(row["payload"])
            payload["applicant_reference"] = request.applicant_reference.strip()
            payload["district"] = request.district.strip()
            fingerprint = _canonical_fingerprint(payload)
            connection.execute(
                """
                UPDATE application_drafts
                SET revision=revision+1, payload=?, fingerprint=?,
                    approved_revision=NULL, approved_fingerprint=NULL,
                    rejected=0, updated_at=?
                WHERE draft_id=? AND journey_id=? AND revision=?
                """,
                (
                    json.dumps(payload, ensure_ascii=False), fingerprint, now,
                    request.draft_id, request.journey_id, request.revision,
                ),
            )
        elif request.action == "approve":
            if request.revision != row["revision"] or request.fingerprint != row["fingerprint"]:
                raise RuntimeError("The displayed draft is stale and cannot be approved.")
            if row["rejected"] or row["submitted_receipt"]:
                raise RuntimeError("This draft cannot be approved in its current state.")
            connection.execute(
                """
                UPDATE application_drafts
                SET approved_revision=revision, approved_fingerprint=fingerprint,
                    rejected=0, updated_at=?
                WHERE draft_id=? AND journey_id=? AND revision=? AND fingerprint=?
                """,
                (now, request.draft_id, request.journey_id, request.revision, request.fingerprint),
            )
        elif request.action == "reject":
            if request.revision != row["revision"] or request.fingerprint != row["fingerprint"]:
                raise RuntimeError("The displayed draft is stale and cannot be rejected.")
            if row["submitted_receipt"]:
                raise RuntimeError("A submitted draft cannot be rejected.")
            connection.execute(
                """
                UPDATE application_drafts
                SET rejected=1, approved_revision=NULL,
                    approved_fingerprint=NULL, updated_at=?
                WHERE draft_id=? AND journey_id=? AND revision=?
                """,
                (now, request.draft_id, request.journey_id, request.revision),
            )
        elif request.action == "submit":
            if request.revision != row["revision"] or request.fingerprint != row["fingerprint"]:
                raise RuntimeError("The displayed draft is stale and cannot be submitted.")
            if row["submitted_receipt"]:
                connection.commit()
                return _safe_record(row)
            if (
                row["approved_revision"] != row["revision"]
                or row["approved_fingerprint"] != row["fingerprint"]
                or row["rejected"]
            ):
                raise RuntimeError("This exact draft has not been approved.")
            receipt = str(uuid4())
            connection.execute(
                """
                UPDATE application_drafts SET submitted_receipt=?, updated_at=?
                WHERE draft_id=? AND journey_id=? AND revision=?
                  AND fingerprint=? AND approved_revision=revision
                  AND approved_fingerprint=fingerprint AND rejected=0
                  AND submitted_receipt IS NULL
                """,
                (receipt, now, request.draft_id, request.journey_id,
                 request.revision, request.fingerprint),
            )
        row = _get_row(connection, request.draft_id, request.journey_id)
        connection.commit()
        return _safe_record(row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def register_tools(mcp: MCPServer) -> None:
    """Register the read-only checklist and one action-based mock portal."""

    @mcp.tool()
    def mock_portal(
        action: PortalAction,
        journey_id: str,
        scheme_id: str | None = None,
        draft_id: str | None = None,
        revision: int | None = None,
        fingerprint: str | None = None,
        profile: dict[str, Any] | None = None,
        rule_package_version: str | None = None,
        deciding_rule_ids: list[str] | None = None,
        documents: dict[str, str] | None = None,
        applicant_reference: str | None = None,
        district: str | None = None,
    ) -> dict[str, Any]:
        """Manage synthetic drafts; submit succeeds only after exact approval."""

        try:
            return _portal_action({
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
            })
        except (ValidationError, ValueError, RuntimeError) as error:
            raise ToolError(str(error)) from error
