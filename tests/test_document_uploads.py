"""Upload storage, the document checker, resolutions and readiness."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.documents.checker import is_submission_ready
from src.documents.uploads import MAX_UPLOAD_BYTES, UploadError, UploadStore

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64


@pytest.fixture
def store(tmp_path) -> UploadStore:
    return UploadStore(tmp_path / "uploads", tmp_path / "uploads.sqlite3")


def test_store_saves_replaces_and_deletes(store: UploadStore) -> None:
    conversation = str(uuid4())
    first = store.save(conversation, "identity_proof", "id.png", PNG)
    assert first.size_bytes == len(PNG)
    assert store.is_intact(conversation, "identity_proof")

    store.save(conversation, "identity_proof", "id.pdf", PDF)
    uploads = store.list_uploads(conversation)
    assert list(uploads) == ["identity_proof"]
    assert uploads["identity_proof"].original_name == "id.pdf"
    files = [path for path in store._folder(conversation, "identity_proof").iterdir()]
    assert len(files) == 1

    assert store.delete_upload(conversation, "identity_proof") is True
    assert store.list_uploads(conversation) == {}


def test_store_rejects_bad_type_empty_and_oversized(store: UploadStore) -> None:
    conversation = str(uuid4())
    with pytest.raises(UploadError):
        store.save(conversation, "identity_proof", "id.exe", b"MZ" + b"0" * 20)
    with pytest.raises(UploadError):
        store.save(conversation, "identity_proof", "id.png", PDF)
    with pytest.raises(UploadError):
        store.save(conversation, "identity_proof", "id.png", b"")
    with pytest.raises(UploadError) as error:
        store.save(
            conversation, "identity_proof", "id.pdf",
            PDF + b"0" * MAX_UPLOAD_BYTES,
        )
    assert error.value.status_code == 413


def test_tampered_file_is_not_intact_and_forget_removes_everything(
    store: UploadStore,
) -> None:
    conversation = str(uuid4())
    store.save(conversation, "identity_proof", "id.png", PNG)
    stored = next(store._folder(conversation, "identity_proof").iterdir())
    stored.write_bytes(PNG + b"tampered")
    assert not store.is_intact(conversation, "identity_proof")

    store.delete_conversation(conversation)
    assert store.list_uploads(conversation) == {}
    assert not store._folder(conversation, "identity_proof").exists()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEME_SAATHI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SCHEME_SAATHI_UPLOAD_DB", str(tmp_path / "uploads.sqlite3"))
    with TestClient(app) as test_client:
        yield test_client


def _values(**extra):
    return {
        "profile": {"date_of_birth": "1950-01-01"},
        "mode": "citizen",
        "candidate_verdicts": {"IGNOAPS-MH": {"result": "eligible"}},
        **extra,
    }


def _patched(values):
    async def fake(_request, _conversation_id):
        return values

    return patch("src.api.document_uploads._journey_values", fake)


def test_upload_check_resolve_and_readiness_flow(client: TestClient) -> None:
    conversation = uuid4()
    base = f"/api/v1/journey/{conversation}/documents"
    with _patched(_values()):
        too_big = client.put(
            f"{base}/files/identity_proof",
            content=PDF + b"0" * MAX_UPLOAD_BYTES,
            headers={"X-File-Name": "id.pdf"},
        )
        assert too_big.status_code == 413

        unknown = client.put(f"{base}/files/not_a_document", content=PDF)
        assert unknown.status_code == 404

        before = client.post(f"{base}/readiness", json={}).json()
        assert before["schemes"][0]["state"] == "none"
        assert before["schemes"][0]["missing_labels"]

        uploaded = client.put(
            f"{base}/files/identity_proof",
            content=PNG,
            headers={"X-File-Name": "aadhaar%20demo.png"},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["status"] == "available"
        assert "path" not in uploaded.text

        after = client.post(f"{base}/readiness", json={}).json()
        scheme = after["schemes"][0]
        assert scheme["state"] == "partial"
        assert scheme["in_place"] >= 1
        assert "not an eligibility decision" in after["notice"]

        report = client.post(
            f"{base}/check",
            json={
                "scheme_id": "IGNOAPS-MH",
                "profile_name": "Asha Patil",
                "document_metadata": {"identity_proof": {"name": "Ashok Patil"}},
            },
        ).json()
        assert report["overall"] == "incomplete"
        issues = [
            issue
            for group in report["groups"]
            for document in group["documents"]
            for issue in document["issues"]
        ]
        mismatch = next(issue for issue in issues if issue["code"] == "name_mismatch")

        body = {
            "scheme_id": "IGNOAPS-MH",
            "profile_name": "Asha Patil",
            "document_metadata": {"identity_proof": {"name": "Ashok Patil"}},
            "document_id": "identity_proof",
            "issue_code": "name_mismatch",
        }
        assert client.post(
            f"{base}/resolutions", json={**body, "reason": "x"}
        ).status_code == 422
        resolved = client.post(
            f"{base}/resolutions", json={**body, "reason": "Spelling variant"}
        ).json()
        acknowledged = next(
            issue
            for group in resolved["groups"]
            for document in group["documents"]
            for issue in document["issues"]
            if issue["code"] == "name_mismatch"
        )
        assert acknowledged["acknowledged"] is True
        assert mismatch["fingerprint"] == acknowledged["fingerprint"]

        # A different typed name voids the acknowledgment.
        changed = client.post(
            f"{base}/check",
            json={
                "scheme_id": "IGNOAPS-MH",
                "profile_name": "Asha Patil",
                "document_metadata": {"identity_proof": {"name": "Someone Else"}},
            },
        ).json()
        voided = next(
            issue
            for group in changed["groups"]
            for document in group["documents"]
            for issue in document["issues"]
            if issue["code"] == "name_mismatch"
        )
        assert voided["acknowledged"] is False

        reopened = client.post(f"{base}/resolutions/reopen", json=body).json()
        assert not any(
            issue["acknowledged"]
            for group in reopened["groups"]
            for document in group["documents"]
            for issue in document["issues"]
        )

        removed = client.delete(f"{base}/files/identity_proof").json()
        assert removed["status"] == "missing"
        listing = client.get(f"{base}/files").json()
        assert listing["files"] == []
        assert listing["max_bytes"] == MAX_UPLOAD_BYTES


def test_parse_suggestion_uses_only_labelled_values() -> None:
    from src.documents.extraction import parse_suggestion

    found = parse_suggestion(
        "Government of India\nName: Asha Patil\nFather Name: Ramesh Patil\n"
        "DOB: 12/03/1958\n",
        "fake",
    )
    assert found.name == "Asha Patil"
    assert found.date_of_birth == "1958-03-12"

    hindi = parse_suggestion("नाम: आशा पाटील\nजन्म तिथि: १२/०३/१९५८", "fake")
    assert hindi.name == "आशा पाटील"
    assert hindi.date_of_birth == "1958-03-12"

    nothing = parse_suggestion("12/03/1958 Asha Patil", "fake")
    assert nothing.name is None and nothing.date_of_birth is None
    assert parse_suggestion("DOB: 31/02/1958", "fake").date_of_birth is None


def test_suggestion_is_dropped_when_file_is_replaced(store: UploadStore) -> None:
    conversation = str(uuid4())
    record = store.save(conversation, "identity_proof", "id.png", PNG)
    store.save_extraction(
        conversation, "identity_proof", record.sha256, "Asha", "1958-03-12", "fake"
    )
    assert store.get_extraction(conversation, "identity_proof")["name"] == "Asha"
    store.save(conversation, "identity_proof", "id.png", PNG + b"1")
    assert store.get_extraction(conversation, "identity_proof") is None
    store.delete_conversation(conversation)


def test_extract_route_is_off_by_default_and_needs_a_stored_file(
    client: TestClient, monkeypatch
) -> None:
    class Fake:
        engine = "fake"

        def read_text(self, _content: bytes) -> str:
            return "Name: Asha Patil\nDOB: 12-03-1958"

    conversation = uuid4()
    base = f"/api/v1/journey/{conversation}/documents/files/identity_proof"
    with _patched(_values()):
        for variable in ("OPENROUTER_API_KEY", "OPENROUTER_API_KEY_FREE"):
            monkeypatch.delenv(variable, raising=False)
        assert client.get(f"{base}/suggestion").json()["enabled"] is False
        assert client.post(f"{base}/extract").status_code == 503

        client.put(base, content=PNG, headers={"X-File-Name": "id.png"})
        with patch("src.api.document_uploads.get_extractor", lambda: Fake()):
            assert client.post(f"{base}/extract").json()["suggestion"]["name"] == (
                "Asha Patil"
            )
            saved = client.get(f"{base}/suggestion").json()["suggestion"]
            assert saved["date_of_birth"] == "1958-03-12"
        client.delete(base)
        with patch("src.api.document_uploads.get_extractor", lambda: Fake()):
            assert client.get(f"{base}/suggestion").json()["suggestion"] is None


def test_review_signoff_is_recorded_and_voided_by_a_new_file(
    client: TestClient,
) -> None:
    conversation = uuid4()
    docs = f"/api/v1/journey/{conversation}/documents"
    base = f"{docs}/files/identity_proof"
    check = {"scheme_id": "IGNOAPS-MH"}

    def review_of_report():
        report = client.post(f"{docs}/check", json=check).json()
        return next(
            document["review"]
            for group in report["groups"]
            for document in group["documents"]
            if document["document_id"] == "identity_proof"
        )

    with _patched(_values()):
        assert client.post(
            f"{base}/review", json={"reviewer_name": "Ravi Kumar"}
        ).status_code == 404
        client.put(base, content=PNG, headers={"X-File-Name": "id.png"})
        assert review_of_report() is None
        saved = client.post(
            f"{base}/review", json={"reviewer_name": "Ravi Kumar", "note": "Looks fine"}
        ).json()["review"]
        assert saved["reviewer_name"] == "Ravi Kumar"
        assert review_of_report()["note"] == "Looks fine"

        client.put(base, content=PNG + b"1", headers={"X-File-Name": "id.png"})
        assert review_of_report() is None

        client.post(f"{base}/review", json={"reviewer_name": "Ravi Kumar"})
        assert client.delete(f"{base}/review").json()["removed"] is True
        assert review_of_report() is None


def test_file_content_is_served_safely_and_rejects_tampering(
    client: TestClient, tmp_path
) -> None:
    docs = f"/api/v1/journey/{uuid4()}/documents/files/identity_proof"
    with _patched(_values()):
        assert client.get(f"{docs}/content").status_code == 404
        client.put(docs, content=PNG, headers={"X-File-Name": "id%20card.png"})
        response = client.get(f"{docs}/content")
        assert response.status_code == 200
        assert response.content == PNG
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert "uploads" not in response.headers["content-disposition"]

        stored = next((tmp_path / "uploads").rglob("*.png"))
        stored.write_bytes(PNG + b"tampered")
        assert client.get(f"{docs}/content").status_code == 409


def test_reviewer_code_gates_signoff_and_file_view(
    client: TestClient, monkeypatch
) -> None:
    docs = f"/api/v1/journey/{uuid4()}/documents/files/identity_proof"
    review = {"reviewer_name": "R. Reviewer", "note": ""}
    with _patched(_values()):
        client.put(docs, content=PNG, headers={"X-File-Name": "id.png"})
        assert client.post(f"{docs}/review", json=review).status_code == 200

        monkeypatch.setenv("SCHEME_SAATHI_REVIEWER_CODE", "s3cret")
        assert client.get(docs.rsplit("/", 1)[0]).json()["reviewer_code_required"]
        wrong = {"X-Reviewer-Code": "nope"}
        right = {"X-Reviewer-Code": "s3cret"}
        assert client.get(f"{docs}/content").status_code == 403
        assert client.get(f"{docs}/content", headers=wrong).status_code == 403
        assert client.post(f"{docs}/review", json=review).status_code == 403
        assert client.delete(f"{docs}/review").status_code == 403
        assert client.get(f"{docs}/content", headers=right).status_code == 200
        assert client.post(f"{docs}/review", json=review, headers=right).status_code == 200
        assert client.delete(f"{docs}/review", headers=right).status_code == 200


def test_same_file_on_two_documents_is_flagged_and_acknowledgeable(
    client: TestClient,
) -> None:
    docs = f"/api/v1/journey/{uuid4()}/documents"
    check = {"scheme_id": "IGNOAPS-MH"}

    def reused_issues():
        report = client.post(f"{docs}/check", json=check).json()
        return [
            issue
            for group in report["groups"]
            for document in group["documents"]
            for issue in document["issues"]
            if issue["code"] == "same_file_reused"
        ]

    with _patched(_values()):
        client.put(f"{docs}/files/identity_proof", content=PNG,
                   headers={"X-File-Name": "a.png"})
        assert reused_issues() == []
        client.put(f"{docs}/files/age_proof", content=PNG,
                   headers={"X-File-Name": "a.png"})
        issues = reused_issues()
        assert len(issues) == 2
        assert all(issue["can_acknowledge"] for issue in issues)

        client.put(f"{docs}/files/age_proof", content=PNG + b"1",
                   headers={"X-File-Name": "b.png"})
        assert reused_issues() == []


def test_submission_readiness_keeps_duplicate_files_blocking_after_acknowledgment() -> None:
    report = {
        "overall": "complete_with_acknowledged_warnings",
        "groups": [{
            "documents": [{
                "issues": [{
                    "code": "same_file_reused",
                    "acknowledged": True,
                }],
            }],
        }],
    }
    assert is_submission_ready(report) is False


def test_submission_readiness_allows_acknowledged_advisory_finding() -> None:
    report = {
        "overall": "complete_with_acknowledged_warnings",
        "groups": [{
            "documents": [{
                "issues": [{
                    "code": "cannot_compare",
                    "acknowledged": True,
                }],
            }],
        }],
    }
    assert is_submission_ready(report) is True


def test_check_after_submission_reuses_the_saved_inputs(client: TestClient) -> None:
    docs = f"/api/v1/journey/{uuid4()}/documents"
    saved = {
        "IGNOAPS-MH": {
            "documents": {"identity_proof": "available"},
            "profile_name": "Asha Patil",
            "document_metadata": {"identity_proof": {"name": "Ashok Patil"}},
        }
    }
    codes = lambda report: {
        issue["code"]
        for group in report["groups"]
        for document in group["documents"]
        for issue in document["issues"]
    }
    with _patched(_values()):
        client.put(
            f"{docs}/files/identity_proof", content=PNG,
            headers={"X-File-Name": "id.png"},
        )
        empty = client.post(f"{docs}/check", json={"scheme_id": "IGNOAPS-MH"}).json()
    with _patched(_values(document_input_reports=saved)):
        reused = client.post(f"{docs}/check", json={"scheme_id": "IGNOAPS-MH"}).json()
    assert "name_mismatch" not in codes(empty)
    assert "name_mismatch" in codes(reused)
