"""Export the reviewed scheme workbook to the runtime passage corpus."""

import argparse
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from pydantic import ValidationError

from src.api.scheme_search import PassageCorpus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK = (
    PROJECT_ROOT
    / "data"
    / "schemes"
    / "scheme_passages_review_v0.4_human_attested.xlsx"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "schemes" / "passages.json"

SOURCE_COLUMNS = {
    "source id",
    "publisher",
    "url",
    "retrieved on",
    "publication / effective date",
}
PASSAGE_COLUMNS = {
    "passage id",
    "scheme id",
    "scheme name",
    "jurisdiction",
    "language",
    "section",
    "exact source text",
    "source id",
    "source locator",
    "review status",
}


def _header_map(sheet: Any) -> dict[str, int]:
    headers = {
        str(cell.value).strip().casefold().replace("_", " "): cell.column
        for cell in sheet[1]
        if cell.value is not None
    }
    return headers


def _required_columns(sheet: Any, required: set[str]) -> dict[str, int]:
    headers = _header_map(sheet)
    missing = required - headers.keys()
    if missing:
        raise ValueError(
            f"Sheet {sheet.title!r} is missing columns: "
            + ", ".join(sorted(missing))
        )
    return headers


def _cell(row: tuple[Any, ...], headers: dict[str, int], name: str) -> Any:
    return row[headers[name.replace("_", " ")] - 1]


def _required_text(value: Any, field: str, row_number: int) -> str:
    if value is None or not str(value).strip():
        raise ValueError(f"Row {row_number}: {field} is required.")
    return str(value).strip()


def _iso_date(value: Any, field: str, row_number: int) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _required_text(value, field, row_number)
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:\s|$)", text)
    if date_match:
        text = date_match.group(1)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise ValueError(
            f"Row {row_number}: {field} must be an ISO date (YYYY-MM-DD)."
        ) from error


def workbook_to_corpus(workbook_path: Path, corpus_version: str) -> dict[str, Any]:
    """Validate workbook rows and return the passage corpus payload."""

    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    required_sheets = {"Sources", "Passages"}
    missing_sheets = required_sheets - set(workbook.sheetnames)
    if missing_sheets:
        raise ValueError(
            "Workbook is missing sheets: " + ", ".join(sorted(missing_sheets))
        )

    source_sheet = workbook["Sources"]
    source_headers = _required_columns(source_sheet, SOURCE_COLUMNS)
    sources: dict[str, dict[str, Any]] = {}
    for row_number, row in enumerate(
        source_sheet.iter_rows(min_row=2, values_only=True),
        start=2,
    ):
        if not any(value is not None for value in row):
            continue
        source_id = _required_text(
            _cell(row, source_headers, "source_id"),
            "Source ID",
            row_number,
        )
        if source_id in sources:
            raise ValueError(f"Row {row_number}: duplicate source ID {source_id!r}.")
        publication_date = _cell(
            row,
            source_headers,
            "publication / effective date",
        )
        sources[source_id] = {
            "source_id": source_id,
            "publisher": _required_text(
                _cell(row, source_headers, "publisher"),
                "Publisher",
                row_number,
            ),
            "url": _required_text(
                _cell(row, source_headers, "url"),
                "URL",
                row_number,
            ),
            "collected_at": _iso_date(
                _cell(row, source_headers, "retrieved on"),
                "Retrieved on",
                row_number,
            ),
            "publication_date": (
                _iso_date(publication_date, "Publication date", row_number)
                if publication_date
                else None
            ),
        }

    passage_sheet = workbook["Passages"]
    passage_headers = _required_columns(passage_sheet, PASSAGE_COLUMNS)
    passages = []
    passage_ids: set[str] = set()
    for row_number, row in enumerate(
        passage_sheet.iter_rows(min_row=2, values_only=True),
        start=2,
    ):
        if not any(value is not None for value in row):
            continue

        passage_id = _required_text(
            _cell(row, passage_headers, "passage id"),
            "Passage ID",
            row_number,
        )
        if passage_id in passage_ids:
            raise ValueError(
                f"Row {row_number}: duplicate passage ID {passage_id!r}."
            )
        passage_ids.add(passage_id)

        review_status = _required_text(
            _cell(row, passage_headers, "review status"),
            "Review status",
            row_number,
        )
        if review_status != "reviewed":
            raise ValueError(
                f"Row {row_number}: passage {passage_id!r} has status "
                f"{review_status!r}; only reviewed passages can be exported."
            )

        source_id = _required_text(
            _cell(row, passage_headers, "source id"),
            "Source ID",
            row_number,
        )
        if source_id not in sources:
            raise ValueError(
                f"Row {row_number}: passage {passage_id!r} references "
                f"unknown source ID {source_id!r}."
            )

        source = dict(sources[source_id])
        source["locator"] = _required_text(
            _cell(row, passage_headers, "source locator"),
            "Source locator",
            row_number,
        )
        passages.append(
            {
                "passage_id": passage_id,
                "scheme_id": _required_text(
                    _cell(row, passage_headers, "scheme id"),
                    "Scheme ID",
                    row_number,
                ),
                "scheme_name": _required_text(
                    _cell(row, passage_headers, "scheme name"),
                    "Scheme name",
                    row_number,
                ),
                "jurisdiction": _required_text(
                    _cell(row, passage_headers, "jurisdiction"),
                    "Jurisdiction",
                    row_number,
                ),
                "language": _required_text(
                    _cell(row, passage_headers, "language"),
                    "Language",
                    row_number,
                ),
                "section": _required_text(
                    _cell(row, passage_headers, "section"),
                    "Section",
                    row_number,
                ),
                "text": _required_text(
                    _cell(row, passage_headers, "exact source text"),
                    "Exact source text",
                    row_number,
                ),
                "source": source,
                "review_status": review_status,
            }
        )

    if not passages:
        raise ValueError("Workbook contains no passage rows.")

    corpus = {"corpus_version": corpus_version, "passages": passages}
    try:
        PassageCorpus.model_validate(corpus)
    except ValidationError as error:
        raise ValueError(f"Exported corpus failed schema validation: {error}") from error
    return corpus


def export_workbook(
    workbook_path: Path,
    output_path: Path,
    corpus_version: str,
) -> int:
    corpus = workbook_to_corpus(workbook_path, corpus_version)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_text = json.dumps(corpus, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(output_text)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return len(corpus["passages"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--corpus-version", required=True)
    args = parser.parse_args()

    passage_count = export_workbook(
        args.workbook,
        args.output,
        args.corpus_version,
    )
    print(
        f"Exported {passage_count} reviewed passages "
        f"to {args.output} (corpus version {args.corpus_version})."
    )


if __name__ == "__main__":
    main()
