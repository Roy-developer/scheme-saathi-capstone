from types import SimpleNamespace

import pytest

from src.documents import extraction
from src.documents.checker import _file_value_codes, issue_fingerprint

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


class FakeModel:
    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.reply)


def _patch_model(monkeypatch, model: FakeModel) -> list:
    calls = []

    def build(api_key, name, *, timeout, max_tokens, reasoning_effort):
        calls.append((api_key, name, timeout, max_tokens))
        return model

    monkeypatch.setattr("src.llm_client.openrouter_chat_model", build)
    return calls


def test_vision_extractor_sends_image_and_returns_transcript(monkeypatch) -> None:
    model = FakeModel("Name: Asha Patil\nDOB: 12/03/1958")
    calls = _patch_model(monkeypatch, model)
    reader = extraction.OpenRouterVisionExtractor("key")

    text = reader.read_text(PNG)

    assert calls == [
        ("key", extraction.DEFAULT_VISION_MODEL,
         extraction.VISION_TIMEOUT_SECONDS, extraction.VISION_MAX_TOKENS)
    ]
    parts = model.messages[0].content
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    found = extraction.parse_suggestion(text, reader.engine)
    assert (found.name, found.date_of_birth) == ("Asha Patil", "1958-03-12")


def test_parse_suggestion_skips_family_name_and_takes_head_of_family() -> None:
    text = (
        "पारिवार का नाम: शमी परिवार\nमुखिया का नाम: राजेश कुमार शर्मा\n"
        "राशन कार्ड संख्या: UP-1234567890\n"
    )
    found = extraction.parse_suggestion(text, "fake")
    assert found.name == "राजेश कुमार शर्मा"
    assert extraction.parse_suggestion("Family Name: Sharma", "fake").name is None


def test_parse_suggestion_reads_marathi_labels_and_skips_relatives() -> None:
    text = (
        "कुटुंबाचे नाव: शिंदे कुटुंब\nवडिलांचे नाव: रमेश शिंदे\nआईचे नाव: सुनीता शिंदे\n"
        "नाव: आशा शिंदे\nजन्मतारीख: १२/०३/१९५८\n"
    )
    found = extraction.parse_suggestion(text, "fake")
    assert found.name == "आशा शिंदे"
    assert found.date_of_birth == "1958-03-12"
    head = "कुटुंब प्रमुखाचे नाव: आशा शिंदे"
    assert extraction.parse_suggestion(head, "fake").name == "आशा शिंदे"


def test_vision_extractor_rejects_pdf_and_failures(monkeypatch) -> None:
    reader = extraction.OpenRouterVisionExtractor("key")
    with pytest.raises(extraction.ExtractionError):
        reader.read_text(b"%PDF-1.7 data")

    _patch_model(monkeypatch, FakeModel(error=RuntimeError("429")))
    with pytest.raises(extraction.ExtractionError):
        reader.read_text(PNG)

    _patch_model(monkeypatch, FakeModel("   "))
    with pytest.raises(extraction.ExtractionError):
        reader.read_text(PNG)


def test_get_extractor_prefers_openrouter_then_azure(monkeypatch) -> None:
    for name in (
        "OPENROUTER_API_KEY", "OPENROUTER_API_KEY_FREE", "OPENROUTER_VISION_MODEL",
        "SCHEME_SAATHI_DOCINTEL_ENDPOINT", "SCHEME_SAATHI_DOCINTEL_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    assert extraction.get_extractor() is None

    monkeypatch.setenv("SCHEME_SAATHI_DOCINTEL_ENDPOINT", "https://x")
    monkeypatch.setenv("SCHEME_SAATHI_DOCINTEL_KEY", "k")
    assert extraction.get_extractor().engine == "azure-document-intelligence"

    monkeypatch.setenv("OPENROUTER_API_KEY", "chat")
    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", "free")
    monkeypatch.setenv("OPENROUTER_VISION_MODEL", "other/vl:free")
    chosen = extraction.get_extractor()
    assert (chosen.engine, chosen.api_key, chosen.model) == (
        "openrouter-vision", "free", "other/vl:free",
    )


def test_file_values_are_compared_with_the_profile() -> None:
    same = {"name": "ASHA  patil", "date_of_birth": "1958-03-12"}
    assert _file_value_codes(same, "Asha Patil", "1958-03-12") == []
    assert _file_value_codes(None, "Asha Patil", "1958-03-12") == []
    other = {"name": "Sita Rao", "date_of_birth": "1960-01-01"}
    assert _file_value_codes(other, "Asha Patil", "1958-03-12") == [
        "file_name_mismatch", "file_date_of_birth_mismatch",
    ]
    assert _file_value_codes(other, None, None) == []


def test_file_issue_fingerprint_changes_with_the_read_values() -> None:
    base = dict(
        document_id="identity_proof", code="file_name_mismatch",
        upload_sha256="abc", profile_name="Asha", entered_name=None,
        entered_date=None, checklist_fingerprint="c",
    )
    first = issue_fingerprint(**base, file_name="Sita")
    assert first != issue_fingerprint(**base, file_name="Gita")
    assert first == issue_fingerprint(**base, file_name="Sita")
