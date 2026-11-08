import json
from pathlib import Path

import pytest

from src.api.scheme_search import load_passages


def test_loads_three_scheme_corpus_with_review_status_per_passage():
    """The two pilots' 13 human-reviewed passages, plus IGNOAPS (added 2026-11-08).

    Only IGNOAPS's eligibility sentence is marked reviewed (the reviewer
    confirmed it word for word); its other passages are pending review.
    """
    project_root = Path(__file__).parents[1]
    passage_file = project_root / "data" / "schemes" / "passages.json"

    passages = load_passages(passage_file)

    assert len(passages) == 17
    assert {passage.scheme_id for passage in passages} == {
        "IGNWPS-MH",
        "PM-KISAN-IN",
        "IGNOAPS-MH",
    }
    pilots = [p for p in passages if p.scheme_id != "IGNOAPS-MH"]
    assert len(pilots) == 13
    assert {passage.review_status for passage in pilots} == {"reviewed"}
    assert {passage.source.collected_at.isoformat() for passage in pilots} == {"2026-11-01"}
    ignoaps = {p.passage_id: p for p in passages if p.scheme_id == "IGNOAPS-MH"}
    assert ignoaps["IGNOAPS-MH-ELIGIBILITY-01"].review_status == "reviewed"
    assert {p.review_status for pid, p in ignoaps.items() if pid != "IGNOAPS-MH-ELIGIBILITY-01"} == {
        "reviewed"
    }
    assert all(passage.source.source_id for passage in passages)
    assert all(passage.source.locator for passage in passages)


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