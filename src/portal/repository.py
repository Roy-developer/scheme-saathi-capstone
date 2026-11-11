"""SQLite repository used only by the independent synthetic portal service."""

import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.documents.checklists import (
    CHECKLIST_DIRECTORY,
    ChecklistSnapshot,
    load_checklist_snapshot,
)
from src.documents.publication import checklist_publication_lock
from src.documents.forms import build_form_fields, load_mock_form_snapshot
from src.mcp_servers.tools.documents import (
    DocumentStatus,
    assess_document_metadata,
)
from src.mcp_servers.rule_data import get_active_rule_data
from src.rules.bundles import bundle_fingerprint
from src.rules.facts import TypedFactStore

PortalAction = Literal[
    "list_drafts",
    "create_draft",
    "get_draft",
    "get_status",
    "edit_draft",
    "approve",
    "reject",
    "submit",
    "delete_journey",
    "begin_profile_change",
    "reconcile_profile",
    "bind_documents",
    "dependency_status",
    "bind_rules",
]
APPROVAL_TTL_SECONDS = 15 * 60

class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortalInput(StrictInput):
    action: PortalAction
    journey_id: str = Field(min_length=1, max_length=80)
    scheme_id: str | None = Field(default=None, max_length=80)
    draft_id: str | None = Field(default=None, max_length=80)
    revision: int | None = Field(default=None, ge=1)
    fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    profile: dict[str, object] | None = None
    rule_package_version: str | None = Field(default=None, max_length=80)
    deciding_rule_ids: list[str] | None = None
    documents: dict[str, DocumentStatus] | None = None
    applicant_reference: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    dependency_version: int | None = Field(default=None, ge=0)
    rules_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    document_report_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    checklist_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    evidence_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    active_checklist_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    typed_facts: dict[str, object] | None = None
    form_values: dict[str, object] | None = None
    approval_token: str | None = Field(default=None, min_length=32, max_length=80)


def _database_path() -> Path:
    return Path(os.getenv(
        "SCHEME_SAATHI_PORTAL_DB",
        os.getenv("SCHEME_SAATHI_APPLICATION_DB", "data/runtime/portal.sqlite3"),
    ))


def _load_current_checklist(scheme_id: str) -> ChecklistSnapshot:
    """Load checklist conditions against the exact registry used by rule tools."""

    snapshot = load_checklist_snapshot(scheme_id)
    if snapshot.checklist is not None:
        try:
            rule_data = get_active_rule_data()
            snapshot.checklist.validate_registry(
                rule_data.registry, rule_data.get_bundle(scheme_id)
            )
        except ValueError:
            return snapshot.model_copy(update={
                "checklist": None,
                "trust_status": "requirements_unverified",
                "citations": [],
                "notice": "Document requirements are not verified.",
            })
    return snapshot


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
            approval_issued_at TEXT,
            approval_expires_at TEXT,
            approval_token TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute("""
        CREATE TABLE IF NOT EXISTS journey_dependencies (
            journey_id TEXT PRIMARY KEY, profile_version INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0)
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS document_dependencies (
            journey_id TEXT NOT NULL, scheme_id TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 0, report TEXT NOT NULL,
            checklist_fingerprint TEXT NOT NULL DEFAULT '',
            evidence_fingerprint TEXT NOT NULL DEFAULT '',
            active_checklist_fingerprint TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (journey_id, scheme_id))
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS rule_dependencies (
            journey_id TEXT NOT NULL, scheme_id TEXT NOT NULL,
            version INTEGER NOT NULL, fingerprint TEXT NOT NULL,
            PRIMARY KEY (journey_id, scheme_id))
    """)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(application_drafts)")}
    if "stale" not in columns:
        connection.execute("ALTER TABLE application_drafts ADD COLUMN stale INTEGER NOT NULL DEFAULT 0")
    document_columns = {
        row["name"] for row in connection.execute(
            "PRAGMA table_info(document_dependencies)"
        )
    }
    for column in (
        "checklist_fingerprint", "evidence_fingerprint",
        "active_checklist_fingerprint",
    ):
        if column not in document_columns:
            connection.execute(
                f"ALTER TABLE document_dependencies ADD COLUMN {column} "
                "TEXT NOT NULL DEFAULT ''"
            )
    for column, declaration in (
        ("approval_issued_at", "TEXT"),
        ("approval_expires_at", "TEXT"),
        ("approval_token", "TEXT"),
        ("creation_fingerprint", "TEXT"),
    ):
        if column not in columns:
            connection.execute(
                f"ALTER TABLE application_drafts ADD COLUMN {column} {declaration}"
            )
    return connection


def _canonical_fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_record(row: sqlite3.Row) -> dict[str, object]:
    expires_at = row["approval_expires_at"]
    approval_expired = _approval_expired(row)
    return {
        "draft_id": row["draft_id"],
        "journey_id": row["journey_id"],
        "scheme_id": row["scheme_id"],
        "revision": row["revision"],
        "draft": json.loads(row["payload"]),
        "fingerprint": row["fingerprint"],
        "approved": (
            not row["stale"]
            and not approval_expired
            and
            row["approved_revision"] == row["revision"]
            and row["approved_fingerprint"] == row["fingerprint"]
        ),
        "rejected": bool(row["rejected"]),
        "receipt_id": row["submitted_receipt"],
        "stale": bool(row["stale"]),
        "approval_expires_at": expires_at,
        "approval_expired": approval_expired,
        # This is an internal workflow credential; public API responses remove it.
        "approval_token": row["approval_token"],
    }


def _approval_expired(row: sqlite3.Row) -> bool:
    """Fail closed on elapsed, malformed, or implausibly extended approvals."""

    expires_at = row["approval_expires_at"]
    issued_at = row["approval_issued_at"]
    if not expires_at or not issued_at:
        return row["approved_revision"] is not None
    try:
        issued = datetime.fromisoformat(issued_at)
        expires = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    if issued.tzinfo is None or expires.tzinfo is None:
        return True
    return (
        expires <= datetime.now(timezone.utc)
        or expires <= issued
        or expires > issued + timedelta(seconds=APPROVAL_TTL_SECONDS)
    )


def _snapshot_matches_request(
    snapshot: ChecklistSnapshot, request: PortalInput
) -> bool:
    """Check checklist digests when a caller supplies them."""

    provided = (
        request.checklist_fingerprint,
        request.evidence_fingerprint,
        request.active_checklist_fingerprint,
    )
    expected = (
        snapshot.checklist_fingerprint,
        snapshot.evidence_fingerprint,
        snapshot.active_fingerprint,
    )
    if any(value is None for value in provided):
        return all(value is None for value in provided)
    return provided == expected


def _refresh_document_dependency(
    connection: sqlite3.Connection,
    journey_id: str,
    scheme_id: str,
    snapshot: ChecklistSnapshot,
    now: str,
) -> int:
    """Persist monotonic checklist changes and revoke affected unsent drafts."""

    previous = connection.execute(
        "SELECT * FROM document_dependencies WHERE journey_id=? AND scheme_id=?",
        (journey_id, scheme_id),
    ).fetchone()
    draft_rows = connection.execute(
        """SELECT payload, stale FROM application_drafts
           WHERE journey_id=? AND scheme_id=? AND submitted_receipt IS NULL""",
        (journey_id, scheme_id),
    ).fetchall()
    current_fingerprint = snapshot.active_fingerprint
    saved_report_fingerprint = (
        json.loads(previous["report"]).get("fingerprint")
        if previous is not None
        else None
    )
    draft_changed = any(
        not row["stale"]
        and (
            json.loads(row["payload"]).get("active_checklist_fingerprint")
            != current_fingerprint
            or json.loads(row["payload"]).get("document_report_fingerprint")
            != saved_report_fingerprint
        )
        for row in draft_rows
    )
    changed = (
        previous is None
        or previous["active_checklist_fingerprint"] != current_fingerprint
        or draft_changed
    )
    version = (previous["version"] if previous else 0) + int(changed)
    if previous is None:
        connection.execute(
            """INSERT INTO document_dependencies
               (journey_id, scheme_id, version, report, checklist_fingerprint,
                evidence_fingerprint, active_checklist_fingerprint)
               VALUES (?, ?, ?, '{}', ?, ?, ?)""",
            (
                journey_id, scheme_id, version, snapshot.checklist_fingerprint,
                snapshot.evidence_fingerprint, current_fingerprint,
            ),
        )
    else:
        connection.execute(
            """UPDATE document_dependencies SET version=?,
               checklist_fingerprint=?, evidence_fingerprint=?,
               active_checklist_fingerprint=?
               WHERE journey_id=? AND scheme_id=?""",
            (
                version, snapshot.checklist_fingerprint,
                snapshot.evidence_fingerprint, current_fingerprint,
                journey_id, scheme_id,
            ),
        )
    if changed:
        _revoke_unsubmitted_approvals(connection, now, journey_id, scheme_id)
    return version


def _assert_snapshot_unchanged(
    scheme_id: str, expected_fingerprint: str
) -> None:
    """Recheck files before commit; external publishers are not synchronized."""

    latest = _load_current_checklist(scheme_id)
    if latest.active_fingerprint != expected_fingerprint:
        raise RuntimeError("The active document checklist changed during this action.")


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


def _revoke_unsubmitted_approvals(
    connection: sqlite3.Connection,
    now: str,
    journey_id: str,
    scheme_id: str | None = None,
) -> None:
    """Mark unsubmitted drafts stale and cancel their approvals.

    Used whenever something the approval depended on changes (answers,
    rules or documents). Submitted drafts keep their receipts.

    Args:
        scheme_id: Limit to one scheme, or None for the whole journey.
    """

    scheme_filter = "AND scheme_id=? " if scheme_id is not None else ""
    connection.execute(
        f"""UPDATE application_drafts SET stale=1, approved_revision=NULL,
           approved_fingerprint=NULL, approval_expires_at=NULL,
           approval_issued_at=NULL, approval_token=NULL, updated_at=?
           WHERE journey_id=? {scheme_filter}AND submitted_receipt IS NULL""",
        (now, journey_id) + ((scheme_id,) if scheme_id is not None else ()),
    )


def _recheck_checklist(
    connection: sqlite3.Connection, journey_id: str, scheme_id: str, now: str,
) -> ChecklistSnapshot:
    """Reload a scheme's checklist, record any change, and fail if it moved.

    Returns:
        The checklist snapshot that was checked.
    """

    snapshot = _load_current_checklist(scheme_id)
    _refresh_document_dependency(connection, journey_id, scheme_id, snapshot, now)
    _assert_snapshot_unchanged(scheme_id, snapshot.active_fingerprint)
    return snapshot


def _portal_action_transaction(data: dict[str, object]) -> dict[str, object]:
    request = PortalInput.model_validate(data)
    now = datetime.now(timezone.utc).isoformat()
    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if request.action not in {
            "list_drafts", "get_draft", "get_status", "dependency_status", "delete_journey",
        }:
            connection.execute(
                "INSERT OR IGNORE INTO journey_dependencies(journey_id) VALUES (?)",
                (request.journey_id,),
            )
        dependency = connection.execute(
            "SELECT * FROM journey_dependencies WHERE journey_id=?", (request.journey_id,)
        ).fetchone() or {"profile_version": 0, "blocked": 0}
        if request.action == "dependency_status":
            connection.commit()
            return {"dependency_version": dependency["profile_version"],
                    "blocked": bool(dependency["blocked"])}
        if request.action == "begin_profile_change":
            if dependency["blocked"]:
                raise RuntimeError("Profile reconciliation is required before another change.")
            if (
                request.dependency_version is not None
                and request.dependency_version != dependency["profile_version"] + 1
            ):
                raise RuntimeError("Profile dependency version is stale.")
            connection.execute(
                "UPDATE journey_dependencies SET profile_version=profile_version+1, blocked=1 WHERE journey_id=?",
                (request.journey_id,),
            )
            _revoke_unsubmitted_approvals(connection, now, request.journey_id)
            connection.commit()
            return {"dependency_version": dependency["profile_version"] + 1}
        if request.action == "reconcile_profile":
            if request.dependency_version != dependency["profile_version"]:
                raise RuntimeError("Profile dependency version is stale.")
            connection.execute(
                "UPDATE journey_dependencies SET blocked=0 WHERE journey_id=?",
                (request.journey_id,),
            )
            connection.commit()
            return {"dependency_version": dependency["profile_version"]}
        if request.action not in {
            "list_drafts", "get_draft", "get_status", "delete_journey", "bind_rules"
        } and dependency["blocked"]:
            raise RuntimeError("Profile reconciliation is required before writes.")
        if (
            request.dependency_version is not None
            and request.dependency_version != dependency["profile_version"]
        ):
            raise RuntimeError("Profile dependency version is stale.")
        if request.action == "bind_rules":
            if request.scheme_id is None or request.rules_fingerprint is None:
                raise ValueError("Scheme and rule fingerprint are required.")
            previous = connection.execute(
                "SELECT * FROM rule_dependencies WHERE journey_id=? AND scheme_id=?",
                (request.journey_id, request.scheme_id),
            ).fetchone()
            version = previous["version"] if previous else 0
            if previous is None or previous["fingerprint"] != request.rules_fingerprint:
                version += 1
                connection.execute(
                    """INSERT INTO rule_dependencies VALUES (?, ?, ?, ?)
                       ON CONFLICT(journey_id, scheme_id) DO UPDATE SET
                       version=excluded.version, fingerprint=excluded.fingerprint""",
                    (request.journey_id, request.scheme_id, version, request.rules_fingerprint),
                )
                _revoke_unsubmitted_approvals(
                    connection, now, request.journey_id, request.scheme_id
                )
            connection.commit()
            return {"dependency_version": version}
        if request.action == "bind_documents":
            if request.scheme_id is None or request.documents is None:
                raise ValueError("Scheme and document report are required.")
            snapshot = _load_current_checklist(request.scheme_id)
            if not _snapshot_matches_request(snapshot, request):
                _refresh_document_dependency(
                    connection, request.journey_id, request.scheme_id, snapshot, now
                )
                connection.commit()
                raise RuntimeError(
                    "The document report is not bound to the current checklist."
                )
            report = json.dumps({
                "documents": request.documents,
                "fingerprint": request.document_report_fingerprint,
                "checklist_fingerprint": snapshot.checklist_fingerprint,
                "evidence_fingerprint": snapshot.evidence_fingerprint,
                "active_checklist_fingerprint": snapshot.active_fingerprint,
            }, sort_keys=True)
            previous = connection.execute(
                "SELECT * FROM document_dependencies WHERE journey_id=? AND scheme_id=?",
                (request.journey_id, request.scheme_id),
            ).fetchone()
            version = previous["version"] if previous else 0
            changed = previous is None or (
                previous["report"] != report
                or previous["active_checklist_fingerprint"]
                != snapshot.active_fingerprint
            )
            if changed:
                version += 1
                connection.execute(
                    """INSERT INTO document_dependencies
                       (journey_id, scheme_id, version, report, checklist_fingerprint,
                        evidence_fingerprint, active_checklist_fingerprint)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(journey_id, scheme_id) DO UPDATE SET
                       version=excluded.version, report=excluded.report,
                       checklist_fingerprint=excluded.checklist_fingerprint,
                       evidence_fingerprint=excluded.evidence_fingerprint,
                       active_checklist_fingerprint=excluded.active_checklist_fingerprint""",
                    (
                        request.journey_id, request.scheme_id, version, report,
                        snapshot.checklist_fingerprint, snapshot.evidence_fingerprint,
                        snapshot.active_fingerprint,
                    ),
                )
                _revoke_unsubmitted_approvals(
                    connection, now, request.journey_id, request.scheme_id
                )
            _assert_snapshot_unchanged(
                request.scheme_id, snapshot.active_fingerprint
            )
            connection.commit()
            return {"dependency_version": version}
        if request.action == "create_draft":
            if request.scheme_id is None:
                raise ValueError("Scheme is required.")
            if request.profile is None or request.documents is None:
                raise ValueError("A profile and document report are required.")
            rule_data = get_active_rule_data()
            bundle = rule_data.get_bundle(request.scheme_id)
            snapshot = _load_current_checklist(request.scheme_id)
            if (
                not snapshot.usable
                or not _snapshot_matches_request(snapshot, request)
            ):
                _refresh_document_dependency(
                    connection, request.journey_id, request.scheme_id, snapshot, now
                )
                connection.commit()
                raise RuntimeError(
                    "Document requirements are not verified against the current checklist."
                )
            dependency_report = connection.execute(
                "SELECT report FROM document_dependencies WHERE journey_id=? AND scheme_id=?",
                (request.journey_id, request.scheme_id),
            ).fetchone()
            saved_report_fingerprint = (
                json.loads(dependency_report["report"]).get("fingerprint")
                if dependency_report is not None
                else None
            )
            if request.document_report_fingerprint is not None:
                if saved_report_fingerprint != request.document_report_fingerprint:
                    raise RuntimeError(
                        "Recheck the documents against the current checklist."
                    )
            if not (request.applicant_reference or "Synthetic applicant").strip():
                raise ValueError("Applicant reference cannot be blank.")
            if not (request.district or "Synthetic district").strip():
                raise ValueError("District cannot be blank.")
            document_result = assess_document_metadata({
                "scheme_id": request.scheme_id,
                "documents": request.documents,
                "typed_facts": request.typed_facts,
                "profile_conditions": {
                    field: request.profile.get(field)
                    for field in ("is_widow", "bpl_card_shown")
                    if isinstance(request.profile.get(field), bool)
                },
            }, snapshot=snapshot, registry=rule_data.registry, bundle=bundle)
            if document_result["status"] != "checklist_complete":
                raise ValueError("The active document checklist is not complete.")
            form_snapshot = load_mock_form_snapshot(
                request.scheme_id, rule_data.registry, bundle=bundle
            )
            if form_snapshot.mapping is None:
                raise RuntimeError(form_snapshot.notice)
            fact_store = None
            if request.typed_facts is None:
                fact_values = {
                    fact_id: (
                        rule_data.registry.get(fact_id).validate_value(
                            request.profile[fact_id]
                        )
                        if request.profile.get(fact_id) is not None
                        else None
                    )
                    for fact_id in bundle.fact_ids
                }
                fact_versions = {
                    fact_id: rule_data.registry.get(fact_id).version
                    for fact_id in bundle.fact_ids
                }
            else:
                fact_store = TypedFactStore.from_wire(
                    request.typed_facts, rule_data.registry
                )
                fact_values = {
                    fact_id: (
                        state.value if state.status == "known" else None
                    )
                    for fact_id, state in fact_store.facts.items()
                }
                fact_versions = {
                    fact_id: state.definition_version
                    for fact_id, state in fact_store.facts.items()
                }
            form_fields, missing_form_fields = build_form_fields(
                form_snapshot, rule_data.registry, fact_values,
                request.form_values or {},
                bundle=bundle,
                typed_store=fact_store,
            )
            if missing_form_fields:
                raise ValueError(
                    "Required synthetic form fields are missing: "
                    + ", ".join(missing_form_fields)
                )
            document_version = _refresh_document_dependency(
                connection, request.journey_id, request.scheme_id, snapshot, now
            )
            payload = {
                "scheme_id": request.scheme_id,
                "profile": request.profile,
                "rule_package_version": request.rule_package_version,
                "bundle_version": bundle.bundle_version,
                "bundle_fingerprint": bundle_fingerprint(bundle),
                "registry_version": bundle.registry_version,
                "registry_sha256": bundle.registry_sha256,
                "rule_package_sha256": bundle.package_sha256,
                "deciding_rule_ids": request.deciding_rule_ids or [],
                "documents": document_result["requirements"],
                "document_groups": document_result["groups"],
                "document_citations": document_result["citations"],
                "requirements_status": snapshot.trust_status,
                "document_report_fingerprint": request.document_report_fingerprint,
                "checklist_version": snapshot.checklist_version,
                "checklist_fingerprint": snapshot.checklist_fingerprint,
                "evidence_fingerprint": snapshot.evidence_fingerprint,
                "active_checklist_fingerprint": snapshot.active_fingerprint,
                "form_version": form_snapshot.mapping.form_version,
                "form_mapping_fingerprint": form_snapshot.fingerprint,
                "form_status": form_snapshot.mapping.status,
                "form_fields": form_fields,
                "form_field_types": {
                    field.field_id: field.value_type
                    for field in form_snapshot.mapping.fields
                },
                "fact_definition_versions": fact_versions,
                "applicant_reference": request.applicant_reference or "Synthetic applicant",
                "district": request.district or "Synthetic district",
                "declaration": (
                    "This is a synthetic demonstration draft. "
                    "It is not a government application."
                ),
                "profile_version": dependency["profile_version"],
                "document_version": document_version,
                "rules_version": (
                    connection.execute(
                        "SELECT version FROM rule_dependencies WHERE journey_id=? AND scheme_id=?",
                        (request.journey_id, request.scheme_id),
                    ).fetchone() or {"version": 0}
                )["version"],
            }
            draft_id = str(uuid4())
            fingerprint = _canonical_fingerprint(payload)
            existing = connection.execute(
                """SELECT * FROM application_drafts
                   WHERE journey_id=? AND scheme_id=?
                   AND COALESCE(creation_fingerprint, fingerprint)=?
                   ORDER BY created_at LIMIT 1""",
                (request.journey_id, request.scheme_id, fingerprint),
            ).fetchone()
            if existing is not None:
                _assert_snapshot_unchanged(
                    request.scheme_id, snapshot.active_fingerprint
                )
                connection.commit()
                return _safe_record(existing)
            connection.execute(
                """
                INSERT INTO application_drafts
                    (draft_id, journey_id, scheme_id, revision, payload,
                     fingerprint, creation_fingerprint, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id, request.journey_id, request.scheme_id,
                    json.dumps(payload, ensure_ascii=False), fingerprint,
                    fingerprint, now, now,
                ),
            )
            row = _get_row(connection, draft_id, request.journey_id)
            _assert_snapshot_unchanged(
                request.scheme_id, snapshot.active_fingerprint
            )
            connection.commit()
            return _safe_record(row)

        if request.action == "delete_journey":
            connection.execute(
                "DELETE FROM application_drafts WHERE journey_id=?",
                (request.journey_id,),
            )
            connection.execute(
                "DELETE FROM document_dependencies WHERE journey_id=?",
                (request.journey_id,),
            )
            connection.execute(
                "DELETE FROM rule_dependencies WHERE journey_id=?",
                (request.journey_id,),
            )
            connection.execute(
                "DELETE FROM journey_dependencies WHERE journey_id=?",
                (request.journey_id,),
            )
            connection.commit()
            return {"deleted": True}

        if request.action == "list_drafts":
            rows = connection.execute(
                "SELECT * FROM application_drafts WHERE journey_id=? ORDER BY created_at",
                (request.journey_id,),
            ).fetchall()
            for draft_row in rows:
                if draft_row["submitted_receipt"]:
                    continue
                snapshot = _recheck_checklist(
                    connection, request.journey_id, draft_row["scheme_id"], now
                )
            rows = connection.execute(
                "SELECT * FROM application_drafts WHERE journey_id=? ORDER BY created_at",
                (request.journey_id,),
            ).fetchall()
            connection.commit()
            return {"drafts": [_safe_record(row) for row in rows]}

        if not request.draft_id:
            raise ValueError("draft_id is required.")
        if request.action in {"get_draft", "get_status"}:
            row = connection.execute(
                "SELECT * FROM application_drafts WHERE draft_id=? AND journey_id=?",
                (request.draft_id, request.journey_id),
            ).fetchone()
            if row is None:
                connection.commit()
                return {"not_found": True}
            if not row["submitted_receipt"]:
                snapshot = _recheck_checklist(
                    connection, request.journey_id, row["scheme_id"], now
                )
                row = _get_row(connection, request.draft_id, request.journey_id)
            connection.commit()
            record = _safe_record(row)
            if request.action == "get_status":
                return {
                    "draft_id": record["draft_id"],
                    "status": (
                        "submitted"
                        if record["receipt_id"]
                        else "stale"
                        if record["stale"]
                        else "approved"
                        if record["approved"]
                        else "expired"
                        if record["approval_expired"]
                        else "rejected"
                        if record["rejected"]
                        else "draft"
                    ),
                    "receipt_id": record["receipt_id"],
                }
            return record
        row = _get_row(connection, request.draft_id, request.journey_id)
        if request.action == "submit" and (
            request.revision != row["revision"]
            or request.fingerprint != row["fingerprint"]
        ):
            raise RuntimeError("The displayed draft is stale and cannot be submitted.")
        if request.action == "submit" and row["submitted_receipt"]:
            if (
                request.approval_token
                and row["approval_token"]
                and hmac.compare_digest(request.approval_token, row["approval_token"])
            ):
                connection.commit()
                return _safe_record(row)
            raise RuntimeError("This submission authorization was already consumed.")
        if not row["submitted_receipt"]:
            snapshot = _recheck_checklist(
                connection, request.journey_id, row["scheme_id"], now
            )
            row = _get_row(connection, request.draft_id, request.journey_id)
            if request.action in {"edit_draft", "approve", "submit"} and not snapshot.usable:
                connection.commit()
                raise RuntimeError(
                    "Document requirements are not verified; this draft cannot proceed."
                )
        if row["stale"] and not row["submitted_receipt"]:
            connection.commit()
            raise RuntimeError("Dependencies changed. Create and approve a fresh draft.")

        if request.action == "edit_draft":
            if row["submitted_receipt"]:
                raise RuntimeError("A submitted draft cannot be edited.")
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
                    approval_issued_at=NULL, approval_expires_at=NULL,
                    approval_token=NULL,
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
            expires_at = (
                datetime.fromisoformat(now)
                + timedelta(seconds=APPROVAL_TTL_SECONDS)
            ).isoformat()
            approval_token = uuid4().hex
            connection.execute(
                """
                UPDATE application_drafts
                SET approved_revision=revision, approved_fingerprint=fingerprint,
                    approval_issued_at=?, approval_expires_at=?, approval_token=?,
                    rejected=0, updated_at=?
                WHERE draft_id=? AND journey_id=? AND revision=? AND fingerprint=?
                """,
                (
                    now, expires_at, approval_token, now, request.draft_id,
                    request.journey_id, request.revision, request.fingerprint,
                ),
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
                    approved_fingerprint=NULL, approval_expires_at=NULL,
                    approval_issued_at=NULL, approval_token=NULL, updated_at=?
                WHERE draft_id=? AND journey_id=? AND revision=?
                """,
                (now, request.draft_id, request.journey_id, request.revision),
            )
        elif request.action == "submit":
            if request.revision != row["revision"] or request.fingerprint != row["fingerprint"]:
                raise RuntimeError("The displayed draft is stale and cannot be submitted.")
            if _approval_expired(row):
                raise RuntimeError("The human approval has expired; review the exact draft again.")
            if (
                row["approved_revision"] != row["revision"]
                or row["approved_fingerprint"] != row["fingerprint"]
                or row["rejected"]
                or not request.approval_token
                or not row["approval_token"]
                or not hmac.compare_digest(request.approval_token, row["approval_token"])
            ):
                raise RuntimeError("This exact draft has no current submission authorization.")
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
        if request.action in {"edit_draft", "approve", "submit"}:
            _assert_snapshot_unchanged(
                request.scheme_id or row["scheme_id"],
                snapshot.active_fingerprint,
            )
        row = _get_row(connection, request.draft_id, request.journey_id)
        connection.commit()
        return _safe_record(row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _portal_action(data: dict[str, object]) -> dict[str, object]:
    """Serialize portal transactions with supported checklist publication."""

    with checklist_publication_lock(CHECKLIST_DIRECTORY):
        return _portal_action_transaction(data)
