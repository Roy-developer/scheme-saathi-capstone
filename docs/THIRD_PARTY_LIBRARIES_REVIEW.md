# Proposal: make Saathi's code simpler with third-party libraries

**To:** GitHub Copilot (or any developer making the change)
**Goal:** replace hand-written plumbing with standard libraries where that makes the
code shorter and easier to follow, **without** weakening any safety behaviour or test.

The proposal has 6 changes, in priority order (biggest win, lowest risk first).
Part 3 lists what should **not** change and why. The Appendix is the full inventory
of hand-built code, with file and line references, that the proposal is based on.

---

## Outcome (2026-11-05, branch `supervisor-redesign-2`, commit `34cafd5`)

The proposals below were checked against the code, then applied or skipped.
Full test suite after the changes: **419 passed** (415 before, plus 4 new tests).

| # | Outcome | What actually happened |
|---|---|---|
| P1 | **Done for chat calls** | `src/llm_client.py` → class `OpenRouterChatClient` (openai SDK, `max_retries=0`). Used by the agent tool choice, query rewrite and answer reading. The provider keeps one connection and closes it at API shutdown. **Embeddings and rerank stay on `urllib`**: the integration tests block paid calls by replacing `urllib.request.urlopen`, and moving them would silently remove that guard. |
| P2 | **Skipped** | The real end-to-end tests route UI and portal HTTP through an `urllib` bridge. Rebuilding it costs more than the ~30 lines saved. |
| P3 | **Done** | `graphlib.TopologicalSorter`; new test passes on old and new code. |
| P4 | **Done** | `filelock.FileLock(..., is_singleton=True)`. A new `FileLock` object per call would wait for itself when nested; the singleton nests correctly. Cross-process blocking verified. |
| P5 | **Skipped** | The three retry loops record different events and treat the budget differently; one helper would need several callbacks and be harder to read. |
| P6 | **Skipped** | The current "create/add if missing" setup is short and safe to repeat; version numbers add a concept without simplifying. |
| A5 | **Done** | Duplicate `Authorization` header removed. |

**Correction to the P1 example below.** It builds the client once at import time
(`_client = AsyncOpenAI(api_key=os.getenv(...))`). That reads the key too early: the
code and tests set the key at call time. The implemented class takes the key when it
is created, and the intake functions create it per call (`async with
OpenRouterChatClient(key) as chat:`). Tests use one shared `fake_openrouter` fixture
(`tests/conftest.py`) instead of replacing `urlopen`.

See **Part 5** for the further simplifications made after an end-to-end review.

---

## Part 1: rules for making these changes

1. **Verify before changing.** Open the listed lines and confirm the description is
   still true. If it is not, stop and report what you found.
2. **One proposal at a time.** Each proposal is a separate commit or PR.
3. **Run the full test suite after each step** (`.venv/Scripts/python -m pytest`).
   If any test fails, fix the change, not the test, unless the test checks
   behaviour this proposal intentionally removes. In that case, say so explicitly.
4. **Keep every item in "Must keep".** If a library cannot keep one of them, do not
   use the library for that part; report it instead.
5. **Do not touch Part 3 items.**
6. **Add new packages to `dependencies` in `pyproject.toml`.** Some packages are
   already installed only because another package depends on them ("indirect").
   Code must not rely on that.

Environment when this proposal was made: Python 3.11+, `langgraph 0.6.11`,
`langchain-core 1.7.3`, `qdrant-client 1.20.0`, `fastembed 0.9.1`, `mcp 2.x`,
`pydantic 2.x`, `httpx 0.28.1`, `filelock 4.2.6` (indirect). Not installed:
`openai`, `langchain`, `langchain-openai`, `sqlalchemy`, `alembic`, `babel`, `tiktoken`.

---

## Part 2: the proposals

### Summary

| # | Proposal | Replaces | Library | New dependency? | Lines saved (estimate) | Risk |
|---|---|---|---|---|---|---|
| P1 | One OpenRouter client file | A1-A7 | `openai` SDK (+ `httpx` for rerank) | Yes: `openai` | 250-350 | Medium |
| P2 | Use `httpx` for internal HTTP calls | A8, A9, A10 | `httpx` | Move from `dev` extra to `dependencies` | 40-80 | Low |
| P3 | Standard-library cycle check | A16 | `graphlib` | No (stdlib) | ~15 | Very low |
| P4 | Library file lock | A13 | `filelock` | Yes: add `filelock` | ~45 | Low-medium |
| P5 | One shared "try twice" helper | A11 | None (own helper) | No | ~30 | Low |
| P6 | Versioned database setup | A14 | SQLite `PRAGMA user_version` | No | ~10 (clearer, not shorter) | Low |

### The pattern behind P1 and P2 (reuse it for any outside service)

Put **all** code that talks to one outside service in **one file**. The rest of the
app only calls that file's functions.

| Rule | Why |
|---|---|
| 1. Settings in one place (key from `.env`, URL, timeout, retries) | Changing provider means editing one file |
| 2. One function per job (`ask_for_json`, `embed`, …) | Callers read like plain English |
| 3. Turn every failure into one error class of your own | Callers catch one error type |
| 4. Check every reply with a Pydantic model | Bad data stops at the door |
| 5. Tests replace those functions with fakes | Tests run offline, free and fast |

```
src/<service>_client.py
  ├─ settings (key from .env, URL, timeout, retries)
  ├─ class <Service>Error(RuntimeError)
  └─ one async function per job → returns a Pydantic model or raises <Service>Error
```

---

### P1. One OpenRouter client file (`src/llm_client.py`) — done (chat calls)

**Today:** 5 separate hand-written `urllib` requests to OpenRouter, each building
headers, sending, catching errors and parsing JSON on its own:

| Where | Job |
|---|---|
| `src/workflow/agent_runtime.py:173-258` (`OpenRouterToolChoiceProvider._choose`) | Agent picks a tool |
| `src/workflow/intake.py:40-150` (`_read_free_text_answer`) | Read a free-text answer |
| `src/workflow/intake.py:163-240` (`_rewrite_query`) | Rewrite a search query |
| `src/api/scheme_search.py:169-235` (`OpenRouterEmbeddings.embed`) | Embeddings |
| `src/api/scheme_search.py:85-166` (`OpenRouterReranker.__call__`) | Rerank |

The duplication also shows up in smaller ways:
- `OPENROUTER_CHAT_URL` and `DEFAULT_CHAT_MODEL` are defined twice (`intake.py:15-16`, `agent_runtime.py:32-33`).
- The `Authorization` header is set twice per request (`intake.py:121, 205`, `scheme_search.py:131, 203`).
- `intake.py:78-107` writes by hand a JSON schema that copies the Pydantic model at `intake.py:23-36`.

**Change:** one file using the official `openai` SDK. The same OpenRouter key works,
because OpenRouter accepts the OpenAI request format. Only `base_url` changes.

```python
"""The only file that talks to OpenRouter."""

import os
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    default_headers={"HTTP-Referer": "https://scheme-saathi.local", "X-Title": "Scheme Saathi"},
    timeout=20,          # MODEL_TIMEOUT_SECONDS
    max_retries=0,       # IMPORTANT, see "Budget warning" below
)
MODEL = os.getenv("OPENROUTER_CHAT_MODEL", "openai/gpt-4o-mini")   # keep "provider/model" names


class LLMError(RuntimeError):
    pass


async def ask_for_json(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    """Ask the model for a reply shaped like `schema`."""
    try:
        reply = await _client.chat.completions.create(
            model=MODEL, temperature=0, max_tokens=512,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        return schema.model_validate_json(reply.choices[0].message.content)
    except (OpenAIError, ValidationError, IndexError, TypeError) as error:
        raise LLMError("The model is unavailable or replied badly.") from error
```

A caller then shrinks. For example, `_rewrite_query` goes from about 75 lines to:

```python
class Rewrite(BaseModel):
    search_query: str = Field(min_length=1, max_length=500)

async def rewrite_scheme_query(query: str) -> str:
    result = await ask_for_json(REWRITE_PROMPT, query, Rewrite)
    return result.search_query.strip()
```

Tests can fake it with no internet:

```python
async def fake_ask_for_json(system, user, schema):
    return schema(search_query="pm kisan farmer support")

monkeypatch.setattr("src.workflow.intake.ask_for_json", fake_ask_for_json)
```

**Facts for this change**

| Topic | Fact |
|---|---|
| Keys | `OPENROUTER_API_KEY` is used for chat; `OPENROUTER_API_KEY_FREE` for embeddings and rerank. Use one client per key. |
| Tool choice (A1) | `client.chat.completions.create(tools=..., tool_choice="required", parallel_tool_calls=False)`; token counts are in `reply.usage` |
| Embeddings | `client.embeddings.create(model=..., input=[...])` |
| Rerank | **Not in the OpenAI SDK.** OpenRouter's `/rerank` is its own endpoint. Write one small `httpx` function for it in the same file. |
| OpenRouter-only options | `extra_body={...}` / `extra_headers={...}` |
| Speed | The SDK is **not** slower in practice. Its own overhead is about 1 ms, against a 1-10 s model call. It reuses connections, while today's `urllib` code opens a new secure connection on every call, and it is truly async, so `asyncio.to_thread` is no longer needed. |

**Budget warning (must read).** The SDK retries failed requests by itself. In a test
with `max_retries=2`, **one** failing call made **3** real requests. Saathi reserves
one model call in its budget *before* each call (`run_accounted_model_call`,
`agent_runtime.py:261-339`). Hidden retries would therefore allow up to 3× the real
calls the budget permits. Use `max_retries=0`.

**Verified:** the client code above was run with `openai 3.45.0` and a fake network
(`httpx.MockTransport`; no real key, no real calls). The request goes to
`https://openrouter.ai/api/v1/chat/completions` with `Authorization: Bearer <key>`
and `X-Title`. A non-JSON reply and an HTTP 503 both become `LLMError`, and
`embeddings.create` works. **Not yet verified against the live OpenRouter API.**

**Steps (run tests after each one):**
1. Add `openai` to `pyproject.toml` and install it.
2. Create `src/llm_client.py` as above.
3. Move `_rewrite_query`.
4. Move `_read_free_text_answer`.
5. Move `OpenRouterToolChoiceProvider._choose`.
6. Move embeddings, and write the rerank function with `httpx`.
7. Delete the unused `urllib` code and the duplicate constants.

**Must keep**
- The `ToolChoiceProvider` Protocol (`agent_runtime.py:120`), so the test fakes such as `ScriptedProvider` still work.
- `AgentModelError` and `IntakeAgentError` raised on every failure, with the same messages. You may keep them as subclasses of, or wrappers around, `LLMError`.
- Token counts from `usage`.
- `tool_choice="required"`, `parallel_tool_calls=False` and `strict=True` on tool definitions.
- The system prompt text.
- Code-fence stripping (`intake.py:139-147`).
- The 500-character and empty-result checks (`intake.py:229-239`).
- Rerank index validation (`scheme_search.py:146-163`) and embedding dimension checks (`scheme_search.py:225-231`).

**Check before using `model_json_schema()` for `AnswerInterpretation`:** OpenAI
strict mode needs **every** field listed in `required`, but Pydantic leaves out
fields that have defaults (`value`). If the generated schema is rejected, keep
the hand-written schema.

---

### P2. Use `httpx` for internal HTTP calls — skipped

**Today:** hand-written `urllib` code in:
- `src/mcp_servers/tools/applications.py:56-100` (`_call_portal`)
- `src/ui/api_client.py:58-89` (`_send`), plus lines 194 and 226
- `src/api/portal_service.py:75-95` (the health-check polling loop)

**Change:** use `httpx` (`httpx.post(...)`, `response.raise_for_status()`,
`response.json()`). Move `httpx` from the `dev` extra to `dependencies`.
Keep the health-check polling as a plain loop; it is short and clear.
`tenacity` is not needed.

**Must keep**
- Every error is turned into the same error class (`MCPToolError`, `JourneyApiError`, `ApplicationApiError`).
- HTTP 409 shows the "no longer waiting" message (`api_client.py:70-77`).
- Replies are validated with `JourneyResponse`.
- The HMAC proof check (`portal_service.py:86-88`).
- Startup fails if the child process exits.
- The existing timeouts (1, 5, 10 and 30 seconds).

---

### P3. Standard-library cycle check — done

**Today:** `src/rules/facts.py:317-337` (`_validate_acyclic`) is a depth-first search written by hand.

**Change:**

```python
from graphlib import CycleError, TopologicalSorter

graph = {
    fact_id: [d for d in definition.derived_from if d in by_id]
    for fact_id, definition in by_id.items()
}
try:
    TopologicalSorter(graph).prepare()
except CycleError as error:
    raise ValueError("Derived fact definitions contain a cycle") from error
```

**Verified:** `graphlib` detects a cycle with the installed Python.

**Must keep**
- The same error message.
- Dependencies that are not in the registry are ignored (`facts.py:330`).

---

### P4. Library file lock — done

**Today:** `src/documents/publication.py:33-81` locks the file by hand, with
Windows (`msvcrt`) and POSIX (`fcntl`) branches, a polling loop, and its own
thread-local bookkeeping so that nested use does not deadlock.

**Change:** use `filelock` with **one shared `FileLock` object per lock file**:

```python
from filelock import FileLock, Timeout

_LOCKS: dict[str, FileLock] = {}
_LOCKS_GUARD = threading.Lock()

def _shared_lock(lock_path: Path) -> FileLock:
    key = str(lock_path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, FileLock(key, timeout=10))
```

**Trap (verified with `filelock 4.2.6`):** creating a **new** `FileLock` object for
the same file inside a block that already holds the lock **does not nest**. It waits
until the timeout and then raises `Timeout`. A **shared** object nests correctly in
the same thread and still blocks other threads. So always use `_shared_lock(...)`;
never write `FileLock(path)` at the call site.

**Must keep**
- Nested use in the same thread works.
- Other threads and processes are blocked.
- The 10-second timeout.
- The `RuntimeError("The document checklist publication lock is unavailable.")` message (convert `Timeout` to it).

---

### P5. One shared "try twice" helper — skipped

**Today:** three separately written retry loops in `src/workflow/journey.py`:
- discovery, `:640-660`
- eligibility, `:2275-2288`
- scheme search, `:2347-2370`

**Change:** one helper, for example `async def call_with_one_retry(call, *, on_retry, on_fail, reserve=None)`,
used by all three. Do **not** use LangGraph `RetryPolicy` for this. It re-runs the
whole node, so it would lose the retry events and the budget counting.

**Check first:** discovery and search reserve each attempt with `reserve_counters`
**before** the call. The eligibility loop appears not to. Report whether that
difference is intentional before you merge them.

**Must keep**
- Each budgeted attempt is reserved before the call.
- The `tool_retry` and `tool_failed` history events, with their current text.
- The stop at `MAX_DISCOVERY_CALLS`.

---

### P6. Versioned database setup — skipped

**Today:** `src/portal/repository.py:111-186` (`_connect`) creates tables and checks
for missing columns with `PRAGMA table_info` + `ALTER TABLE` on **every** connection.

**Change:** keep a numbered list of setup steps and run only the new ones, using
SQLite's `PRAGMA user_version`. This adds no new dependency. Alembic is not
needed for one small SQLite file.

**Must keep**
- Existing databases upgrade correctly (test with a database created by the current code).
- WAL mode.
- `BEGIN IMMEDIATE` transactions (line 367).

---

## Part 3: do NOT change (and why)

| Item | Why it stays as it is |
|---|---|
| Agent loop `run_react_loop` (`agent_runtime.py:342-494`) | A library loop (`create_react_agent`, LangChain `create_agent`) lacks typed stop statuses, per-action actor checks, output schemas and budget reservation before each call. Test `tests/test_planning_and_intake_agents.py` ("blocked means never ran") depends on it. |
| Allow-list and `ServiceClientRouter` (`agent_runtime.py:35-52`, `service_routing.py`) | No library has Saathi's actor roles. A forbidden request must make zero tool calls. |
| Conversation budgets (`run_accounted_model_call`, `conversation_budget.py`) | They must be saved **before** each call and kept across HTTP requests. LangChain's call-limit middleware is not installed and works per run. |
| `mask_sensitive_text` (`agent_runtime.py:497-503`) | Aadhaar and Indian phone formats need custom patterns anyway; it is only 12 lines. |
| Trace (`AgentTraceEvent`, `_merge_agent_trace`) | It is shown to the user and must hold no prompts or personal data. Callbacks and LangSmith capture both. |
| `recover_authorized_action` (`agent_runtime.py`) | A business rule, not a model fallback or a retry. |
| `_serialize_journey` (`journey.py:2591-2608`) | No library serializes runs per conversation. |
| Search fusion (`scheme_search.py:511-534`) | Qdrant's built-in fusion exists, but the search thresholds were tuned on a 43-query dev set. Change it only with a re-run of that evaluation. |
| SQLAlchemy for `repository.py` | A ~900-line rewrite of approval and token logic. The risk is too high for the gain. |
| `gettext` / `babel` for Hindi and Marathi text | Large churn across 4 files. Do it as a separate project if translations grow. |
| `tiktoken` for token estimates | OpenRouter serves many models with different tokenizers. The estimate must never under-count. |
| Date parsing (`questions.py:387-399`) | Fixed formats are stricter than `dateutil`, which guesses ambiguous dates. |
| `_atomic_replace`, `_unique_json_object`, rule operators | Already the simplest correct form. |
| `run_services.py` | Short and works. A process manager adds a tool without removing much code. |
| LangGraph `CachePolicy`, `interrupt_before`, `pre_model_hook`; LangChain middleware | See Appendix D. Each either needs the agent loop replaced or loses required behaviour. |

**Optional, low priority:** a `BaseCallbackHandler` (installed) for **server-side** logs
of node names, durations and error types only, never node inputs or outputs.

---

## Part 4: what to report back

For each proposal P1-P6:
1. **Done**, **skipped** or **blocked**, with the reason.
2. Lines removed and lines added.
3. The test result.
4. Any "Must keep" item you could not keep.

Also report any hand-built code this proposal missed.

---

## Part 5: end-to-end simplification review (done)

Every file in `src/` was mapped, the long functions were read in full, and a
duplicate-code detector was run. A second model (Fable 5.1) checked each finding
against the code before changes were made; it rejected one proposed change (F5,
below) and found five duplicates that were missed. All items keep behaviour
unchanged; each was followed by its targeted tests, then the full suite.

| # | Change | Where | New name to search for |
|---|---|---|---|
| 1 | Fixed 90 lines of irregular indentation (AST identical) | `journey.py` | — |
| 2 | One "ask a question" builder and one "no question pending" reset | `journey.py` intake (438 → 301 lines) | `ask()`, `ask_next_proposal()`, `_with_fact()`, `NO_PENDING_QUESTION` |
| 3 | One blocking helper for the application step (11 copies); document conditions built once; comment on the intentional second draft fetch | `journey.py` | `fail()` |
| 4 | Inline text moved to where text lives | `supervisor.py`, `questions.py` | `replan_reason()`, `direct_answer_question()`, `confirm_yes_or_no_question()` |
| 5 | Portal helpers (4 + 3 copies) | `portal/repository.py` | `_revoke_unsubmitted_approvals()`, `_recheck_checklist()` |
| 6 | One "check documents and bind" step for the journey and the API re-check, so both build identical fingerprints | `api/applications.py` | `check_and_bind_documents()` |
| 7 | UI repeats merged | `ui/app.py` | `interview_request()`, `render_history()`, `APPLICATION_STATE_KEYS` |
| 8 | One decimal/date converter; the journey's copy now applies the strict decimal check (rejects `"1_000"`, `"abc"`) | `rules/facts.py` | `encode_wire_value()`, `decode_wire_value()` |
| 9 | One helper for "MCP tool failed → HTTP error" (14 blocks) | `api/app.py` | `_tool_failure()` |

**Rejected after the second-model check**
- **Raising instead of returning `{}` in the application step.** Without a model,
  `run_application_specialist` catches every error, so the specific reason would be
  lost; with a model, a raise lets the action be retried. `fail()` keeps `return {}`.
- **Swapping `dict(budget)` for `copy_agent_budget(budget)`.** Not equivalent: the
  second also normalizes bad values.
- **Splitting `_portal_action_transaction` per action.** Some paths save stale marks
  and then raise on purpose; the shared prelude must run in order.

**Left for later**
- Splitting the 2,000-line `build_journey_graph` into a class or modules. Items 2–4
  made the nodes smaller first; `registered_intake_result` and `discover_candidates`
  are the next candidates to move out as plain functions.
- Moving embeddings/rerank to the SDK (needs the integration network guard extended).
- The eligibility retry loop does not count its retry against any budget. Decide
  whether that is intended.

---

## Appendix: full inventory of hand-built code

### A. Could use a library

| ID | Location | What the code does by hand | Library | Installed? | Proposal |
|---|---|---|---|---|---|
| A1 | `src/workflow/agent_runtime.py:173-258` | OpenRouter tool-choice request via `urllib` in `asyncio.to_thread` (line 165) | `openai` SDK | No | P1 |
| A2 | `src/workflow/intake.py:40-150` | OpenRouter `json_schema` request | `openai` SDK | No | P1 |
| A3 | `src/workflow/intake.py:163-240` | OpenRouter `json_object` request | `openai` SDK | No | P1 |
| A4 | `intake.py:15-16`, `agent_runtime.py:32-33` | Duplicate URL and model constants | None needed | n/a | P1 |
| A5 | `intake.py:121, 205`; `scheme_search.py:131, 203` | Duplicate `Authorization` header | None needed | n/a | P1 |
| A6 | `intake.py:78-107` | Hand-written JSON schema copying a Pydantic model | `model_json_schema()` | Yes | P1 (check strict mode) |
| A7 | `src/api/scheme_search.py:85-166`, `:169-235` | OpenRouter rerank and embeddings via `urllib` | `openai` SDK (embeddings), `httpx` (rerank) | Partly | P1 |
| A8 | `src/mcp_servers/tools/applications.py:56-100` | Portal POST via `urllib` | `httpx` | Yes (dev + indirect) | P2 |
| A9 | `src/ui/api_client.py:58-89`, 194, 226 | Journey API client via `urllib` | `httpx` | Yes (dev + indirect) | P2 |
| A10 | `src/api/portal_service.py:75-95` | Health-check polling loop | `httpx` | Yes | P2 |
| A11 | `src/workflow/journey.py:640-660`, `:2275-2288`, `:2347-2370` | Three "try twice" loops | Own helper | n/a | P5 |
| A12 | `src/api/scheme_search.py:511-534` | RRF fusion in Python | Qdrant `Prefetch` + `FusionQuery(Fusion.RRF)` (available in installed versions) | Yes | Not proposed |
| A13 | `src/documents/publication.py:33-81` | Cross-process file lock (`msvcrt`/`fcntl`) | `filelock` | Indirect (`huggingface_hub`) | P4 |
| A14 | `src/portal/repository.py:111-186` | Table/column checks on every connection | `PRAGMA user_version` | Yes | P6 |
| A15 | `src/portal/repository.py` (~900 lines) | Raw `sqlite3` SQL | `sqlalchemy` | No | Not proposed |
| A16 | `src/rules/facts.py:317-337` | Hand-written cycle detection | `graphlib` | Yes (stdlib) | P3 |
| A17 | `src/ui/app.py:50-514` (`COPY`), `discovery.py:40`, `supervisor.py:13`, `questions.py:85-95` | Translations in Python dicts | `gettext` / `babel` | `gettext` yes | Not proposed |
| A18 | `src/workflow/agent_config.py:17` | Token estimate = characters ÷ 3 | `tiktoken` | No | Not proposed |
| A19 | `src/run_services.py:40-78` | Child-process runner | `honcho`, docker compose | No | Not proposed |

### B. Built by hand on purpose

| ID | Location | What it does |
|---|---|---|
| B1 | `agent_runtime.py:342-494` | `run_react_loop`, the agent loop with typed statuses |
| B2 | `agent_runtime.py:35-52`; `src/mcp_servers/service_routing.py` | Allow-list, actor binding, tool routing |
| B3 | `agent_runtime.py:261-339`; `src/workflow/conversation_budget.py` | Budgets saved before each call |
| B4 | `agent_runtime.py:53-56, 497-503` | Personal-data masking |
| B5 | `agent_runtime.py:82-95, 562-587`; `journey.py:133` | User-facing trace, last 40 events |
| B6 | `agent_runtime.py` | Authorized-action recovery |
| B7 | `journey.py:2591-2608` | Per-conversation lock and budget `ContextVar` |
| B8 | `questions.py:387-399` | Strict date parsing |
| B9 | `src/rules/data_provider.py:97-118` | Reject duplicate JSON keys |
| B10 | `src/api/eligibility.py:89-98` | Rule operators `eq`/`gte`/`lte` |
| B11 | `src/documents/publication.py:149-160` | Atomic file replace |

### C. Already uses a library correctly

| Location | Library |
|---|---|
| `src/workflow/application_gate.py:20, 85`; `journey.py:2188, 2953` | LangGraph `interrupt()` and `Command(resume=...)` |
| `journey.py` state fields (~281-323) | LangGraph `Annotated` reducers |
| `conversation_budget.py`, `src/api/app.py:292` | LangGraph `StateGraph` and `AsyncSqliteSaver` |
| `agent_runtime.py` (`AgentSchema`) | Pydantic `extra="forbid"` |
| `src/mcp_servers/tools/*.py` | MCP SDK `@mcp.tool` |
| `src/api/scheme_search.py:14-15, 274` | `rank_bm25`, `fastembed`, `qdrant_client` |
| `portal_service.py:33-37`; `src/portal/app.py:46-55`; `repository.py:775-877` | `secrets`, `hmac.compare_digest`, `uuid4` |
| `src/api/eligibility.py:40`; `src/mcp_servers/rule_data.py:9` | `functools.lru_cache` |
| `src/config.py:7` | `python-dotenv` |

### D. Built-in LangGraph / LangChain hooks considered

The code today uses only `interrupt()` and `Annotated` reducers. No `retry_policy=`,
`cache_policy=`, `interrupt_before=`/`interrupt_after=` or callback handlers are
used. Graph nodes are registered at `journey.py:2442-2448`.

| Hook | Installed? | Verdict |
|---|---|---|
| `RetryPolicy` on `add_node` | Yes | Not for P5: it re-runs the whole node and loses retry events and budget counting |
| `CachePolicy` on `add_node` | Yes | No: results could go stale after data changes, and budget handling is unclear |
| `interrupt_before` / `interrupt_after` | Yes | No: `interrupt()` already does this and also passes data to the UI |
| `BaseCallbackHandler` | Yes | Optional, for server logs only (Part 3) |
| `pre_model_hook` / `post_model_hook` | Yes | No: only works with `create_react_agent`, which is not used |
| LangChain v1 middleware (`@wrap_tool_call`, call limits, `PIIMiddleware`, `HumanInTheLoopMiddleware`, `ModelFallbackMiddleware`) | No | No: needs LangChain's `create_agent`, which means replacing B1 |
| `langchain-core` chat model + `bind_tools` / `with_structured_output` | Partly (needs `langchain-openai`) | No: the plain `openai` SDK (P1) is simpler |
| `stream_mode` + `get_stream_writer()` | Yes | Only if the UI is changed to show live progress |
