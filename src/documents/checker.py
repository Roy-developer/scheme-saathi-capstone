"""Deterministic document checker and scheme document readiness.

Everything here is plain code over the stored upload records and the
checklist result; no model reads a file or decides anything. A document is
"in place" only when a stored file still matches its saved hash and the typed
name/date (if any) agree with the confirmed profile. It does not prove the
document is real.
"""

import hashlib
import json
import unicodedata
from collections.abc import Callable
from typing import Any

from src.documents.uploads import ResolutionRecord, UploadRecord

Assess = Callable[[dict[str, Any]], dict[str, Any]]

ACKNOWLEDGEABLE_CODES = frozenset(
    {
        "name_mismatch", "date_of_birth_mismatch", "cannot_compare",
        "same_file_reused", "file_name_mismatch", "file_date_of_birth_mismatch",
    }
)
SUBMISSION_BLOCKING_CODES = frozenset(
    {
        "file_problem",
        "no_file",
        "name_mismatch",
        "date_of_birth_mismatch",
        "same_file_reused",
        "file_name_mismatch",
        "file_date_of_birth_mismatch",
    }
)
NOT_VERIFIED_NOTICE = (
    "Document checker: it confirms that files are stored and that typed names "
    "and dates agree. Values read from a file are only suggestions and are "
    "compared with the profile; it does not verify that a document is "
    "authentic."
)


def _normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _file_value_codes(
    extraction: dict[str, Any] | None,
    profile_name: str | None,
    profile_date_of_birth: str | None,
) -> list[str]:
    """Compare values read from the stored file with the confirmed profile."""

    if not extraction:
        return []
    codes = []
    name = extraction.get("name")
    if name and profile_name and _normalized_name(name) != _normalized_name(profile_name):
        codes.append("file_name_mismatch")
    dob = extraction.get("date_of_birth")
    if dob and profile_date_of_birth and dob != profile_date_of_birth:
        codes.append("file_date_of_birth_mismatch")
    return codes


def issue_fingerprint(
    *,
    document_id: str,
    code: str,
    upload_sha256: str | None,
    profile_name: str | None,
    entered_name: str | None,
    entered_date: str | None,
    checklist_fingerprint: str,
    file_name: str | None = None,
    file_date: str | None = None,
) -> str:
    """Hash everything an acknowledgment depends on; any change voids it."""

    values = {
        "document_id": document_id,
        "code": code,
        "upload_sha256": upload_sha256,
        "profile_name": (profile_name or "").strip(),
        "entered_name": (entered_name or "").strip(),
        "entered_date": entered_date or "",
        "checklist_fingerprint": checklist_fingerprint,
    }
    if code.startswith("file_") and code != "file_problem":
        values["file_name"] = (file_name or "").strip()
        values["file_date"] = file_date or ""
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_submission_ready(report: dict[str, Any]) -> bool:
    """Return whether a document report permits mock-portal submission.

    Only a complete report, or a complete report with acknowledged advisory
    findings, can proceed. Integrity, availability, reuse, and profile-value
    mismatches remain blocking even if someone has acknowledged them.
    """

    if report["overall"] not in {"complete", "complete_with_acknowledged_warnings"}:
        return False
    return not any(
        issue["code"] in SUBMISSION_BLOCKING_CODES
        for group in report["groups"]
        for document in group["documents"]
        for issue in document["issues"]
    )


def _document_issues(
    document_id: str,
    *,
    upload: UploadRecord | None,
    is_intact: bool,
    declared: str | None,
    status: str,
    discrepancy_codes: set[str],
    shares_file: bool = False,
    file_codes: list[str] | None = None,
) -> list[str]:
    codes: list[str] = []
    if upload is not None and not is_intact:
        codes.append("file_problem")
    if upload is None and declared == "available":
        codes.append("no_file")
    if upload is not None and is_intact:
        if shares_file:
            codes.append("same_file_reused")
        codes.extend(sorted(discrepancy_codes))
        codes.extend(file_codes or [])
        if status == "unknown" and not discrepancy_codes:
            codes.append("cannot_compare")
    return codes


def check_scheme_documents(
    scheme_id: str,
    *,
    assess: Assess,
    uploads: dict[str, UploadRecord],
    intact: set[str],
    declared: dict[str, str],
    profile_name: str | None,
    document_metadata: dict[str, dict[str, Any]],
    profile_date_of_birth: str | None,
    profile_conditions: dict[str, bool | None],
    typed_facts: dict[str, object] | None,
    resolutions: list[ResolutionRecord],
    extractions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one scheme's checker report from stored files and typed fields."""

    base_request = {
        "scheme_id": scheme_id,
        "documents": {},
        "profile_name": profile_name,
        "profile_date_of_birth": profile_date_of_birth,
        "document_metadata": {},
        "profile_conditions": profile_conditions,
        "typed_facts": typed_facts,
    }
    base = assess(base_request)
    if base["status"] == "requirements_unverified":
        report = {
            "scheme_id": scheme_id,
            "overall": "requirements_unverified",
            "message": base["message"],
            "notice": NOT_VERIFIED_NOTICE,
            "demo_only": base["demo_only"],
            "checklist_version": base["checklist_version"],
            "checklist_fingerprint": base["checklist_fingerprint"],
            "groups": [],
            "citations": [],
            "counts": {"required": 0, "in_place": 0, "missing": 0, "attention": 0},
            "missing_labels": [],
        }
        report["submission_ready"] = False
        return report

    document_ids = {item["document_id"] for item in base["requirements"]}
    statuses = {
        document_id: "available" if document_id in intact else "missing"
        for document_id in document_ids
    }
    metadata = {
        document_id: fields
        for document_id, fields in document_metadata.items()
        if document_id in intact
    }
    assessment = assess({
        **base_request, "documents": statuses, "document_metadata": metadata,
    })
    discrepancies: dict[str, set[str]] = {}
    for discrepancy in assessment["discrepancies"]:
        discrepancies.setdefault(discrepancy["document_id"], set()).add(
            discrepancy["code"]
        )
    resolution_by_issue = {
        (resolution.document_id, resolution.issue_code): resolution
        for resolution in resolutions
    }
    # The same file attached to two of this scheme's documents is suspicious.
    sha_counts: dict[str, int] = {}
    for document_id in document_ids & intact:
        upload = uploads.get(document_id)
        if upload is not None:
            sha_counts[upload.sha256] = sha_counts.get(upload.sha256, 0) + 1

    groups: list[dict[str, Any]] = []
    for group in assessment["groups"]:
        documents = []
        for item in group["alternatives"]:
            document_id = item["document_id"]
            upload = uploads.get(document_id)
            extracted = (extractions or {}).get(document_id)
            codes = _document_issues(
                document_id,
                upload=upload,
                is_intact=document_id in intact,
                declared=declared.get(document_id),
                status=item["status"],
                discrepancy_codes=discrepancies.get(document_id, set()),
                shares_file=(
                    upload is not None and sha_counts.get(upload.sha256, 0) > 1
                ),
                file_codes=_file_value_codes(
                    extracted, profile_name, profile_date_of_birth
                ),
            )
            entered = metadata.get(document_id, {})
            issues = []
            for code in codes:
                fingerprint = issue_fingerprint(
                    document_id=document_id,
                    code=code,
                    upload_sha256=upload.sha256 if upload else None,
                    profile_name=profile_name,
                    entered_name=entered.get("name"),
                    entered_date=(
                        str(entered["date_of_birth"])
                        if entered.get("date_of_birth") else None
                    ),
                    checklist_fingerprint=assessment["active_fingerprint"],
                    file_name=(extracted or {}).get("name"),
                    file_date=(extracted or {}).get("date_of_birth"),
                )
                resolution = resolution_by_issue.get((document_id, code))
                acknowledged = (
                    resolution is not None and resolution.fingerprint == fingerprint
                )
                issues.append({
                    "issue_id": f"{document_id}:{code}",
                    "document_id": document_id,
                    "code": code,
                    "can_acknowledge": code in ACKNOWLEDGEABLE_CODES,
                    "fingerprint": fingerprint,
                    "acknowledged": acknowledged,
                    "resolution": (
                        resolution.model_dump(mode="json") if acknowledged else None
                    ),
                })
            unresolved = [issue for issue in issues if not issue["acknowledged"]]
            if document_id not in intact:
                state = "needs_attention" if "file_problem" in codes else "missing"
            elif unresolved:
                state = "needs_attention"
            elif issues:
                state = "acknowledged"
            else:
                state = "in_place"
            documents.append({
                "document_id": document_id,
                "label": item["label"],
                "labels": item["labels"],
                "state": state,
                "upload": upload.model_dump(mode="json") if upload else None,
                "issues": issues,
            })
        states = {document["state"] for document in documents}
        if group["applicable"] is False:
            group_state = "not_applicable"
        elif group["applicable"] is None:
            group_state = "unknown"
        elif "in_place" in states:
            group_state = "in_place"
        elif "acknowledged" in states:
            group_state = "acknowledged"
        elif "needs_attention" in states:
            group_state = "needs_attention"
        else:
            group_state = "missing"
        groups.append({
            "requirement_id": group["requirement_id"],
            "label": group["label"],
            "labels": group["labels"],
            "applicable": group["applicable"],
            "state": group_state,
            "any_one_of": len(documents) > 1,
            "documents": documents,
        })

    applicable = [group for group in groups if group["state"] != "not_applicable"]
    group_states = [group["state"] for group in applicable]
    if "missing" in group_states:
        overall = "incomplete"
    elif "needs_attention" in group_states or "unknown" in group_states:
        overall = "needs_attention"
    elif "acknowledged" in group_states:
        overall = "complete_with_acknowledged_warnings"
    else:
        overall = "complete"
    report = {
        "scheme_id": scheme_id,
        "overall": overall,
        "message": assessment["message"],
        "notice": NOT_VERIFIED_NOTICE,
        "demo_only": assessment["demo_only"],
        "checklist_version": assessment["checklist_version"],
        "checklist_fingerprint": assessment["active_fingerprint"],
        "groups": groups,
        "citations": assessment["citations"],
        "counts": {
            "required": len(applicable),
            "in_place": sum(state in {"in_place", "acknowledged"} for state in group_states),
            "missing": group_states.count("missing"),
            "attention": sum(state in {"needs_attention", "unknown"} for state in group_states),
        },
        "missing_labels": [
            group["labels"] for group in applicable if group["state"] == "missing"
        ],
    }
    report["submission_ready"] = is_submission_ready(report)
    return report


def readiness_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Summarize how many required document groups a scheme already has."""

    counts = report["counts"]
    if report["overall"] == "requirements_unverified":
        state = "unverified"
    elif report["overall"] in {"complete", "complete_with_acknowledged_warnings"}:
        state = "ready"
    elif counts["in_place"] > 0:
        state = "partial"
    else:
        state = "none"
    return {
        "scheme_id": report["scheme_id"],
        "state": state,
        "in_place": counts["in_place"],
        "required": counts["required"],
        "missing_labels": report["missing_labels"],
        "overall": report["overall"],
    }
