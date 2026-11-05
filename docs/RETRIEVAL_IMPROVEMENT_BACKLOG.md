# Scheme retrieval improvement backlog

## Data-driven onboarding dependency (planned 2026-11-04)

Follow the revised [six-phase plan](PHASE_WISE_IMPLEMENTATION_PLAN.md).
Finding a passage does not mean the scheme has an executable rule package.
Keep scheme IDs consistent with validated bundles; missing/unsupported bundles
remain information-only. Derive search hints only from confirmed registered
facts whose meaning and scope support an existing retrieval filter.

Add development retrieval cases for a data-only synthetic new scheme after
the generic runtime exists, but do not claim broad catalogue coverage or mix
that synthetic package into official/gold counts. No paid retrieval run is
authorized by this planning update; historical measurements below stay intact.

## Historical development baseline (2026-11-01)

**Reconciled 2026-11-03:** these numbers describe the recorded configuration
below, not the deployed full pipeline. Hosted reranking is now implemented,
and the later Phase 3 exercise was reported as BM25-only; neither may be
silently compared with these hybrid/no-reranker figures. Use
[the phase-wise plan](PHASE_WISE_IMPLEMENTATION_PLAN.md) for sequencing
(G09/G12/G13; R3/R5) and keep source curation in
[the catalogue workstream](SCHEME_CATALOGUE_AND_DELIVERY_PLAN.md).

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
`data/schemes/retrieval_eval_dev_results.json`. The command below exercises
the current code without reranking; reproducing the historical result also
requires the recorded corpus/config/commit. It can incur embedding charges:
run only when explicitly requested, using a distinct output file for new
measurements rather than overwriting the historical result.

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_scheme_retrieval.py --k 5 --skip-reranker --output retrieval_eval_new.json
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
- The then-configured local cross-encoder was not measured in this baseline.
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
5. **Measure the implemented hosted reranker.** Local memory failures were
   historical. Verify the current hosted provider/model/cutoffs and compare
   reranked versus non-reranked retrieval under the same corpus and reviewed
   query labels. If embeddings/reranking are unavailable, label the fallback
   configuration; a BM25 diagnostic is not full hybrid evidence.
6. **Expand evaluation responsibly.** Add varied, independently reviewed
   queries for each language and cross-scheme comparison. Keep this data
   development-only; create a separately governed held-out evaluation set only
   through the project’s approved evaluation process.
7. **Set acceptance criteria before tuning.** Agree on per-language Recall@k
   thresholds with the project/domain reviewers before using metrics as a
   release gate. No target threshold is set by this note.
8. **Separate retrieval from agent correctness.** Confirmed facts should feed
   only existing supported search hints/filters and bounded rediscovery in the
   analyst. New state/gender/age filters need separately reviewed schema,
   corpus and retrieval changes; the registry alone does not provide them.
   Record newly added/deduplicated candidates and passage limits; a scheme
   hit does not establish eligibility. Keep query/refinement calls inside the
   conversation budget and preserve counters across corrections.
9. **Meet the PDF evidence bar.** Before/after Recall@5 on at least 30 reviewed
   queries with exact corpus/config/model IDs, per-language results, costs and
   failures. Add the source/gold/extractor evidence from the catalogue plan;
   43 provisional retrieval queries do not replace 60 personas or 15 gold
   schemes. Do not use held-out cases for retrieval tuning.

## Completion record

The baseline and this improvement list document a known limitation; they do not
mark multilingual retrieval as fixed or validated. Update this file when
reviewed labels, multilingual corpus passages, stage-level comparisons, or a
successful reranked baseline become available.
