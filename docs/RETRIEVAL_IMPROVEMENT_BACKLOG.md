# Scheme retrieval improvement backlog

## Current development baseline

Recorded 2026-11-01 against corpus version `0.3.0` and evaluation dataset
version `0.2.0` (`data/schemes/retrieval_eval_dev.json`). This is a synthetic,
unprotected development set. The 13 Hindi, Marathi, and cross-scheme queries
have provisional labels; bilingual/domain review has not been completed.

The measured configuration was BM25 + OpenRouter vectors + Reciprocal Rank
Fusion, with the local cross-encoder reranker disabled because ONNX Runtime
failed to allocate memory. This is not a full-pipeline result.

| Metric | Result |
|---|---:|
| Queries | 43 |
| Passage Recall@5 | 83.7% |
| Scheme hit rate@5 | 100% |
| English Recall@5 (33 queries) | 97.0% |
| Hindi Recall@5 (5 queries) | 20.0% |
| Marathi Recall@5 (5 queries) | 60.0% |

The detailed per-query output is in
`data/schemes/retrieval_eval_dev_results.json`. Reproduce the current baseline
from the repository root with:

```powershell
python scripts/evaluate_scheme_retrieval.py --k 5 --skip-reranker --output data/schemes/retrieval_eval_dev_results.json
```

## Findings and caveats

- Multilingual retrieval is the largest measured gap: Hindi and Marathi Recall@5
  are substantially below English on this small development set.
- The runtime corpus currently contains English passages only. This is a likely
  limitation for Indic-language queries, but the baseline alone does not isolate
  the cause; embedding behavior, tokenization, query decomposition, and ranking
  may also contribute.
- The 5-query Hindi and 5-query Marathi samples are too small to establish
  general language performance. Do not treat these metrics as production
  acceptance results.
- Cross-scheme queries are only a small initial probe. Their provisional
  relevance labels must be checked against the cited passages.
- The configured local cross-encoder has not been measured in this baseline.
  Its initialization previously failed with an ONNX allocation error.

## Improvement work

1. **Validate the labels first.** Ask bilingual domain reviewers to check each
   added Hindi/Marathi query, its translation and intent, and every relevant
   passage label. Record reviewer and date; correct the dataset only from
   reviewed evidence.
2. **Add reviewed multilingual evidence.** Curate Hindi and Marathi passage
   text alongside the English source passages, retaining the official source,
   locator, source language, and translation provenance. Do not silently treat
   machine translations as official source text.
3. **Diagnose retrieval stages separately.** Measure BM25-only, vector-only,
   and fused RRF results by query language on the validated development set.
   Inspect tokenization and query decomposition for Devanagari, and test the
   embedding model with representative Hindi and Marathi queries before
   changing ranking weights.
4. **Compare model and ranking options.** With the same reviewed labels, compare
   multilingual embedding configurations and any language-aware or
   transliteration-assisted retrieval. Keep a reproducible baseline and report
   per-language results; do not tune solely to the current 13 added queries.
5. **Resolve reranker memory limits.** Investigate model/runtime/provider and
   memory requirements, then rerun the full hybrid pipeline when it can load.
   Report reranked and non-reranked results separately.
6. **Expand evaluation responsibly.** Add varied, independently reviewed
   queries for each language and cross-scheme comparison. Keep this data
   development-only; create a separately governed held-out evaluation set only
   through the project’s approved evaluation process.
7. **Set acceptance criteria before tuning.** Agree on per-language Recall@k
   thresholds with the project/domain reviewers before using metrics as a
   release gate. No target threshold is set by this note.

## Completion record

The baseline and this improvement list document a known limitation; they do not
mark multilingual retrieval as fixed or validated. Update this file when
reviewed labels, multilingual corpus passages, stage-level comparisons, or a
successful reranked baseline become available.
