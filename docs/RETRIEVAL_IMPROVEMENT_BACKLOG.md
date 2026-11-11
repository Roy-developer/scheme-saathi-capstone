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

## Local multilingual embedding and BM25 tuning (2026-11-11)

The capstone guide's minimum-bar evidence for retrieval is Recall@5 on at least
30 labeled queries before and after a change (PDF p. 3; see
[`CAPSTONE_PROJECT_GUIDE_REFERENCE.md`](CAPSTONE_PROJECT_GUIDE_REFERENCE.md)).
It specifies no numerical pass threshold. The following controlled development
experiments meet that query-count requirement, but are not held-out validation
or evidence that the full retrieval bar is complete.

All runs below use the same 199-query development set
(`retrieval_eval_dev.json`), passage corpus, `k=5`, and disabled reranker.
Labels are development-only; the 156 added English labels received AI-assisted
review, while the original Hindi and Marathi labels remain provisional.

| Configuration | BM25 k1 / b | Recall@5 | Scheme hit@5 |
|---|---:|---:|---:|
| BM25 only | 1.5 / 0.75 | 58.1% | 87.4% |
| Potion multilingual + BM25 + RRF | 1.5 / 0.75 | 47.2% | 79.4% |
| MiniLM multilingual + BM25 + RRF | 1.5 / 0.75 | 68.1% | 92.0% |
| MiniLM multilingual + BM25 + RRF | 0.6 / 0.5 | **69.3%** | **93.5%** |

The selected local model is FastEmbed's
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Its measured
Windows cache occupied 240.5 MB versus 506.4 MB for the cached Potion model.
The best tested BM25 settings are `k1=0.6`, `b=0.5`; a small parameter sweep
found a modest development-set gain over the defaults (`1.5`, `0.75`). A sweep
of RRF constants from 5 through 200 did not change Recall@5 for MiniLM.

These are not a protected or independently human-reviewed evaluation. The
five Hindi and five Marathi queries all target English passages in the corpus,
and both hybrid models scored 0% Recall@5 for those language groups; this does
not establish cross-lingual retrieval quality. The experiment also disables
the reranker, so the scores must not be presented as full-pipeline results.
Retain the MiniLM/BM25 settings as the current development configuration, and
validate on independently reviewed, held-out multilingual cases before
claiming generalization or capstone completion.

An attempted 199-query run with the local BGE cross-encoder enabled did not
complete: ONNX Runtime failed to allocate memory during reranking, so no
full-pipeline score was produced. Do not treat the long-running attempt as
latency evidence for one interactive search. Leave the local reranker
configuration unchanged; prioritize bilingual corpus and evaluation coverage
instead.

### Marathi retrieval slice (2026-11-11)

The user chose Marathi instead of the proposed 10-scheme Hindi expansion. The
corpus already contains Marathi-tagged source passages for three Maharashtra
schemes: BFFL-MH, EACS-MH, and NSMNY-MH. A 30-query exploratory set is at
`data/schemes/retrieval_eval_marathi_dev.json` (10 questions per scheme),
grounded to those Marathi passage IDs.

All 30 questions and their supporting passages received AI-assisted review
from OpenRouter's free `nvidia/nemotron-3.5-lightning:free` model. Four
question wordings and one supporting-passage label were revised and
re-reviewed. The detailed output,
including the review scope and model, is at
`data/schemes/retrieval_eval_marathi_dev_ai_review.json`. This is not
independent bilingual/domain review; the query set and labels remain
development-only and provisional. Do not claim validated Marathi retrieval
quality until a Marathi reviewer checks naturalness, source meaning, and
supporting passage IDs. The corpus also has incomplete passage coverage for
EACS-MH; its current Marathi text covers benefits, documents, and one
application statement, not full scheme eligibility or application procedure.
Keep the scope to the evidence actually present, and add held-out reviewed
cases before claims of generalization.

The scanned MBOCWW education application form cited for EACS-MH
(`SRC-EACS-MH-002`, collected 2026-11-04) was rendered and OCR-checked against
both page images. For scheme E-01, its Marathi benefit, 75% attendance
certificate, Annexure A document list, and self-attested submission statement
are already represented by `EACS-MH-BENEFIT-03`,
`EACS-MH-DOCUMENTS-01/02`, and `EACS-MH-APPLICATION-02`. Its office-use
checklist also confirms that an actively registered construction worker's
application includes all required documents; this source-exact Marathi
statement was added as `EACS-MH-APPLICATION-03` in corpus version `0.3.1`.
Within EACS-MH, the new passage ranks first in BM25 and in the hybrid top five
for a matching Marathi query (hybrid rank 2). In an unscoped search across the
full corpus, it did not appear in the top five, so this check does not show
that a user can retrieve it without first narrowing to EACS-MH. The form does
not provide the full application procedure, so the coverage gap above remains.

Follow-up source and discovery check: the myScheme EACS page currently renders
no scheme details in the accessible page content, and the MBOCWW public page
checked did not expose an E-01 application procedure. No procedure passages
were added. On the existing 10-query AI-reviewed Marathi EACS development
slice, using the normal unscoped BM25+MiniLM search limited to the top 10
passages, at least one EACS passage appeared for 7/10 queries; the labeled
relevant passage appeared in the top 10 for 7/10. These are development-only
checks, not independent review. The search flow has no pre-retrieval scheme
filter, so EACS misses should be addressed with broader validated Marathi
retrieval work rather than treating the scheme-scoped smoke test as evidence
of successful discovery.

Development results on the revised, AI-reviewed 30-query set (`k=5`,
reranker disabled):

| Configuration | Recall@5 | Scheme hit@5 |
|---|---:|---:|
| BM25 only (`k1=0.6`, `b=0.5`) | 65.0% | 90.0% |
| MiniLM + tuned BM25 + RRF | 51.7% | 86.7% |

These are not a fair quality verdict because the synthetic questions were
drafted from the same passages used to label them and the review was performed
by an LLM, not an independent Marathi reviewer. The smoke-test signal remains:
do not assume embeddings improve Marathi retrieval; BM25-only scored higher on
this small set.

A BM25-only `k1`/`b` sweep on the same 30 development queries reached its best
measured Recall@5 at `k1=1.5`, `b=1.0` (78.3%; scheme hit@5 90.0%), compared
with the current `k1=0.6`, `b=0.5` settings (65.0%; scheme hit@5 90.0%).
Other nearby settings varied materially, and the set is small, synthetic, and
AI-reviewed rather than independently reviewed. Do not apply a Marathi-only
parameter override or replace the shared settings based on this sweep; use it
only as a tuning hypothesis to test on reviewed, held-out Marathi queries.

Cross-set check of the current settings vs. the Marathi sweep candidate
(`k=5`, reranker disabled):

| Settings | Set | BM25-only Recall@5 / scheme hit | MiniLM + BM25 + RRF Recall@5 / scheme hit |
|---|---|---:|---:|
| Current `0.6 / 0.5` | English development (199) | 58.4% / 86.9% | 69.3% / 93.5% |
| Candidate `1.5 / 1.0` | English development (199) | 58.9% / 88.4% | 68.1% / 91.5% |
| Current `0.6 / 0.5` | Marathi draft (30) | 65.0% / 90.0% | 51.7% / 86.7% |
| Candidate `1.5 / 1.0` | Marathi draft (30) | 78.3% / 90.0% | 56.7% / 76.7% |

The candidate improves BM25-only recall on both sets but reduces hybrid scheme
hit rate on Marathi and both hybrid metrics on English. Keep the shared
production settings unchanged; the next useful experiment is retrieval-fusion
weighting (or BM25-only comparison) after independent Marathi review, not
promoting the Marathi BM25 optimum to a global hybrid setting.

### Fusion-weight experiment (2026-11-11)

Compared BM25-only, vector-only, and weighted RRF at vector contribution
weights 0.25, 0.5, 1, 2, and 4 (BM25 contribution held at 1; `k=5`,
reranker disabled). Each modality contributes one ranking per query variant.
No application defaults were changed.

| Vector weight | English-heavy dev (199): Recall@5 / scheme hit | Marathi draft (30): Recall@5 / scheme hit |
|---:|---:|---:|
| BM25-only (0) | 58.4% / 86.9% | 65.0% / 90.0% |
| 0.25 | 65.1% / 88.9% | 58.3% / 86.7% |
| 0.5 | 66.1% / 90.5% | 58.3% / 86.7% |
| 1 (current equal-weight RRF) | **69.3% / 93.5%** | 51.7% / 86.7% |
| 2 | 67.1% / 92.5% | 15.0% / 43.3% |
| 4 | 67.1% / 92.5% | 15.0% / 43.3% |
| Vector-only | 62.8% / 89.9% | 6.7% / 40.0% |

The English-heavy development set benefits most from equal-weight RRF; the
Marathi draft set performs best with BM25-only, and increasing vector weight
quickly degrades Marathi retrieval. In the equal-weight comparison, BM25-only
retrieved relevant passage(s) for five Marathi queries where RRF did not:
MR-BFFL-001, MR-BFFL-008, MR-BFFL-009, MR-EACS-005, and MR-NSMNY-007.
Conversely, vector fusion did not improve Marathi Recall@5 on this sample.
Because the Marathi set is synthetic and AI-reviewed, use this only as a
development signal: retain current production settings and, if needed, test
language-specific BM25 preference against independently reviewed Marathi cases.

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
