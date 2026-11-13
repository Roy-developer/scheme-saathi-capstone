import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from scripts.evaluate_scheme_retrieval import evaluate_retrieval, load_evaluation_set, DEFAULT_EVAL_SET, DEFAULT_CORPUS
from src.api.scheme_search import HybridSchemeRetriever, load_passages
es = load_evaluation_set(DEFAULT_EVAL_SET, DEFAULT_CORPUS)
passages = load_passages(DEFAULT_CORPUS)
r = HybridSchemeRetriever(passages, vector_search=lambda q, c, k: (), rerank=lambda q, c: [0.0]*len(c))
rep = evaluate_retrieval(es, r, k=5, reranker_mode="disabled; BM25 only, vectors off, fused order returned")
out = Path("eval/reports/retrieval_canonical_dev_bm25_only.json")
out.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(rep["query_count"], rep["recall_at_k"], rep["scheme_hit_rate_at_k"])
