"""Calibrate the search fallback rule from recorded reranker and retrieval signals.

Step 1 (paid, a few cents): record signals for every development question.
Each question is rewritten exactly as live search does, then the script records
the best reranker score and its scheme, and the scheme that keyword (BM25)
search and meaning (vector) search each rank first.

    python scripts/calibrate_search_fallback.py --record signals.json

Step 2 (free, repeatable): compare rules on the recorded signals.

    python scripts/calibrate_search_fallback.py --analyse signals.json

Questions come from data/schemes/retrieval_eval_dev.json (all on-topic) and
data/schemes/retrieval_calibration_dev.json (plain wording and off-topic,
scheme-level labels). Both are unprotected development sets.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_project_dotenv  # noqa: E402

DATA = PROJECT_ROOT / "data" / "schemes"


def load_questions() -> list[dict]:
    passages = json.loads((DATA / "passages.json").read_text(encoding="utf-8"))["passages"]
    scheme_of = {passage["passage_id"]: passage["scheme_id"] for passage in passages}
    questions = []
    dev = json.loads((DATA / "retrieval_eval_dev.json").read_text(encoding="utf-8"))
    for item in dev["queries"]:
        schemes = {scheme_of[pid] for pid in item["relevant_passage_ids"]}
        questions.append({
            "query_id": item["query_id"], "language": item.get("query_language", "en"),
            "query": item["query"], "expected": sorted(schemes), "kind": "dev",
        })
    calibration = json.loads((DATA / "retrieval_calibration_dev.json").read_text(encoding="utf-8"))
    for item in calibration["queries"]:
        expected = item["expected_scheme_id"]
        questions.append({
            "query_id": item["query_id"], "language": item["language"], "query": item["query"],
            "expected": [expected] if expected else [],
            "kind": "plain" if expected else "off_topic",
        })
    return questions


async def record(output: Path) -> None:
    load_project_dotenv()
    from src.api.scheme_search import (
        HybridSchemeRetriever, OpenRouterReranker, decompose_query, load_passages,
        reciprocal_rank_fusion,
    )
    from src.workflow.intake import rewrite_scheme_query

    passages = load_passages(DATA / "passages.json")
    retriever = HybridSchemeRetriever(passages, rerank=OpenRouterReranker(), use_cross_encoder=False)
    rows = []
    for question in load_questions():
        query = await rewrite_scheme_query(question["query"])
        variants = decompose_query(query)
        keyword = [retriever._bm25_search(v, passages) for v in variants]
        vector = list(retriever._vector_search_many(variants, passages))
        fused = reciprocal_rank_fusion([*keyword, *vector])[:100]
        candidates = [retriever._passage_by_id[pid] for pid in fused]
        scores = retriever._rerank(query, candidates)
        best_score, best = max(zip(scores, candidates), key=lambda item: item[0])
        rows.append({
            **question, "rewritten": query,
            "best_score": round(float(best_score), 4), "best_scheme": best.scheme_id,
            "keyword_top": retriever._top_scheme(keyword),
            "vector_top": retriever._top_scheme(vector),
        })
        print(f'{question["query_id"]:<18} {best_score:.3f} {best.scheme_id:<12} '
              f'kw={rows[-1]["keyword_top"]} vec={rows[-1]["vector_top"]}')
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"recorded {len(rows)} questions -> {output}")


def shown_scheme(row: dict, keep: float, fallback: float | None, agreement: float | None) -> str | None:
    """Which scheme the user would see under a rule (None = 'nothing found')."""

    score, scheme = row["best_score"], row["best_scheme"]
    if score >= keep or (fallback is not None and score >= fallback):
        return scheme
    if (agreement is not None and score >= agreement
            and scheme == row["keyword_top"] == row["vector_top"]):
        return scheme
    return None


def analyse(path: Path) -> None:
    rows = json.loads(path.read_text(encoding="utf-8"))
    on_topic = [r for r in rows if r["expected"]]
    off_topic = [r for r in rows if not r["expected"]]
    print(f"{len(on_topic)} on-topic questions, {len(off_topic)} off-topic questions\n")
    print(f"{'rule':<40} {'right scheme shown':>18} {'nothing shown':>14} "
          f"{'wrong scheme':>13} {'off-topic shown':>16}")
    rules = [("current: keep 0.3, fallback 0.2", 0.3, 0.2, None)]
    rules += [(f"current + agreement >= {t:.2f}", 0.3, 0.2, t)
              for t in (0.05, 0.08, 0.10, 0.12, 0.14, 0.15, 0.16, 0.18)]
    rules += [(f"fallback lowered to {t:.2f} (no agreement)", 0.3, t, None) for t in (0.15, 0.18)]
    for name, keep, fallback, agreement in rules:
        right = sum(shown_scheme(r, keep, fallback, agreement) in r["expected"] for r in on_topic)
        nothing = sum(shown_scheme(r, keep, fallback, agreement) is None for r in on_topic)
        wrong = len(on_topic) - right - nothing
        false_alarm = sum(shown_scheme(r, keep, fallback, agreement) is not None for r in off_topic)
        print(f"{name:<40} {right:>12}/{len(on_topic):<5} {nothing:>14} {wrong:>13} "
              f"{false_alarm:>10}/{len(off_topic)}")
    print("\nOff-topic questions, highest score first:")
    for r in sorted(off_topic, key=lambda r: -r["best_score"]):
        agree = r["best_scheme"] == r["keyword_top"] == r["vector_top"]
        print(f'  {r["best_score"]:.3f} agree={agree!s:<5} {r["query_id"]:<16} {r["rewritten"]}')
    print("\nOn-topic questions below the 0.2 fallback:")
    for r in sorted(on_topic, key=lambda r: -r["best_score"]):
        if r["best_score"] < 0.2:
            agree = r["best_scheme"] == r["keyword_top"] == r["vector_top"]
            print(f'  {r["best_score"]:.3f} agree={agree!s:<5} right={r["best_scheme"] in r["expected"]!s:<5} '
                  f'{r["query_id"]:<16} {r["rewritten"]}')


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--record", type=Path, help="Record signals (paid calls) to this file.")
    group.add_argument("--analyse", type=Path, help="Compare rules on recorded signals (free).")
    args = parser.parse_args()
    if args.record:
        asyncio.run(record(args.record))
    else:
        analyse(args.analyse)
