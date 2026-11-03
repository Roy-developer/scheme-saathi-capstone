from pathlib import Path

from openpyxl import Workbook
import pytest

from scripts.export_scheme_dataset import export_workbook, workbook_to_corpus
from src.api.scheme_search import load_passages


def create_workbook(path: Path, review_status: str = "reviewed") -> None:
    workbook = Workbook()
    sources = workbook.active
    sources.title = "Sources"
    sources.append(
        [
            "Source ID",
            "Publisher",
            "URL",
            "Retrieved on",
            "Publication / effective date",
        ]
    )
    sources.append(
        [
            "SRC-TEST-001",
            "Test department",
            "https://example.gov.in/scheme",
            "2026-11-01",
            None,
        ]
    )
    passages = workbook.create_sheet("Passages")
    passages.append(
        [
            "Passage ID",
            "Scheme ID",
            "Scheme name",
            "Jurisdiction",
            "Language",
            "Section",
            "Exact source text",
            "Source ID",
            "Source locator",
            "Review status",
        ]
    )
    passages.append(
        [
            "TEST-001",
            "TEST",
            "Test scheme",
            "IN",
            "en",
            "benefit",
            "A source-backed test excerpt.",
            "SRC-TEST-001",
            "PDF p. 1, section 1",
            review_status,
        ]
    )
    workbook.save(path)


def test_exports_reviewed_workbook_and_runtime_loader_accepts_json(tmp_path):
    workbook_path = tmp_path / "source.xlsx"
    output_path = tmp_path / "passages.json"
    create_workbook(workbook_path)

    count = export_workbook(workbook_path, output_path, "test.1")

    loaded = load_passages(output_path)
    assert count == 1
    assert loaded[0].passage_id == "TEST-001"
    assert loaded[0].source.source_id == "SRC-TEST-001"
    assert loaded[0].source.locator == "PDF p. 1, section 1"
    assert loaded[0].review_status == "reviewed"


def test_export_rejects_pending_passages(tmp_path):
    workbook_path = tmp_path / "pending.xlsx"
    create_workbook(workbook_path, review_status="pending_review")

    with pytest.raises(ValueError, match="only reviewed passages can be exported"):
        workbook_to_corpus(workbook_path, "test.1")
