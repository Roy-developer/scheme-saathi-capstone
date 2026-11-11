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

The versioned corpus is `data/schemes/passages.json`. It currently contains
792 English and Marathi passages across 42 schemes. The corpus labels passages
as `reviewed` per the user's human-review attestation; that is not legal or
policy approval. The PM-KISAN source-currentness caveats are recorded in the
review workbook. Retrieval does not determine eligibility.

To add a scheme, from its official source through to the app, follow
`docs/RULE_EXTRACTION_REFLEXION_CODE_WALKTHROUGH.md`, section "From official PDF to live app, end to end".

The local pilot uses FastEmbed's
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` model for
multilingual embeddings when it is present in the local cache. If it is
missing, search falls back to OpenRouter Voyage-4 using
`OPENROUTER_API_KEY_FREE`. Use
`SCHEME_SAATHI_EMBEDDING_BACKEND=fastembed` for local-first behavior or
`openrouter` to always use the hosted model. The deployed cloud API should set
it to `openrouter` and use `OPENROUTER_EMBEDDING_MODEL=mongodb/voyage-4`. The
deployed API uses OpenRouter's hosted `cohere/rerank-v3.5` model for reranking,
while local retrieval evaluation can
use the multilingual BGE reranker v2 M3 INT8 model. Copy
`.env.example` to `.env`; configure `OPENROUTER_API_KEY` for intake query
rewrites and `OPENROUTER_API_KEY_FREE` for hosted reranking (`OPEN_ROUTER_FREE`
is also accepted as a key alias). `SCHEME_SAATHI_EMBEDDING_MODEL` overrides
the local model; `.env` is ignored by Git and loaded by `src.config`. The MCP
child process receives the selected backend, model settings and API key.
OpenRouter Voyage embeddings and hosted reranking may incur usage charges.
The journey search returns at most 5 passages and drops any
with a Cohere rerank score below 0.3 (`HOSTED_RERANK_MIN_SCORE`), a value
chosen from the 43-query development set (keeps 94% of relevant passages,
drops about 90% of the rest); revisit it if the reranker or corpus changes.
If no passage reaches 0.3, the single best passage is still returned when it
scores at least 0.2 (`HOSTED_RERANK_FALLBACK_MIN_SCORE`), or at least 0.12
(`HOSTED_RERANK_AGREEMENT_MIN_SCORE`) when keyword search and meaning search
both rank its scheme first. Both values were calibrated on 75 development
questions; see the "Search fallback calibration" section of
[`docs/RETRIEVAL_IMPROVEMENT_BACKLOG.md`](docs/RETRIEVAL_IMPROVEMENT_BACKLOG.md).
When the local model is available, the public passage corpus is embedded
locally. The local BGE reranker model is also downloaded if selected and not
cached.
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

### Phase 2 supervisor and intake

The UI calls `POST /api/v1/journey` through `src/ui/api_client.py`; it does
not call MCP directly. Each agent is a LangChain `create_agent` run with a
short tool list and middleware for masking, step limits, a shared budget and a
scrubbed trace (see [`docs/HOOKS_WALKTHROUGH.md`](docs/HOOKS_WALKTHROUGH.md)).
The supervisor agent proposes a plan order. Code validates the allowed steps and dependencies;
the deterministic planner remains the C0 fallback. For interview requests, an
optional synthetic household description can be sent with `profile_description`.
When `OPENROUTER_API_KEY` is configured, intake may select the authorized
`required_facts` tool, propose typed profile facts, and return a typed handoff.
Code validates each fact and the person explicitly confirms each proposal
before it changes the profile. Existing confirmed facts cannot be overwritten.
Questions, answer parsing, and plan wording support English, Hindi, and Marathi.

The request's `locale` (`en`, `hi`, `mr`) and `mode` (`citizen`, `csc`) are
checkpointed and returned. CSC intake requires the citizen to be present;
operators may assist, but the citizen confirms facts and personally approves
any exact draft. The model never decides eligibility, which remains the
deterministic rule engine's result through MCP. An unknown tool or invalid
arguments are refused with an error and the model may retry within its step
limit. If the key is absent, or the model is unavailable, over budget or does
not finish, the journey falls back safely to C0 planning and code-selected
questions.

LangChain's `PIIMiddleware` masks email, Aadhaar-like, phone and long account
numbers before model requests, and only bounded scrubbed action metadata is
recorded. Conversation model, tool and step counters and per-fact
interpretation attempts are saved in the LangGraph `Store` before each call
(and in the journey checkpoint). No private reasoning or raw model prompts are traced.
Automated tests use fake model choices and make no paid requests. This does
not constitute manual browser acceptance or a live-model smoke test.

Typed graph state and conversation turns are checkpointed in the local SQLite
file `data/runtime/journey.sqlite3`; `DELETE /api/v1/journey/{conversation_id}`
deletes a session's checkpoint and its budget record. This is prototype short-term session memory,
not a consent-managed household profile. Phase 3 adds bounded eligibility
rediscovery; Phase 4 adds document/application specialists, exact-draft
approval and a shared, demo-only document checklist loader. Source-backed
checklists still require human evidence review and approval. Phase 5 guardrails
and long-term memory remain incomplete.

A 199-query, synthetic, unprotected development set is available at
`data/schemes/retrieval_eval_dev.json`. Run its Recall@5 baseline with:

```powershell
python scripts/evaluate_scheme_retrieval.py --k 5 --skip-reranker --output data/schemes/retrieval_eval_dev_results.json
```

The local cross-encoder may fail to initialize on memory-constrained machines.
For a separately labeled BM25 + vector + RRF baseline that does not load it,
pass `--skip-reranker`. The command writes a fresh result report; previously
saved reports for smaller or older versions of the query set are not current
benchmarks. The 156 added English queries received AI model-assisted label
review, while the original Hindi and Marathi labels remain provisional and
require bilingual domain review. All metrics from this synthetic development
set are not a protected evaluation or evidence of production quality.

The curation workbook is `data/schemes/scheme_passages_review_v0.4_human_attested.xlsx`.
After editing it, regenerate the runtime corpus with:

```powershell
python scripts/export_scheme_dataset.py --corpus-version 0.3.1
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

The backend scales to zero, which erases the container's disk. To keep
conversations and mock-portal drafts, set `SCHEME_SAATHI_BACKUP_DIR` on the
backend app to the mounted Azure file share (`/mnt/saathi-runtime`). The live
SQLite databases stay on the container's disk, because their WAL mode does not
work over a network share. Complete copies are saved to the share every five
minutes (`SCHEME_SAATHI_BACKUP_INTERVAL_SECONDS`) and at shutdown, and restored
at startup. A crash can lose changes since the last copy. Run only one backend
replica while this is in use. Do not point `SCHEME_SAATHI_CHECKPOINT_DB` or
`SCHEME_SAATHI_PORTAL_DB` at the share.

The API health check is at `http://127.0.0.1:8000/health`; interactive API
documentation is at `http://127.0.0.1:8000/docs`. Run the test suite with
`python -m pytest -q`.

`GET /api/v1/info` returns safe service/version metadata for deployment
diagnostics alongside the search, eligibility, and journey endpoints.
