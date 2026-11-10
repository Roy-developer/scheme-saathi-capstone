"""Evaluate scheme passage retrieval on a development query set."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.scheme_search import HybridSchemeRetriever, load_passages


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_SET = PROJECT_ROOT / "data" / "schemes" / "retrieval_eval_dev.json"
DEFAULT_CORPUS = PROJECT_ROOT / "data" / "schemes" / "passages"


class EvaluationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    query_language: Literal["en", "hi", "mr"] = "en"
    relevant_passage_ids: tuple[str, ...] = Field(min_length=1)


class EvaluationSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str = Field(min_length=1)
    split: str
    protected: bool
    annotation_note: str
    queries: tuple[EvaluationQuery, ...] = Field(min_length=1)


def load_evaluation_set(path: Path, corpus_path: Path) -> EvaluationSet:
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        evaluation_set = EvaluationSet.model_validate(data)
    except ValidationError as error:
        raise ValueError(f"Invalid retrieval evaluation set: {error}") from error

    if evaluation_set.split != "development" or evaluation_set.protected:
        raise ValueError(
            "This evaluator only accepts unprotected development query sets."
        )

    passages = load_passages(corpus_path)
    passage_ids = {passage.passage_id for passage in passages}
    query_ids: set[str] = set()
    for query in evaluation_set.queries:
        if query.query_id in query_ids:
            raise ValueError(f"Duplicate query ID {query.query_id!r}.")
        query_ids.add(query.query_id)
        unknown = set(query.relevant_passage_ids) - passage_ids
        if unknown:
            raise ValueError(
                f"Query {query.query_id!r} references unknown passages: "
                + ", ".join(sorted(unknown))
            )
    return evaluation_set


def evaluate_retrieval(
    evaluation_set: EvaluationSet,
    retriever: Any,
    *,
    k: int = 5,
    reranker_mode: str = "provided retriever",
) -> dict[str, Any]:
    if k < 1:
        raise ValueError("k must be at least 1.")

    scheme_by_passage = {
        passage.passage_id: passage.scheme_id for passage in retriever.passages
    }
    per_query = []
    scheme_totals: dict[str, list[float]] = defaultdict(list)
    language_totals: dict[str, list[float]] = defaultdict(list)

    for query in evaluation_set.queries:
        results = retriever.search(query.query, limit=k)
        retrieved_ids = [result.passage_id for result in results[:k]]
        relevant_ids = set(query.relevant_passage_ids)
        hits = relevant_ids.intersection(retrieved_ids)
        recall = len(hits) / len(relevant_ids)
        relevant_schemes = {
            scheme_by_passage[passage_id]
            for passage_id in relevant_ids
        }
        retrieved_schemes = {
            scheme_by_passage[passage_id]
            for passage_id in retrieved_ids
            if passage_id in scheme_by_passage
        }
        scheme_hit = bool(relevant_schemes.intersection(retrieved_schemes))
        per_query.append(
            {
                "query_id": query.query_id,
                "query": query.query,
                "query_language": query.query_language,
                "relevant_passage_ids": sorted(relevant_ids),
                "retrieved_passage_ids": retrieved_ids,
                "recall_at_k": recall,
                "scheme_hit_at_k": scheme_hit,
            }
        )
        for scheme_id in relevant_schemes:
            scheme_totals[scheme_id].append(recall)
        language_totals[query.query_language].append(recall)

    query_count = len(per_query)
    return {
        "dataset_version": evaluation_set.dataset_version,
        "split": evaluation_set.split,
        "protected": evaluation_set.protected,
        "reranker_mode": reranker_mode,
        "k": k,
        "query_count": query_count,
        "recall_at_k": sum(item["recall_at_k"] for item in per_query)
        / query_count,
        "scheme_hit_rate_at_k": sum(
            item["scheme_hit_at_k"] for item in per_query
        )
        / query_count,
        "recall_at_k_by_scheme": {
            scheme_id: sum(scores) / len(scores)
            for scheme_id, scores in sorted(scheme_totals.items())
        },
        "recall_at_k_by_language": {
            language: sum(scores) / len(scores)
            for language, scores in sorted(language_totals.items())
        },
        "per_query": per_query,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--skip-reranker",
        action="store_true",
        help="Evaluate BM25 + vectors + RRF without loading the local cross-encoder.",
    )
    args = parser.parse_args()

    evaluation_set = load_evaluation_set(args.eval_set, args.corpus)
    passages = load_passages(args.corpus)
    if args.skip_reranker:
        retriever = HybridSchemeRetriever(
            passages,
            rerank=lambda _query, candidates: [0.0] * len(candidates),
        )
        reranker_mode = "disabled; fused RRF order returned"
    else:
        retriever = HybridSchemeRetriever(passages)
        reranker_mode = "configured local cross-encoder"
    report = evaluate_retrieval(
        evaluation_set,
        retriever,
        k=args.k,
        reranker_mode=reranker_mode,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
