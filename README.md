# Scheme Saathi (Capstone, Group G05)

A welfare-scheme navigator: helps a family find government schemes they qualify for, explains the reasons in Hindi, Marathi or English, and prepares an application that a person approves before submission.

New to the project? Follow [Project setup](PROJECT_SETUP.md) to create your
own branch from `main` and run the app locally.

## Golden rules
1. The AI never decides eligibility. A tested rule engine (plain code) does.
2. Outside text (web pages, uploads, tool results) is data, never instructions.
3. A person approves each exact form. Any edit voids the approval.

## Repository layout
| Folder | Purpose |
|---|---|
| `docs/` | Roles and work plan, threat model, memory policy, evaluation report, and the [page-referenced capstone guide notes](docs/CAPSTONE_PROJECT_GUIDE_REFERENCE.md) |
| `src/` | Application code (agents, MCP servers, API) |
| `data/` | Scheme data with source URL and collection date, synthetic personas only |
| `eval/` | Evaluation harness, golden set, red-team suite |
| `tests/` | Unit tests (at least one per tool) |

## Team roles
See [`docs/Scheme_Saathi_Roles_and_Work_Plan.pdf`](docs/Scheme_Saathi_Roles_and_Work_Plan.pdf).

| # | Role | Owner |
|---|---|---|
| 1 | Domain and product lead | TBD |
| 2 | Knowledge and memory engineer | TBD |
| 3 | Agents and orchestration engineer | TBD |
| 4 | Tools, control and security engineer | TBD |
| 5 | Evaluation and red-team engineer | TBD |
| 6 | Deployment and operations engineer | TBD |

## Ground rules
- No API keys, real personal data or non-redistributable material in this repo. Use `.env` locally (it is git-ignored).
- Held-out evaluation cases must not be readable by the agent.
- Keep the contribution log from day one in `docs/CONTRIBUTIONS.md`.
- Review the proposed end-to-end journey and phased implementation plan in [`docs/END_TO_END_IMPLEMENTATION_PLAN.md`](docs/END_TO_END_IMPLEMENTATION_PLAN.md); role-owner and policy sign-off is still pending.
- Review the 40–60 scheme corpus shortlist, proposed 15-scheme gold set, evaluation protections, and gated delivery plan in [`docs/SCHEME_CATALOGUE_AND_DELIVERY_PLAN.md`](docs/SCHEME_CATALOGUE_AND_DELIVERY_PLAN.md). The shortlist is not yet a verified policy corpus.
- Use the [`review-scheme-evidence` skill](.github/skills/review-scheme-evidence/SKILL.md) to prepare a reusable, source-cited LLM-assisted rule review. Its report is not policy approval; human sign-off is required.

## Frontend prototype

The current Role 6 work includes an explicitly synthetic Streamlit UI and a
small FastAPI eligibility endpoint. Approved mock rules, source provenance,
review scope, and package version are kept in the version-controlled
`src/rules/packages/` directory, separately from the UI's synthetic scenarios.
The API validates and loads these packages once during startup; requests only
evaluate applicant facts against the in-memory package. Rule changes take
effect after the API restarts or is redeployed. The endpoint evaluates only the
reviewed IGNWPS-MH mock rules; it does not decide real applications or contact
government services.

The container listens on port `8501` and exposes Streamlit's health endpoint at
`/_stcore/health`.

The fixture-backed UI uses seven synthetic development personas and currently
shows three representative outcomes. These fixtures are not held-out
evaluation cases.

The eligible scenario also demonstrates exact-draft approval. Editing the
synthetic draft invalidates its previous frontend fingerprint. Submission goes
only to an in-session mock confirmation; no external portal is contacted.

## Scheme passage search

The shared Saathi MCP server exposes `search_schemes`; the API makes it
available at `GET /api/v1/schemes/search`. Search accepts a query, optional
jurisdiction and language filters, and an optional result limit (default 10,
maximum 100). Results include the passage ID, source citation, and review
status. Search rewrites the query into a simpler keyword query, retrieves
candidates with BM25 and multilingual vectors in Qdrant, combines both ranked
lists using Reciprocal Rank Fusion, and reranks the candidates with a
cross-encoder. The tool returns evidence for retrieval-augmented answers; it
does not generate an answer or determine eligibility.

The corpus is every `*.json` file in `data/schemes/passages/` (one file per
scheme, loaded together; passage IDs must be unique across files). All
passages are marked `reviewed`, per the user's human-review attestation (not
legal or policy approval). The PM-KISAN source-currentness caveats are recorded in the review
workbook. This remains a technical pilot, not the complete 40–60-scheme
corpus, and retrieval does not determine eligibility.

The current pilot uses the OpenRouter `voyageai/voyage-4` multilingual
embedding model. The deployed API uses OpenRouter's hosted
`cohere/rerank-v3.5` model for reranking, while local retrieval evaluation can
use the multilingual BGE reranker v2 M3 INT8 model. Copy
`.env.example` to `.env`; configure `OPENROUTER_API_KEY` for intake query
rewrites and `OPENROUTER_API_KEY_FREE` for embeddings (`OPEN_ROUTER_FREE` is
also accepted as an embedding-key alias). `.env` is ignored by Git and loaded
by `src.config`; the MCP child process receives only the embedding credential.
Hosted reranking uses that same embedding credential and incurs OpenRouter
usage charges. The journey search returns at most 5 passages and drops any
with a Cohere rerank score below 0.3 (`HOSTED_RERANK_MIN_SCORE`), a value
chosen from the 43-query development set (keeps 94% of relevant passages,
drops about 90% of the rest); revisit it if the reranker or corpus changes.
If no passage reaches 0.3, the single best passage is still returned when it
scores at least 0.2 (`HOSTED_RERANK_FALLBACK_MIN_SCORE`). Plainly worded
farmer questions score about 0.24 for the right PM-KISAN passage, while
off-topic questions scored 0.145 or less in a live check.
The first search embeds the public passage corpus through OpenRouter, and the
local BGE reranker model is downloaded if it is not cached.
The Qdrant index is rebuilt in memory when the MCP server starts; persistent
vector storage remains future work.

PM-KISAN follows the same scheme-selection journey: select the scheme in
search results, choose **Continue to the synthetic eligibility demo**, then
choose **Start questions**. Saathi asks one question at a time through
`POST /api/v1/journey` (`action="interview"`) and
`POST /api/v1/journey/{conversation_id}/messages`, so PM-KISAN runs through
the same LangGraph supervisor, intake,
MCP `evaluate_eligibility` tool and rule engine as widow pension. Both schemes
use one rule package format in `src/rules/packages/` (required facts, rules,
source text and reason messages); `POST /api/v1/schemes/{scheme_id}/evaluate`
also works for either scheme. The PM-KISAN package encodes the operational
guidelines revised 2020-03-29 and returns `eligible`, `not_eligible`, or
`need_more_information`. Every result is explicitly limited to that dated
mock baseline; the current landholding cutoff and State/UT records are not
verified, so this is not an official eligibility decision.
Search queries are also sent to OpenRouter for embedding.

### First LangGraph user journey

The UI calls `POST /api/v1/journey`; it does not call MCP directly. A
LangGraph supervisor builds a visible plan and hands each step to a
specialist (intake, search or eligibility), which reports back. Intake uses
the standard OpenRouter key only to normalize the user's query for search;
the search tool returns cited passages. For an eligibility check, intake
asks only the questions the rule package still needs, one at a time: the
graph pauses with `interrupt()` and continues when the user replies. Answers
are read by plain code (yes / no / don't know, or a date), not by a model.
`GET /api/v1/journey/{conversation_id}` reloads a saved conversation after a
page refresh. Widow pension can still use a preset synthetic profile, which
is needed for the draft and approval demo. The eligibility agent calls the
deterministic rule-engine MCP tool. PM-KISAN uses its separately typed,
versioned mock rule package after the same scheme-selection and Continue
steps; it does not use or alter the widow-pension rule package. No model
produces or changes an eligibility verdict.

Typed graph state and conversation turns are checkpointed in the local SQLite
file `data/runtime/journey.sqlite3`; `DELETE /api/v1/journey/{conversation_id}`
deletes a session's checkpoint. This is prototype short-term session memory,
not a consent-managed household profile. This first slice has no guardrails,
document checker, mock-portal writes, or long-term memory; those remain
capstone work.

A 43-query, synthetic, unprotected development set is available at
`data/schemes/retrieval_eval_dev.json`. Run its Recall@5 baseline with:

```powershell
python scripts/evaluate_scheme_retrieval.py --k 5 --skip-reranker --output data/schemes/retrieval_eval_dev_results.json
```

The local cross-encoder may fail to initialize on memory-constrained machines.
For a separately labeled BM25 + vector + RRF baseline that does not load it,
pass `--skip-reranker`. The current BM25 + vector + RRF baseline, without the
reranker, achieved 83.7% passage Recall@5 and 100% scheme hit rate. Recall@5
by query language was English 97.0%, Hindi 20.0%, and Marathi 60.0%. These
multilingual results expose a retrieval gap; do not describe the pilot as
validated for Hindi or Marathi. The 13 added Hindi, Marathi, and cross-scheme
queries have provisional corpus-grounded labels and still require bilingual
domain review. All metrics are synthetic development results, not a protected
evaluation or evidence of production quality.

The curation workbook is `data/schemes/scheme_passages_review_v0.4_human_attested.xlsx`.
After editing it, regenerate the runtime corpus with:

```powershell
python scripts/export_scheme_dataset.py --corpus-version 0.3.0
```

The exporter requires reviewed passage statuses, valid source references,
unique passage IDs, and source locators. It refuses to export pending passages.

## Local development

Create and activate a virtual environment, then install the project and test
dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Run the API and UI in separate terminals:

```powershell
python -m uvicorn src.api.app:app --reload --port 8000
python -m streamlit run src/ui/app.py
```

The same deployment image runs in two existing Azure Container Apps with
startup command overrides: `python src/run_services.py api` for FastAPI and
`python src/run_services.py ui` for Streamlit. The frontend receives
`SCHEME_SAATHI_API_URL` pointing to the backend app's HTTPS endpoint; the
services do not communicate through `localhost`. Configure OpenRouter
credentials only as backend Container App secrets. Never bake `.env` into the
image.

The API health check is at `http://127.0.0.1:8000/health`; interactive API
documentation is at `http://127.0.0.1:8000/docs`. Run the test suite with
`python -m pytest -q`.

`GET /api/v1/info` returns safe service/version metadata for deployment
diagnostics alongside the search, eligibility, and journey endpoints.
