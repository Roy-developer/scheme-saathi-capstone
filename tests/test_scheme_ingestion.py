import json
import re
from pathlib import Path

import pytest

from src.api.scheme_search import load_passages


def test_loads_multi_scheme_reviewed_passage_corpus():
    project_root = Path(__file__).parents[1]
    passage_file = project_root / "data" / "schemes" / "passages.json"

    passages = load_passages(passage_file)

    corpus = json.loads(passage_file.read_text(encoding="utf-8"))
    assert len(passages) == len(corpus["passages"])
    scheme_ids = {passage.scheme_id for passage in passages}
    assert {
        "IGNWPS-MH",
        "PM-KISAN-IN",
        "IGNOAPS-MH",
    } <= scheme_ids
    assert {passage.review_status for passage in passages} == {"reviewed"}
    assert all(passage.source.source_id for passage in passages)
    assert all(passage.source.locator for passage in passages)
    pm_kisan_exclusion = next(
        passage
        for passage in passages
        if passage.passage_id == "PM-KISAN-IN-EXCLUSION-02"
    )
    assert "paid Income Tax" in pm_kisan_exclusion.text


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


def test_selected_gold_quotes_are_grounded_in_the_combined_corpus():
    project_root = Path(__file__).parents[1]
    schemes_dir = project_root / "data" / "schemes"
    manifest = json.loads(
        (schemes_dir / "rule_gold_selection.json").read_text(encoding="utf-8")
    )
    passages = {
        passage.passage_id: passage
        for passage in load_passages(schemes_dir / "passages.json")
    }

    def normalized(text: str) -> str:
        return re.sub(r"\s+", " ", text).casefold().strip()

    for selected in manifest["schemes"]:
        gold = json.loads(
            (schemes_dir / selected["draft_file"]).read_text(encoding="utf-8")
        )
        for rule in gold["rules"]:
            passage = passages[rule["source_passage_id"]]
            assert passage.scheme_id == selected["scheme_id"]
            assert normalized(rule["source_quote"]) in normalized(passage.text), (
                selected["scheme_id"],
                rule["rule_id"],
            )
