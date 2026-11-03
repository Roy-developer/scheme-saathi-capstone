import json
from pathlib import Path

import pytest

from src.api.scheme_search import load_passages


def test_loads_human_reviewed_two_scheme_corpus():
    project_root = Path(__file__).parents[1]
    passage_file = project_root / "data" / "schemes" / "passages.json"

    passages = load_passages(passage_file)

    assert len(passages) == 13
    assert {passage.scheme_id for passage in passages} == {
        "IGNWPS-MH",
        "PM-KISAN-IN",
    }
    assert {passage.review_status for passage in passages} == {"reviewed"}
    assert all(passage.source.source_id for passage in passages)
    assert all(passage.source.locator for passage in passages)
    assert {passage.source.collected_at.isoformat() for passage in passages} == {
        "2026-11-01"
    }


def test_rejects_duplicate_passage_ids(tmp_path):
    passage_file = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "schemes"
        / "passages.json"
    )
    data = json.loads(passage_file.read_text(encoding="utf-8"))
    data["passages"].append(data["passages"][0])
    invalid_file = tmp_path / "duplicate-passages.json"
    invalid_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        load_passages(invalid_file)