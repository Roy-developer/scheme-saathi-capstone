import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.evaluate_scheme_retrieval import (
    EvaluationSet,
    evaluate_retrieval,
    load_evaluation_set,
)
from src.api.scheme_search import load_passages


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_SET_PATH = PROJECT_ROOT / "data" / "schemes" / "retrieval_eval_dev.json"
CORPUS_PATH = PROJECT_ROOT / "data" / "schemes" / "passages"


class FakeRetriever:
    passages = (
        SimpleNamespace(passage_id="widow-1", scheme_id="IGNWPS-MH"),
        SimpleNamespace(passage_id="farmer-1", scheme_id="PM-KISAN-IN"),
    )

    def __init__(self, ranked_ids):
        self.ranked_ids = ranked_ids

    def search(self, query, *, limit):
        return tuple(
            SimpleNamespace(passage_id=passage_id)
            for passage_id in self.ranked_ids[:limit]
        )


def test_development_dataset_has_multilingual_and_cross_scheme_queries():
    evaluation_set = load_evaluation_set(EVAL_SET_PATH, CORPUS_PATH)

    assert len(evaluation_set.queries) == 43
    assert evaluation_set.split == "development"
    assert evaluation_set.protected is False
    assert len({query.query_id for query in evaluation_set.queries}) == 43
    assert {
        language: sum(query.query_language == language for query in evaluation_set.queries)
        for language in ("en", "hi", "mr")
    } == {"en": 33, "hi": 5, "mr": 5}
    assert sum(
        query.query_id.startswith("CROSS-")
        for query in evaluation_set.queries
    ) == 3
    passage_schemes = {
        passage.passage_id: passage.scheme_id
        for passage in load_passages(CORPUS_PATH)
    }
    for query in evaluation_set.queries:
        if query.query_id.startswith("CROSS-"):
            assert len({
                passage_schemes[passage_id]
                for passage_id in query.relevant_passage_ids
            }) > 1


def test_evaluator_reports_passage_recall_and_scheme_hit_rate():
    evaluation_set = EvaluationSet.model_validate(
        {
            "dataset_version": "test",
            "split": "development",
            "protected": False,
            "annotation_note": "test",
            "queries": [
                {
                    "query_id": "q1",
                    "query": "widow support",
                    "query_language": "hi",
                    "relevant_passage_ids": ["widow-1"],
                },
                {
                    "query_id": "q2",
                    "query": "farmer support",
                    "query_language": "mr",
                    "relevant_passage_ids": ["farmer-1"],
                },
            ],
        }
    )

    report = evaluate_retrieval(
        evaluation_set,
        FakeRetriever(["widow-1", "farmer-1"]),
        k=1,
        reranker_mode="disabled; fused RRF order returned",
    )

    assert report["recall_at_k"] == 0.5
    assert report["scheme_hit_rate_at_k"] == 0.5
    assert report["reranker_mode"] == "disabled; fused RRF order returned"
    assert report["recall_at_k_by_scheme"] == {
        "IGNWPS-MH": 1.0,
        "PM-KISAN-IN": 0.0,
    }
    assert report["recall_at_k_by_language"] == {"hi": 1.0, "mr": 0.0}


def test_evaluator_rejects_protected_or_non_development_sets(tmp_path):
    data = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    data["protected"] = True
    path = tmp_path / "protected.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unprotected development"):
        load_evaluation_set(path, CORPUS_PATH)


def test_evaluator_rejects_unknown_passage_labels(tmp_path):
    data = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    data["queries"][0]["relevant_passage_ids"] = ["not-in-corpus"]
    path = tmp_path / "unknown-label.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown passages"):
        load_evaluation_set(path, CORPUS_PATH)
