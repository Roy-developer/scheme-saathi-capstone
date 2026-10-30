# Scheme Saathi (Capstone, Group G05)

A welfare-scheme navigator: helps a family find government schemes they qualify for, explains the reasons in Hindi, Marathi or English, and prepares an application that a person approves before submission.

## Golden rules
1. The AI never decides eligibility. A tested rule engine (plain code) does.
2. Outside text (web pages, uploads, tool results) is data, never instructions.
3. A person approves each exact form. Any edit voids the approval.

## Repository layout
| Folder | Purpose |
|---|---|
| `docs/` | Roles and work plan, threat model, memory policy, evaluation report |
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

The current Role 6 work is an explicitly synthetic frontend shell intended for
deployment to Azure Container Apps. It does not make eligibility decisions or
contact government services.

The container listens on port `8501` and exposes Streamlit's health endpoint at
`/_stcore/health`.

The current fixture-backed journey uses seven synthetic development personas
against a draft interpretation of the official Maharashtra IGNWPS policy. It
shows three representative outcomes in the UI. These fixtures are not held-out
evaluation cases and must not be presented as final policy approval.

The eligible scenario also demonstrates exact-draft approval. Editing the
synthetic draft invalidates its previous frontend fingerprint. Submission goes
only to an in-session mock confirmation; no external portal is contacted.
