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

## Search fallback calibration (2026-11-05, branch `supervisor-redesign-3`)

### The problem

Live search showed "No matching passages were found" for plainly worded,
on-topic questions such as *"small farmer with 1 acre, any money support?"*.
Search had found the right scheme (PM-KISAN ranked first), but the hosted
reranker (`cohere/rerank-v3.5` via OpenRouter) gave the best passage **0.198**,
just under the 0.2 fallback line, so it was hidden. The old (branch 2) and new
(LangChain `OpenAIEmbeddings` + `QdrantVectorStore`) search code gave identical
rankings and scores for this question, so this was a threshold problem, not a
regression.

The rule before the fix: show passages scoring ≥ 0.3; if none, show the single
best passage if it scores ≥ 0.2; otherwise show nothing. The 0.2 line came from a
few live questions (plain farmer questions about 0.24, off-topic up to 0.145).

### The fix: a second check ("both searches agree")

Saathi retrieves with two independent methods before reranking: **keyword**
search (BM25) and **meaning** search (vectors). When the reranker is unsure,
agreement between the two is strong evidence. New rule, applied only when
nothing reaches 0.3 and the best passage is under 0.2:

> Show the best passage if it scores **≥ 0.12** **and** keyword search and
> meaning search both rank **its scheme** first.

Code: `HybridSchemeRetriever.search(..., agreement_min_score=...)` and
`_top_scheme` in `src/api/scheme_search.py`; the value is
`HOSTED_RERANK_AGREEMENT_MIN_SCORE = 0.12`, passed by the `search_schemes` MCP
tool in hosted-rerank mode. Offline tests:
`test_agreement_keeps_a_near_miss_when_both_searches_rank_its_scheme_first`,
`test_agreement_needs_both_searches_to_rank_the_same_scheme_first`.

### How the value was chosen (measured, not guessed)

1. **Questions (75, development only):** the 43 existing questions in
   `data/schemes/retrieval_eval_dev.json` (all on-topic), plus 32 new ones in
   `data/schemes/retrieval_calibration_dev.json`: 16 plainly worded on-topic
   questions (8 English, 4 Hindi, 4 Marathi) and 16 off-topic questions that
   must show nothing (home loans, scholarships, gas and ration cards, health and
   crop insurance, army pension, weather; English, Hindi and Marathi). Labels are
   scheme-level and **provisional**; they need domain/bilingual review.
2. **Signals recorded once** with `scripts/calibrate_search_fallback.py --record`
   (paid: ~75 query rewrites, embeddings and rerank calls, a few cents). Each
   question is rewritten exactly as live search does, then the script records
   the best rerank score and scheme, and the scheme keyword and meaning search
   each rank first.
3. **Rules compared for free** with `--analyse` on the recorded signals:

| Rule | Right scheme shown (59 on-topic) | Nothing shown | Off-topic wrongly shown (16) |
|---|---:|---:|---:|
| Before: keep 0.3, fallback 0.2 | 55 | 4 | 0 |
| + agreement ≥ 0.05 | 59 | 0 | **2** |
| **+ agreement ≥ 0.12 (chosen)** | **59** | **0** | **0** |
| + agreement ≥ 0.18 | 59 | 0 | 0 |
| Fallback simply lowered to 0.15 | 59 | 0 | 0 |

What the data showed:
- The 4 missed right answers scored **0.186–0.198**, and **all four** had both
  searches agreeing on the right scheme (the farmer question, a Marathi
  question, a plain "help for small land farmers", and a cross-scheme question).
- Off-topic questions scored at most **0.068**. Two of them ("army pension" at
  0.067, "scholarship" at 0.060) did have both searches agreeing, so agreement
  alone is **not** enough; a score floor is still needed.
- **0.12** sits with a margin on both sides: ~0.05 above the highest off-topic
  score and ~0.07 below the lowest missed right answer.
- Simply lowering the fallback to 0.15 also passed this set, but an earlier
  live check saw an off-topic housing question at 0.145; requiring agreement
  protects against such a case where only the reranker is fooled.

### Caveats

- Small, synthetic, provisional set (16 off-topic questions; a 13-passage,
  two-scheme corpus). The rule must be re-checked when schemes or passages are
  added, or the reranker or embedding model changes.
- Scores are rerank scores on the **rewritten** query; a change to the
  query-rewrite prompt also requires re-calibration.
- Keyword search finds nothing for some untranslated Hindi/Marathi questions
  (no shared words with the English corpus); those cannot "agree" and fall back
  to the 0.3 / 0.2 rule.

### How to re-calibrate

```powershell
python scripts/calibrate_search_fallback.py --record retrieval_signals_<date>.json   # paid, a few cents
python scripts/calibrate_search_fallback.py --analyse retrieval_signals_<date>.json  # free
```

Pick the lowest agreement floor that still shows **zero** off-topic questions,
keep a margin above the highest off-topic score, update
`HOSTED_RERANK_AGREEMENT_MIN_SCORE` with the date and set size in its comment,
and add the new table here.

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
