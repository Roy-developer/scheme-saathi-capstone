"""HTTP routes for synthetic document uploads, the checker and readiness.

Uploaded files are stored and hashed. On request, an OCR engine reads a file to
suggest a name and date of birth (``extraction.py``); a person must confirm
them. The checker and readiness views are deterministic and do not change
eligibility.
"""

import asyncio
import hashlib
import hmac
import os
from typing import Any
from urllib.parse import quote, unquote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field

from src.api.applications import (
    DocumentMetadata,
    DocumentStatus,
    StrictApplicationModel,
)
from src.documents.checker import (
    ACKNOWLEDGEABLE_CODES,
    check_scheme_documents,
    readiness_from_report,
)
from src.documents.checklists import load_checklist_snapshot
from src.documents.extraction import ExtractionError, get_extractor, parse_suggestion
from src.documents.uploads import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    UploadError,
    UploadStore,
)
from src.mcp_servers.tools.documents import assess_document_metadata
from src.rules.models import HouseholdProfile

router = APIRouter(prefix="/api/v1/journey/{conversation_id}/documents")


class CheckInputs(StrictApplicationModel):
    """What the person typed on the checklist; files come from the store."""

    documents: dict[str, DocumentStatus] = Field(default_factory=dict)
    profile_name: str | None = Field(default=None, max_length=120)
    document_metadata: dict[str, DocumentMetadata] = Field(default_factory=dict)


class DocumentCheckRequest(CheckInputs):
    scheme_id: str = Field(min_length=1, max_length=80)


class ResolutionRequest(DocumentCheckRequest):
    document_id: str = Field(min_length=1, max_length=80)
    issue_code: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=3, max_length=300)


class ReopenRequest(DocumentCheckRequest):
    document_id: str = Field(min_length=1, max_length=80)
    issue_code: str = Field(min_length=1, max_length=40)


def _store(request: Request) -> UploadStore:
    return request.app.state.upload_store


def _upload_error(error: UploadError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


async def _journey_values(request: Request, conversation_id: UUID) -> dict[str, Any]:
    snapshot = await request.app.state.journey_graph.aget_state(
        {"configurable": {"thread_id": str(conversation_id)}}
    )
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return snapshot.values


def _known_document_ids(request: Request) -> set[str]:
    """Collect every document_id in the active checklists of loaded schemes."""

    found: set[str] = set()
    for scheme_id in request.app.state.rule_packages:
        snapshot = load_checklist_snapshot(
            scheme_id,
            registry=request.app.state.fact_registry,
            bundle=request.app.state.rule_bundles.get(scheme_id),
        )
        if snapshot.usable and snapshot.checklist is not None:
            found.update(
                alternative.document_id
                for requirement in snapshot.checklist.requirements
                for alternative in requirement.alternatives
            )
    return found


async def _read_limited_body(request: Request) -> bytes:
    """Read the raw upload body, stopping as soon as it passes 20 MB."""

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail="The file is larger than the 20 MB limit."
        )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail="The file is larger than the 20 MB limit."
            )
    return bytes(body)


def _scheme_report(
    request: Request,
    conversation_id: UUID,
    values: dict[str, Any],
    scheme_id: str,
    inputs: CheckInputs,
) -> dict[str, Any]:
    """Build one scheme's checker report from stored files and typed fields."""

    if scheme_id not in request.app.state.rule_packages:
        raise HTTPException(status_code=409, detail="This scheme is information-only.")
    try:
        profile = HouseholdProfile.model_validate(values.get("profile") or {})
    except ValueError as error:
        raise HTTPException(
            status_code=409, detail="The saved profile is invalid."
        ) from error
    if not inputs.documents and not inputs.document_metadata:
        # After submission the form is gone; reuse what the person last sent.
        saved = (values.get("document_input_reports") or {}).get(scheme_id)
        if saved:
            inputs = CheckInputs(
                documents=saved.get("documents") or {},
                profile_name=saved.get("profile_name"),
                document_metadata=saved.get("document_metadata") or {},
            )
    registry = request.app.state.fact_registry
    bundle = request.app.state.rule_bundles.get(scheme_id)
    store = _store(request)
    uploads = store.list_uploads(str(conversation_id))
    intact = {
        document_id
        for document_id in uploads
        if store.is_intact(str(conversation_id), document_id)
    }

    def assess(data: dict[str, Any]) -> dict[str, Any]:
        return assess_document_metadata(data, registry=registry, bundle=bundle)

    reviews = store.list_reviews(str(conversation_id))
    extractions = {}
    for document_id in intact:
        saved = store.get_extraction(str(conversation_id), document_id)
        if saved:
            extractions[document_id] = saved
    try:
        report = check_scheme_documents(
            scheme_id,
            assess=assess,
            uploads=uploads,
            intact=intact,
            declared=dict(inputs.documents),
            profile_name=inputs.profile_name,
            document_metadata={
                document_id: metadata.model_dump(mode="json")
                for document_id, metadata in inputs.document_metadata.items()
            },
            profile_date_of_birth=(
                profile.date_of_birth.isoformat()
                if profile.date_of_birth is not None
                else None
            ),
            profile_conditions={
                "is_widow": profile.is_widow,
                "bpl_card_shown": profile.bpl_card_shown,
            },
            typed_facts=values.get("typed_facts"),
            resolutions=store.list_resolutions(str(conversation_id)),
            extractions=extractions,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    for group in report["groups"]:
        for document in group["documents"]:
            document["review"] = reviews.get(document["document_id"])
    return report


class ReviewRequest(StrictApplicationModel):
    reviewer_name: str = Field(min_length=2, max_length=80)
    note: str = Field(default="", max_length=300)


def reviewer_code_required() -> bool:
    return bool(os.environ.get("SCHEME_SAATHI_REVIEWER_CODE", "").strip())


def _require_reviewer(request: Request) -> None:
    """When a reviewer code is configured, sign-off and file viewing need it."""

    expected = os.environ.get("SCHEME_SAATHI_REVIEWER_CODE", "").strip()
    if not expected:
        return
    given = request.headers.get("x-reviewer-code", "")
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=403, detail="A valid reviewer access code is required."
        )


@router.post("/files/{document_id}/review")
async def review_file(
    conversation_id: UUID, document_id: str, review: ReviewRequest, request: Request
) -> dict:
    """Record who looked at the stored file. Informational; it gates nothing."""

    _require_reviewer(request)
    values = await _journey_values(request, conversation_id)
    try:
        saved = await asyncio.to_thread(
            _store(request).save_review, str(conversation_id), document_id,
            review.reviewer_name, review.note, values.get("mode", "citizen"),
        )
    except UploadError as error:
        raise _upload_error(error) from error
    return {"review": saved}


@router.delete("/files/{document_id}/review")
async def remove_review(
    conversation_id: UUID, document_id: str, request: Request
) -> dict:
    _require_reviewer(request)
    await _journey_values(request, conversation_id)
    try:
        removed = await asyncio.to_thread(
            _store(request).delete_review, str(conversation_id), document_id
        )
    except UploadError as error:
        raise _upload_error(error) from error
    return {"removed": removed}


@router.get("/files")
async def list_files(conversation_id: UUID, request: Request) -> dict:
    """List stored file metadata (never paths or contents)."""

    await _journey_values(request, conversation_id)
    uploads = await asyncio.to_thread(_store(request).list_uploads, str(conversation_id))
    return {
        "max_bytes": MAX_UPLOAD_BYTES,
        "allowed_extensions": list(ALLOWED_EXTENSIONS),
        "reviewer_code_required": reviewer_code_required(),
        "files": [record.model_dump(mode="json") for record in uploads.values()],
    }


@router.put("/files/{document_id}")
async def upload_file(
    conversation_id: UUID, document_id: str, request: Request
) -> dict:
    """Store one synthetic document file sent as the raw request body."""

    await _journey_values(request, conversation_id)
    if document_id not in _known_document_ids(request):
        raise HTTPException(
            status_code=404, detail="This document is not in any active checklist."
        )
    content = await _read_limited_body(request)
    file_name = unquote(request.headers.get("x-file-name", "document"))
    try:
        record = await asyncio.to_thread(
            _store(request).save, str(conversation_id), document_id, file_name, content
        )
    except UploadError as error:
        raise _upload_error(error) from error
    return {"file": record.model_dump(mode="json"), "status": "available"}


@router.get("/files/{document_id}/content")
async def file_content(
    conversation_id: UUID, document_id: str, request: Request
) -> Response:
    """Return the stored file so a reviewer can look at it (checked against its hash)."""

    _require_reviewer(request)
    await _journey_values(request, conversation_id)
    store = _store(request)
    try:
        record, content = await asyncio.to_thread(
            store.read_file, str(conversation_id), document_id
        )
    except UploadError as error:
        raise _upload_error(error) from error
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise HTTPException(
            status_code=409, detail="The stored file failed its integrity check."
        )
    safe_name = quote(record.original_name, safe="")
    return Response(
        content=content,
        media_type=record.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/files/{document_id}/suggestion")
async def get_suggestion(
    conversation_id: UUID, document_id: str, request: Request
) -> dict:
    """Return the saved suggestion for the file now stored, if any."""

    await _journey_values(request, conversation_id)
    try:
        saved = await asyncio.to_thread(
            _store(request).get_extraction, str(conversation_id), document_id
        )
    except UploadError as error:
        raise _upload_error(error) from error
    return {"enabled": get_extractor() is not None, "suggestion": saved}


@router.post("/files/{document_id}/extract")
async def extract_suggestion(
    conversation_id: UUID, document_id: str, request: Request
) -> dict:
    """Read the stored file and save a name/date suggestion. Never auto-accepted."""

    await _journey_values(request, conversation_id)
    extractor = get_extractor()
    if extractor is None:
        raise HTTPException(
            status_code=503, detail="Reading values from files is not switched on."
        )
    store = _store(request)
    try:
        record, content = await asyncio.to_thread(
            store.read_file, str(conversation_id), document_id
        )
        text = await asyncio.to_thread(extractor.read_text, content)
        found = parse_suggestion(text, extractor.engine)
        saved = await asyncio.to_thread(
            store.save_extraction, str(conversation_id), document_id,
            record.sha256, found.name, found.date_of_birth, found.engine,
        )
    except UploadError as error:
        raise _upload_error(error) from error
    except ExtractionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {
        "enabled": True,
        "suggestion": saved,
        "notice": "Suggested from the file. Not verified and not proof of authenticity.",
    }


@router.delete("/files/{document_id}")
async def delete_file(
    conversation_id: UUID, document_id: str, request: Request
) -> dict:
    """Remove a stored file and any acknowledgments that depended on it."""

    await _journey_values(request, conversation_id)
    try:
        removed = await asyncio.to_thread(
            _store(request).delete_upload, str(conversation_id), document_id
        )
    except UploadError as error:
        raise _upload_error(error) from error
    return {"removed": removed, "status": "missing"}


@router.post("/check")
async def check_documents_report(
    conversation_id: UUID, check: DocumentCheckRequest, request: Request
) -> dict:
    """Return the deterministic checker report for one scheme."""

    values = await _journey_values(request, conversation_id)
    return await asyncio.to_thread(
        _scheme_report, request, conversation_id, values, check.scheme_id, check
    )


@router.post("/readiness")
async def document_readiness(
    conversation_id: UUID, inputs: CheckInputs, request: Request
) -> dict:
    """Rank candidate schemes by how many required documents are in place.

    Eligibility results are shown alongside, unchanged; readiness never alters them.
    """

    values = await _journey_values(request, conversation_id)
    verdicts = values.get("candidate_verdicts", {})
    schemes = []
    for scheme_id, verdict in verdicts.items():
        if scheme_id not in request.app.state.rule_packages:
            continue
        report = await asyncio.to_thread(
            _scheme_report, request, conversation_id, values, scheme_id, inputs
        )
        schemes.append({
            **readiness_from_report(report),
            "eligibility": verdict.get("result"),
        })
    order = {"ready": 0, "partial": 1, "none": 2, "unverified": 3}
    eligibility_order = {"eligible": 0, "need_more_information": 1}
    schemes.sort(key=lambda item: (
        item["eligibility"] == "not_eligible",
        order[item["state"]],
        eligibility_order.get(item["eligibility"], 2),
        -item["in_place"],
        item["scheme_id"],
    ))
    return {
        "schemes": schemes,
        "notice": (
            "Document readiness only counts documents on file. It is not an "
            "eligibility decision."
        ),
    }


@router.post("/resolutions")
async def resolve_issue(
    conversation_id: UUID, resolution: ResolutionRequest, request: Request
) -> dict:
    """Record that the person knowingly accepts one flagged issue."""

    values = await _journey_values(request, conversation_id)
    if resolution.issue_code not in ACKNOWLEDGEABLE_CODES:
        raise HTTPException(
            status_code=422,
            detail="This issue is fixed by uploading or correcting the document.",
        )
    report = await asyncio.to_thread(
        _scheme_report, request, conversation_id, values,
        resolution.scheme_id, resolution,
    )
    issue = next(
        (
            issue
            for group in report["groups"]
            for document in group["documents"]
            for issue in document["issues"]
            if issue["document_id"] == resolution.document_id
            and issue["code"] == resolution.issue_code
        ),
        None,
    )
    if issue is None:
        raise HTTPException(
            status_code=409, detail="This issue is not currently flagged."
        )
    try:
        await asyncio.to_thread(
            _store(request).save_resolution,
            str(conversation_id),
            resolution.document_id,
            resolution.issue_code,
            resolution.reason,
            values.get("mode", "citizen"),
            issue["fingerprint"],
        )
    except UploadError as error:
        raise _upload_error(error) from error
    return await asyncio.to_thread(
        _scheme_report, request, conversation_id, values,
        resolution.scheme_id, resolution,
    )


@router.post("/resolutions/reopen")
async def reopen_issue(
    conversation_id: UUID, resolution: ReopenRequest, request: Request
) -> dict:
    """Withdraw an acknowledgment so the issue shows as unresolved again."""

    values = await _journey_values(request, conversation_id)
    try:
        await asyncio.to_thread(
            _store(request).delete_resolution,
            str(conversation_id), resolution.document_id, resolution.issue_code,
        )
    except UploadError as error:
        raise _upload_error(error) from error
    return await asyncio.to_thread(
        _scheme_report, request, conversation_id, values,
        resolution.scheme_id, resolution,
    )
