# Agents, Middleware and Hooks in Scheme Saathi: Code Walkthrough

This guide shows **how Saathi's AI agents are built and guarded**: which LangChain and LangGraph building blocks are used, which rules are Saathi's own, and where each one lives in the code.

**Read it with the code open.** Every section links to the exact file and line. When you finish, you should be able to open any agent file, recognise each piece, and build a new agent the same way.

**You need:** basic Python, plus the idea of an async function (`async def` / `await`). LangChain and LangGraph terms are explained where they first appear.

---

## Contents

1. [The one idea: the model chooses, our code runs](#1-the-one-idea-the-model-chooses-our-code-runs)
2. [Standard building blocks vs Saathi's own rules](#2-standard-building-blocks-vs-saathis-own-rules)
3. [The files, and a reading order](#3-the-files-and-a-reading-order)
4. [One request traced through every guard](#4-one-request-traced-through-every-guard)
5. [Each building block, with its code and its test](#5-each-building-block-with-its-code-and-its-test)
6. [The five agents at a glance](#6-the-five-agents-at-a-glance)
7. [How agents are tested](#7-how-agents-are-tested)
8. [Adding a new agent, step by step](#8-adding-a-new-agent-step-by-step)
9. [Reference tables](#9-reference-tables)
10. [The three two-try retry loops, seen in the UI](#10-the-three-two-try-retry-loops-seen-in-the-ui)
11. [Known gaps](#11-known-gaps)
12. [Appendix: a complete runnable mini version](#12-appendix-a-complete-runnable-mini-version)

---

## 1. The one idea: the model chooses, our code runs

A **hook** is code that runs automatically before or after an operation, to check it, limit it, clean it or record it. In LangChain v1 these hooks are called **middleware**.

The model never holds a Python function or a connection. It only returns a **tool name and arguments**:

```
AI model ──returns──► tool call {"name": "inspect_document_metadata", "args": {"scheme_id": "pm-kisan"}}
                                  │
                                  ▼
            LangChain create_agent + Saathi middleware decide whether it runs
```

So every guard sits in **our** process, between "the model chose X" and "X runs". Three kinds of operation are guarded:

| Operation | Why it needs guarding |
|---|---|
| Calling the AI model (OpenRouter) | It costs money, and it must not receive personal data |
| Running a tool the model chose | The model can be wrong or tricked |
| Calling an MCP service | It can read or change application data |

**One more rule:** no agent decides eligibility. The rule engine (plain code) decides; agents only choose *which code-checked step comes next*.

---

## 2. Standard building blocks vs Saathi's own rules

Saathi uses the standard LangChain v1 / LangGraph piece wherever one exists. Custom code is kept only for rules that no library can express, and each of those is one small, named class or function.

| Job | Piece | Standard or Saathi? | Where |
|---|---|---|---|
| The chat model | `ChatOpenAI` pointed at OpenRouter | **LangChain** | [`llm_client.py:33`](../src/llm_client.py#L33) |
| Search vectors | `OpenAIEmbeddings` + `QdrantVectorStore` | **LangChain** | [`llm_client.py:59`](../src/llm_client.py#L59), [`api/scheme_search.py`](../src/api/scheme_search.py) |
| The agent loop (model → tool → model …) | `create_agent` | **LangChain** | [`agent_runtime.py:153`](../src/workflow/agent_runtime.py#L153) |
| An agent's actions | `@tool(args_schema=...)` functions | **LangChain** | each `*_agent.py` |
| The allow-list | The `tools=[...]` list itself | **LangChain** | each `run_agent(...)` call |
| Strict arguments | Pydantic `args_schema` with `extra="forbid"` | **LangChain + Pydantic** | `AgentSchema`, [`agent_runtime.py`](../src/workflow/agent_runtime.py) |
| Finishing actions | `return_direct=True` | **LangChain** | the handoff tools |
| Steps per run | `ModelCallLimitMiddleware` | **LangChain** | `run_agent` |
| Masking personal data | `PIIMiddleware` + `RedactionRule` | **LangChain** | [`agent_runtime.py:45`](../src/workflow/agent_runtime.py#L45) |
| One-off structured answers | `with_structured_output(...)` | **LangChain** | [`intake.py`](../src/workflow/intake.py) |
| The conversation graph, pauses, saving | `StateGraph`, `interrupt()`, `AsyncSqliteSaver` | **LangGraph** | [`journey.py`](../src/workflow/journey.py) |
| Per-conversation budget storage | `Store` (`AsyncSqliteStore`) | **LangGraph** | [`conversation_budget.py`](../src/workflow/conversation_budget.py) |
| Keeping the last 40 trace events | an `Annotated` reducer | **LangGraph** | `_merge_agent_trace`, [`journey.py:143`](../src/workflow/journey.py#L143) |
| **Shared conversation budget**, saved *before* each call | `DurableBudgetMiddleware` | **Saathi** (no library reserves durably before a call) | [`agent_middleware.py:171`](../src/workflow/agent_middleware.py#L171) |
| **Privacy-safe activity log** | `ScrubbedTraceMiddleware` | **Saathi** (must store no prompts or answers) | [`agent_middleware.py:90`](../src/workflow/agent_middleware.py#L90) |
| **Task checks inside each tool** | `if ... raise AgentActionError` | **Saathi** (business rules) | each `*_agent.py` |
| **Who may call which MCP tool** | `ServiceClientRouter` | **Saathi** (no library knows Saathi's roles) | [`service_routing.py:73`](../src/mcp_servers/service_routing.py#L73) |
| **Run the code path when the model can't** | `recover_authorized_action` | **Saathi** | [`agent_runtime.py:207`](../src/workflow/agent_runtime.py#L207) |
| **Two-try retries with visible notes** | hand-written loops | **Saathi** (see section 10 for why not `RetryPolicy`) | [`journey.py`](../src/workflow/journey.py) |

---

## 3. The files, and a reading order

| File | Its one job |
|---|---|
| [`src/llm_client.py`](../src/llm_client.py) | Builds the OpenRouter chat model (`openrouter_chat_model`) and embeddings model (`openrouter_embeddings`) |
| [`src/workflow/agent_config.py`](../src/workflow/agent_config.py) | All limits (`MAX_...`) and each agent's system prompt in en/hi/mr |
| [`src/workflow/agent_runtime.py`](../src/workflow/agent_runtime.py) | `run_agent` (builds and runs `create_agent`), `PII_RULES`, `mask_sensitive_text`, `recover_authorized_action`, `run_accounted_model_call`, `AgentSchema` |
| [`src/workflow/agent_middleware.py`](../src/workflow/agent_middleware.py) | Saathi's two middleware classes, the budget rule (`model_call_fits`, `reserve_model_call`), the trace event and `observation()` |
| [`src/workflow/conversation_budget.py`](../src/workflow/conversation_budget.py) | `ConversationBudget` (counters in the LangGraph `Store`), `CURRENT_BUDGET`, `reserve_counters` |
| [`src/workflow/supervisor_agent.py`](../src/workflow/supervisor_agent.py), [`intake_agent.py`](../src/workflow/intake_agent.py), [`eligibility_agent.py`](../src/workflow/eligibility_agent.py), [`document_agent.py`](../src/workflow/document_agent.py), [`application_agent.py`](../src/workflow/application_agent.py) | One agent each: its schemas, its `@tool` functions, one `run_agent(...)` call |
| [`src/workflow/journey.py`](../src/workflow/journey.py) | The LangGraph graph. Each agent is called from a node; `_serialize_journey` wraps every request |
| [`src/mcp_servers/service_routing.py`](../src/mcp_servers/service_routing.py) | `ServiceClientRouter`: role permissions in front of MCP tools |
| [`tests/fake_chat_model.py`](../tests/fake_chat_model.py) | `FakeChatModel`: an offline LangChain chat model for tests |

**Reading order for a newcomer:**
1. `agent_config.py` (short: numbers and prompts)
2. `document_agent.py`: the simplest complete agent
3. `agent_runtime.py`: `run_agent`
4. `agent_middleware.py`: the two middleware classes
5. `conversation_budget.py`, then `_serialize_journey` in `journey.py`

---

## 4. One request traced through every guard

Here is everything that happens when the **documents agent** checks Asha's documents. Each `◆` is a guard; the tag says whether it is **[LC]** LangChain, **[LG]** LangGraph or **[S]** Saathi.

```
HTTP request (src/api/app.py)
│
▼
journey.py · run_journey(...)
│  ◆ [S]  @_serialize_journey
│         - lock this conversation (one request at a time per server process)
│         - load its budget from the LangGraph Store       ◆ [LG] Store
│         - put it in CURRENT_BUDGET for everything below
▼
journey.py · document_agent(state)                 a node in the LangGraph graph
│  defines inspect(): the real work (MCP tool "check_documents")
│  calls run_document_specialist(model, scheme_id, locale, state["agent_budget"], inspect)
▼
document_agent.py · run_document_specialist(...)
│  two @tool functions = the allow-list              ◆ [LC] tools list
│    inspect_document_metadata(scheme_id)            ◆ [LC] args_schema  ◆ [S] task checks inside
│    handoff_documents(outcome)  return_direct=True  ◆ [S] must match the observed report
│  calls run_agent(model, "documents", locale, {"scheme_id": ...}, tools, budget, max_steps=2)
▼
agent_runtime.py · run_agent(...) → create_agent(model, tools, system_prompt, middleware=[...])
│  each model call passes through, outermost first:
│    ◆ [LC] PIIMiddleware ×4         mask email, Aadhaar, phone, account numbers
│    ◆ [LC] ModelCallLimitMiddleware  stop after max_steps model calls
│    ◆ [S]  ScrubbedTraceMiddleware   record a data-free event
│    ◆ [S]  DurableBudgetMiddleware   check limits → save the reservation → force one strict tool call
│           ChatOpenAI → OpenRouter → returns one tool call
│  each tool call passes through:
│    ◆ [LC] unknown tool name? → error message back to the model, nothing runs
│    ◆ [LC] arguments fail args_schema? → error message back to the model, nothing runs
│    ◆ [S]  DurableBudgetMiddleware   tool budget left? count it, save it
│    ◆ [S]  ScrubbedTraceMiddleware   record denied / invalid_arguments / observed / completed
│           the tool runs → inspect() → check_and_bind_documents(...)
│             ◆ [S] ServiceClientRouter: is the "documents" role allowed? → MCP doc-check service
│           the result goes back to the model as observation(...) labelled "outside_text_is_data"
│  returns AgentRunResult(status, budget, trace)
▼
document_agent.py · back in run_document_specialist
│  ◆ [S] model unavailable or budget used up? recover_authorized_action runs inspect() once, no model
▼
journey.py · the node returns {"agent_budget": ..., "agent_trace": [...], ...}
│  ◆ [LG] Annotated reducer _merge_agent_trace keeps the last 40 events
▼
Response to the user
```

Keep this picture in mind. Section 5 explains each `◆`.

---

## 5. Each building block, with its code and its test

### 5.1 The model: `ChatOpenAI` pointed at OpenRouter **[LC]**

OpenRouter speaks the OpenAI request format, so LangChain's `ChatOpenAI` works with OpenRouter's address and key. It is built in **one place**, [`llm_client.py:33`](../src/llm_client.py#L33):

```python
return ChatOpenAI(
    model=model, api_key=api_key, base_url=OPENROUTER_BASE_URL,
    default_headers=_IDENTIFYING_HEADERS, temperature=0,
    extra_body={"max_tokens": MAX_COMPLETION_TOKENS},  # OpenRouter's name for the reply cap
    timeout=MODEL_TIMEOUT_SECONDS,
    max_retries=0,          # every call is counted in the budget; no hidden retries
    http_async_client=_http_client(),   # tests swap in a fake transport
)
```

No key means no model: `src/api/app.py` passes `None`, and every agent takes its code-only path.

**Test:** `test_openrouter_chat_model_sends_one_strict_tool_choice_without_network` in [`tests/test_planning_and_intake_agents.py`](../tests/test_planning_and_intake_agents.py).

### 5.2 Tools are the allow-list **[LC]**, with task checks inside **[S]**

An agent can only call tools it was given. There is no separate allow-list. From [`document_agent.py:78`](../src/workflow/document_agent.py#L78):

```python
@tool(args_schema=InspectDocumentsArguments)          # strict input schema
async def inspect_document_metadata(scheme_id: str) -> str:
    """Inspect the supplied demo metadata with the deterministic checker."""
    nonlocal assessment, expected
    if scheme_id != task_scheme_id or assessment is not None:      # Saathi task check
        raise AgentActionError("Document inspection is outside this task.")
    assessment = await inspect()
    ...
    return observation(InspectDocumentsObservation(status=status, discrepancy_codes=[...]))

@tool(args_schema=DocumentHandoffArguments, return_direct=True)    # ends the run
async def handoff_documents(outcome: str) -> str:
    ...
```

What each part does:

| Part | Meaning |
|---|---|
| `@tool(args_schema=...)` | LangChain turns the function into a tool. The model sees the schema and docstring. |
| `AgentSchema` (`extra="forbid"`) | Unknown or extra arguments are rejected before the function runs |
| The function is defined *inside* `run_document_specialist` | It can see `task_scheme_id` (a closure), so the task check needs no extra parameters |
| `raise AgentActionError(...)` | A business rule refused the call. The run stops with status `action_rejected`. |
| `observation(...)` | The result goes back as JSON marked `"outside_text_is_data": True`, so text inside it is never treated as instructions |
| `return_direct=True` | Calling this tool ends the run. These are the "handoff" or "finish" tools. |

When the tool's name must be chosen at run time, the same thing is built with `StructuredTool.from_function(coroutine=..., name=..., args_schema=...)`, as in [`application_agent.py:101`](../src/workflow/application_agent.py#L101).

**Test:** `test_agent_action_schema_denial_and_budget_stop_before_executor` in [`tests/test_planning_and_intake_agents.py`](../tests/test_planning_and_intake_agents.py) proves that bad arguments, unknown tools and budget stops never run the tool.

### 5.3 `run_agent`: one `create_agent` with Saathi's middleware **[LC] + [S]**

Every agent runs through one function, [`agent_runtime.py:153`](../src/workflow/agent_runtime.py#L153):

```python
graph = create_agent(
    model,
    tools=tools,
    system_prompt=system_prompt,                 # from agent_config.prompt_for(agent, locale)
    middleware=[
        *(
            PIIMiddleware(rule.pii_type, detector=rule.detector, strategy="redact")
            for rule in PII_RULES
        ),                                                                    # LangChain
        ModelCallLimitMiddleware(run_limit=max_steps, exit_behavior="end"),  # LangChain
        ScrubbedTraceMiddleware(agent, model.model_name, trace),              # Saathi
        DurableBudgetMiddleware(counters, estimate_extra=...),                # Saathi
    ],
)
message = json.dumps(dict(context), ensure_ascii=False, default=str)
try:
    await graph.ainvoke({"messages": [HumanMessage(content=message)]})
except RunStopped as stop:
    return AgentRunResult(stop.status, counters, trace)
if any(event["status"] == "completed" for event in trace):
    return AgentRunResult("completed", counters, trace)
trace.append(trace_event(agent, None, "step_limit", model.model_name, max_steps))
return AgentRunResult("step_limit", counters, trace)
```

**Order matters:** middleware earlier in the list wraps the later ones. Masking runs first, so nothing after it sees raw identifiers. The trace wraps the budget, so a budget stop is always recorded.

**How a run ends:**

| Status | When |
|---|---|
| `completed` | A `return_direct` (handoff) tool ran |
| `step_limit` | The model used all `max_steps` calls without finishing |
| `budget_exhausted` | A conversation limit was reached before a model or tool call |
| `model_unavailable` | The model request failed (network, HTTP error, timeout) |
| `action_rejected` | A tool's own check (`AgentActionError`) or its output schema refused the call |

### 5.4 Masking personal data: `PIIMiddleware` + `RedactionRule` **[LC]**

The rules are defined once, [`agent_runtime.py:45`](../src/workflow/agent_runtime.py#L45):

```python
PII_RULES = (
    RedactionRule("email"),                                                   # built-in detector
    RedactionRule("aadhaar", detector=r"(?<!\d)(?:\d[ -]?){11}\d(?!\d)"),
    RedactionRule("phone",   detector=r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)"),
    RedactionRule("account", detector=r"(?<!\d)(?:\d[ -]?){8,17}\d(?!\d)"),
)
```

- **Agents:** `PIIMiddleware` applies each rule to the model input.
- **Everything else** (trace text, intake replies, search queries): `mask_sensitive_text(text)` applies the same rules.

Matches become `[REDACTED_EMAIL]`, `[REDACTED_AADHAAR]`, `[REDACTED_PHONE]` and `[REDACTED_ACCOUNT]`. Aadhaar comes before phone and account so that a 12-digit Aadhaar number isn't partly matched as a phone number.

**Tests:** `test_react_intake_observes_allowed_tool_then_confirms_each_fact` checks that the model sees `[REDACTED_EMAIL]` and `[REDACTED_AADHAAR]`. `test_search_query_rewrite_uses_the_durable_model_budget` checks search queries.

### 5.5 Steps per run: `ModelCallLimitMiddleware` **[LC]**

`run_limit=max_steps` caps model calls in **this run**. `exit_behavior="end"` ends the run quietly instead of raising, and `run_agent` then reports `step_limit`. Each agent passes its own `max_steps` (2 or 3, see section 6).

The **conversation-wide** limits are a different thing. They are Saathi's budget (5.7).

### 5.6 The privacy-safe activity log: `ScrubbedTraceMiddleware` **[S]**

[`agent_middleware.py:90`](../src/workflow/agent_middleware.py#L90). After every tool call it records one event:

| Event status | Cause |
|---|---|
| `denied` | The model named a tool it wasn't given (`request.tool is None`) |
| `invalid_arguments` | LangChain returned an error `ToolMessage` because the arguments failed the schema |
| `observed` | A normal tool ran; its observation went back to the model |
| `completed` | A `return_direct` tool ran; the run ends |
| `action_rejected` | The tool raised `AgentActionError` or a `ValidationError`. The run stops. |
| `budget_exhausted`, `model_unavailable` | Recorded when the budget middleware stops a model call |

Each event has a fixed shape (`trace_event`): agent, action, status, model, prompt version, step, token counts, duration and a **fixed summary sentence**. It never holds prompts, arguments or applicant data, so it can be stored and shown to the person.

**Why it's Saathi's own:** LangChain's tracing (for example LangSmith) records full prompts and arguments, and Saathi must not store those.

### 5.7 The shared budget: `DurableBudgetMiddleware` + the LangGraph `Store` **[S] + [LG]**

**The rule:** in one conversation, all agents together may use at most 8 model calls, 12 agent steps, 24 tool calls and 12,000 tokens. Each call is **saved before it is sent**, so a crash or retry can never produce an uncounted paid call.

**Where the counters live:** the LangGraph `Store` under namespace `("budget",)`, keyed by conversation ID. This is separate from the conversation's checkpoints, so a reservation survives even when the node that made it crashes. See [`conversation_budget.py`](../src/workflow/conversation_budget.py):

```python
# shortened: docstrings and type hints left out
BUDGET_NAMESPACE = ("budget",)

class ConversationBudget:
    async def load(self, conversation_id):
        item = await self.store.aget(BUDGET_NAMESPACE, conversation_id)
        self.values = dict(item.value) if item else {}

    async def reserve(self, counters):
        ...
        await self.store.aput(BUDGET_NAMESPACE, self.conversation_id, dict(self.values))
```

In production the store is `AsyncSqliteStore`, in the same SQLite file as the checkpoints but on its own connection (`src/api/app.py`). "Forget my data" deletes both the checkpoint and the store item.

**How code reaches it without passing it everywhere:** `_serialize_journey` ([`journey.py`](../src/workflow/journey.py)) wraps every request. It locks the conversation, loads the budget and puts it in the context variable `CURRENT_BUDGET`. Any function below can then call `reserve_counters(counters)`.

**The rule itself is one pair of functions** ([`agent_middleware.py:150`](../src/workflow/agent_middleware.py#L150)), used by both agents and one-off calls:

```python
def model_call_fits(counters: dict[str, int], estimated_input: int) -> bool:
    return not (
        counters["model_calls"] >= MAX_CONVERSATION_MODEL_CALLS
        or counters["agent_steps"] >= MAX_CONVERSATION_AGENT_STEPS
        or counters["input_tokens"] + counters["output_tokens"]
        + estimated_input + MAX_COMPLETION_TOKENS > MAX_CONVERSATION_TOKENS
    )

async def reserve_model_call(counters: dict[str, int], estimated_input: int) -> None:
    counters["model_calls"] += 1
    counters["agent_steps"] += 1
    counters["input_tokens"] += estimated_input
    counters["output_tokens"] += MAX_COMPLETION_TOKENS     # reserve the largest possible reply
    await reserve_counters(counters)                        # saved BEFORE the call
```

**What the middleware adds around each model call** ([`agent_middleware.py:171`](../src/workflow/agent_middleware.py#L171)):
1. Estimate the input tokens (messages + system prompt + tool schemas).
2. If `model_call_fits` is false, raise `RunStopped("budget_exhausted")`. The model is never called.
3. `reserve_model_call`, which saves the reservation.
4. Force **one strict tool call**: `request.override(tool_choice="required", model_settings={"parallel_tool_calls": False, "strict": True})`.
5. Call the model. Any `OpenAIError` becomes `RunStopped("model_unavailable")`.
6. Replace the estimate with real usage, release the unused part of the reply reservation, and save again.

**Around each tool call:** an unknown tool or bad arguments pass straight through (LangChain returns an error, nothing runs, nothing is counted). Otherwise it checks the 24-tool limit, counts the call and saves it before the tool runs.

**Why it's Saathi's own:** LangChain's limit middleware counts in memory for one run. Saathi needs a limit shared by all agents for the whole conversation, saved before the call, that survives restarts.

**Tests:** `test_same_id_restart_preserves_model_budget` and `test_model_budget_survives_correction_and_same_id_process_restart` in [`tests/test_planning_and_intake_agents.py`](../tests/test_planning_and_intake_agents.py).

### 5.8 When the model chooses badly

| The model… | What happens | Run status |
|---|---|---|
| names a tool it wasn't given | LangChain answers "*X* is not a valid tool". Nothing runs and nothing is counted. The model may try again within its steps. | continues, maybe `step_limit` |
| sends arguments that fail the schema | LangChain answers with the validation error. Nothing runs and nothing is counted. The model may try again. | continues, maybe `step_limit` |
| calls a real tool, but the task check refuses it | `AgentActionError`. The run stops. | `action_rejected` |
| keeps going without finishing | `ModelCallLimitMiddleware` ends the run | `step_limit` |

In every case the tool's body never runs, and the trace says why.

### 5.9 When there is no model: the code path **[S]**

Every agent wraps a step that plain code can do on its own (run the rule check, inspect documents). If the model **could not be asked** (`budget_exhausted` or `model_unavailable`), `recover_authorized_action` ([`agent_runtime.py:207`](../src/workflow/agent_runtime.py#L207)) runs that code step **once**, counted against the tool budget:

```python
if (
    run.status not in {"budget_exhausted", "model_unavailable"}
    or run.budget.get("tool_calls", 0) >= MAX_CONVERSATION_TOOL_CALLS
):
    return None
run.budget["tool_calls"] = run.budget.get("tool_calls", 0) + 1
await reserve_counters(run.budget)
return await execute()
```

With **no API key at all**, agents skip the model entirely (`if provider is None: ...`) and report `deterministic`.

**Test:** `test_model_recovery_never_bypasses_the_remaining_tool_budget` in [`tests/test_document_and_application_agents.py`](../tests/test_document_and_application_agents.py).

### 5.10 One-off model calls: `with_structured_output` + `run_accounted_model_call` **[LC] + [S]**

Intake makes two single calls that aren't agents: reading a free-text answer and rewriting a search query. They use LangChain structured output ([`intake.py`](../src/workflow/intake.py)):

```python
reader = openrouter_chat_model(api_key, model).with_structured_output(
    schema, method="json_mode",
)
return await reader.ainvoke([
    {"role": "system", "content": system},
    {"role": "user", "content": user},
])
```

These calls don't run inside `create_agent`, so agent middleware can't wrap them. `run_accounted_model_call` ([`agent_runtime.py:84`](../src/workflow/agent_runtime.py#L84)) applies the **same** `model_call_fits` / `reserve_model_call` rule around them. It reserves before the call, and on failure it records `model_unavailable` and lets the fixed question flow continue.

**Tests:** `test_legacy_chat_call_is_rejected_before_provider_at_budget_limit` and `test_query_rewriter_timeout_falls_back_with_counted_trace`.

### 5.11 The guard in front of MCP tools: `ServiceClientRouter` **[S]**

Every MCP call goes through [`service_routing.py:73`](../src/mcp_servers/service_routing.py#L73). The caller's role (`documents`, `application`, `human_approval`…) is bound in code with `for_actor(...)`, never taken from tool arguments. Each call then checks:
- that the role may use this tool (`ACTOR_TOOLS`);
- for the mock portal, that the role may use this action (`PORTAL_ACTIONS`) and the call is bound to this journey;
- that no argument tries to set the caller's identity.

Only then is the call sent to the one service that owns the tool. The full walkthrough is in [MCP_PERMISSIONS_WALKTHROUGH.md](MCP_PERMISSIONS_WALKTHROUGH.md).

### 5.12 Keeping the trace in the conversation state **[LG]**

Each node returns new `agent_trace` events. The state field is declared with a reducer, so LangGraph merges instead of overwriting ([`journey.py:143`](../src/workflow/journey.py#L143)):

```python
# shortened: type hints left out
def _merge_agent_trace(current, added):
    return (current + added)[-MAX_TRACE_EVENTS:]     # keep the last 40
```

---

## 6. The five agents at a glance

Each agent file has the same shape: schemas → `@tool` functions (closures with task checks) → `if provider is None:` code path → `run_agent(...)` → recovery.

| Agent | File | Tools (the allow-list) | `max_steps` | What plain code still decides |
|---|---|---|---|---|
| Supervisor | [`supervisor_agent.py`](../src/workflow/supervisor_agent.py) | `propose_plan`, `finish_plan`* | 2 | The plan must use known step IDs in a valid order; otherwise the fixed plan is kept |
| Intake | [`intake_agent.py`](../src/workflow/intake_agent.py) | `read_required_facts`, `propose_profile_facts`, `finish_intake`* | default 3 | Proposed facts are only proposals; the person confirms each one |
| Eligibility | [`eligibility_agent.py`](../src/workflow/eligibility_agent.py) | `check_candidate`, `handoff_verdict`*, `request_clarification`*, `refer_for_help`* | 3 | The verdict always comes from the rule engine |
| Documents | [`document_agent.py`](../src/workflow/document_agent.py) | `inspect_document_metadata`, `handoff_documents`* | 2 | The handoff must match the checker's report |
| Application | [`application_agent.py`](../src/workflow/application_agent.py) | one portal action named for the operation (`prepare_draft`, `edit_draft`, `submit_draft`, `read_application_status`), `handoff_application`* | 2 | The backend authorizes the action; submitting needs the person's exact approval |

\* `return_direct=True`: calling it ends the run.

---

## 7. How agents are tested

### The fake model

[`tests/fake_chat_model.py`](../tests/fake_chat_model.py) defines `FakeChatModel`, a real LangChain `BaseChatModel` subclass. Tests subclass it and write `choose()`:

```python
# example
class Model(FakeChatModel):
    async def choose(self, agent, locale, messages, tools):
        return ModelDecision(action="inspect_document_metadata", arguments={"scheme_id": "pm-kisan"})
```

`choose` receives the agent name and language (worked out from the system prompt), the conversation so far and the bound tools. A test can therefore script the model, check what it was shown, or raise to simulate an outage. No test reaches the network.

### The fake OpenRouter

For code that builds a real `ChatOpenAI` (intake's one-off calls), the `fake_openrouter` fixture in [`tests/conftest.py`](../tests/conftest.py) replaces the HTTP transport. Tests set `fake_openrouter.answer(...)`, or an HTTP 503 reply, and read back exactly what was sent.

### The key test pattern: "blocked means never ran"

```python
# example, condensed from test_agent_action_schema_denial_and_budget_stop_before_executor
calls = []

@tool(args_schema=Args)
async def propose_plan(value: str) -> str:
    calls.append("executed")
    ...

# The model sends bad arguments, then an unknown tool:
invalid = await run(provider)
assert [e["status"] for e in invalid.trace] == ["invalid_arguments", "step_limit"]
assert not calls                       # the tool body never ran
```

Every guard is tested the same way: make the model do the wrong thing, then assert that the action **never ran** and that the trace says why.

---

## 8. Adding a new agent, step by step

Say you are adding a **feedback** agent that saves a rating.

1. **Prompt and limits:** add `"feedback": {"en": ..., "hi": ..., "mr": ...}` to `AGENT_PROMPTS` in [`agent_config.py`](../src/workflow/agent_config.py).
2. **Schemas:** create `feedback_agent.py` with `AgentSchema` subclasses for each tool's arguments and observations.
3. **Tools:** inside `run_feedback_specialist(...)`, write `@tool(args_schema=...)` functions. Put task checks at the top of each one (`raise AgentActionError(...)`) and return `observation(Model(...))`. Mark the finishing tool `return_direct=True`.
4. **No-model path:** `if provider is None:` do the step in plain code.
5. **Run it:** `run = await run_agent(provider, "feedback", locale, {...minimal context...}, [tools], budget, max_steps=2)`.
6. **Recovery:** if the model couldn't be asked, call `recover_authorized_action(run, do_it_in_code)`.
7. **Return the standard four values:** `(result, run.budget, run.trace, "model_assisted" | "deterministic_fallback")`.
8. **Call it from a node** in `journey.py` and return `agent_budget` and `agent_trace`, so the budget and trace are saved.
9. **If it calls an MCP tool:** add a role to `ACTOR_TOOLS` (and `PORTAL_ACTIONS` for portal actions), and call through `specialist_client("feedback")`.
10. **Test** with a `FakeChatModel` subclass: the happy path, an unknown tool, bad arguments, a refused task, an exhausted budget and a model failure.

You don't write a loop, an allow-list, a masking step or a budget check. `run_agent` brings them all.

---

## 9. Reference tables

### Limits ([`agent_config.py`](../src/workflow/agent_config.py))

| Constant | Value | Scope |
|---|---|---|
| `MAX_CONVERSATION_MODEL_CALLS` | 8 | All agents and one-off calls, whole conversation |
| `MAX_CONVERSATION_AGENT_STEPS` | 12 | Same |
| `MAX_CONVERSATION_TOOL_CALLS` | 24 | Same (agent tools and code-path recoveries) |
| `MAX_CONVERSATION_TOKENS` | 12,000 | Same (input + output) |
| `MAX_COMPLETION_TOKENS` | 512 | Per model reply; reserved in full before each call |
| `MAX_AGENT_STEPS_PER_TURN` | 3 | Default `max_steps` for one run |
| `MODEL_TIMEOUT_SECONDS` | 20 | Per model request |
| `MAX_TRACE_EVENTS` | 40 | Trace events kept in the conversation state |
| `MAX_DISCOVERY_CALLS` ([`discovery.py`](../src/workflow/discovery.py)) | 4 | Scheme searches per conversation |

### The fourth value each agent returns

| Value | Meaning |
|---|---|
| `model_assisted` | The agent run completed with the model |
| `deterministic` | No model configured; plain code did the step |
| `deterministic_fallback` | The model couldn't finish; the code path decided (or nothing was done) |

### Where to find each guard

| Look for… | It is… |
|---|---|
| `@tool(`, `StructuredTool.from_function(` | an agent action (allow-list entry) |
| `raise AgentActionError(` | a Saathi task check |
| `return_direct=True` | a finishing (handoff) action |
| `middleware=[` | the guard stack (`run_agent` only) |
| `reserve_counters(`, `reserve_model_call(` | a budget reservation saved before a call |
| `mask_sensitive_text(` | masking outside agents |
| `specialist_client("...")`, `for_actor(` | an MCP call bound to a role |
| `recover_authorized_action(` | the code path when the model couldn't be asked |

---

## 10. The three two-try retry loops, seen in the UI

Three places call an MCP tool and, if it fails, try **exactly once more**. They are hand-written loops, not LangGraph `RetryPolicy`, on purpose:

- `RetryPolicy` throws away everything a failed attempt wrote to the state, so the "Retrying once" note would never be saved.
- After the last attempt, `RetryPolicy` lets the error escape the graph, so the user would get an API error instead of the calm "No decision was invented" reply.

Budget counting is **not** a reason. Each search reservation is saved in the LangGraph `Store` before the call, so a re-run would still count it.

```
 User message
     │
     ▼
 scheme_search_tool   Loop 1: "Which schemes match what I typed?"
     │
     ▼
 interview answers    Loop 2: discover_candidates, "With these confirmed facts, are there more schemes?"
     │
     ▼
 eligibility_agent    Loop 3: checked_verdict, "Does this household pass this scheme's rules?"
```

| | Loop 1: Search | Loop 2: Discovery | Loop 3: Rule check |
|---|---|---|---|
| Code | `scheme_search_tool` in `journey.py` | `discover_candidates` in `journey.py` | `checked_verdict` inside `eligibility_agent` |
| Trigger | The user's request | Newly confirmed facts (multi-scheme mode, profile signature changed) | Ready to check one scheme |
| MCP tool | `search_schemes` | `search_schemes` | `evaluate_eligibility` |
| Budget | 4 searches per conversation, shared with loop 2; each try counts | Same shared 4 | None (the rule engine is free code) |
| If both tries fail | Calm message, a `tool_failed` history note, and a `tool_error` report to the supervisor | Existing schemes kept; the `tool_error` notice is shown | "No verdict" for that scheme only |
| Why not `RetryPolicy` | It would lose the note and the calm failure | It's a helper inside other nodes, not a node | Re-running the node would also re-run the agent's AI calls |

How it appears on screen:
- History notes are grey captions: `render_history` in `src/ui/app.py` turns `tool_retry` / `tool_failed` into "Retry" / "Tool failed" (translated for hi/mr).
- Discovery notices are yellow warnings: `render_discovery_notices`, with text from `DISCOVERY_MESSAGES` in `src/workflow/discovery.py`.

### Loop 1: Scheme search

Sunita, a widow in Pune, types: *"I lost my husband last year, is there any pension for me?"*

**The first try fails and the retry works.** Searches used: 2 of 4.
```
Retry: Scheme search failed. Retrying once.                     (grey)
Schemes found:
 • Sanjay Gandhi Niradhar Anudan Yojana   [source]
 • Indira Gandhi National Widow Pension   [source]
 [ Start interview ]
```

**Both tries fail.** Searches used: 2 of 4, so she can try again later in the same conversation.
```
Retry: Scheme search failed. Retrying once.                     (grey)
Tool failed: Scheme search failed twice. No search results are available.  (grey)
⚠ A check or search could not finish. No decision was invented.
  Retry later or ask a CSC operator for help.
```

### Loop 2: Discovery, the re-search after answers

Ramesh is checking widow-pension schemes for his mother in multi-scheme mode. He confirms: *"Yes, the family owns 1 acre of farmland."*

**The re-search finds more.** PM-KISAN joins the list, the plan version goes up, and its questions are added to the interview.
```
Confirmed facts added retrieved candidates. Only reviewed rules decide eligibility.  (grey)
pm-kisan                                                        (grey)
Next question: Is the land registered in the family's name?
```

**The first try fails and the retry works.**
```
Discovery failed; retrying once within the same conversation budget.  (grey)
Confirmed facts added retrieved candidates. ...                 (grey)
```

**Both tries fail.** The existing schemes stay and the interview goes on; only the extra scheme is missed.
```
⚠ A check or search could not finish. No decision was invented. ...
Next question: What is the mother's age?
```

**The allowance is already used up.** No search is attempted at all.
```
⚠ The conversation's search limit is reached. Some schemes may remain
  unchecked; ask a CSC operator for help.
```

### Loop 3: Eligibility rule check

Ramesh has answered every PM-KISAN question.

**The first try fails and the retry works.** Nothing counts against any allowance.
```
Retry: Eligibility tool retry.                                  (grey)
PM-KISAN: This scheme meets the current mock rules. ✔
 [ Document checklist ]
```

**Both tries fail.** The other schemes' results still show; Saathi never guesses a verdict.
```
Retry: Eligibility tool retry.                                  (grey)
Tool failed: Eligibility tool failed; no verdict.               (grey)
⚠ Some candidates could not be checked. No eligibility decision was
  made for them; ask a CSC operator for help.
Widow pension: This scheme meets the current mock rules. ✔
PM-KISAN: no verdict
```

**The rule behind all three:** one failure shows a grey "Retry" note and then normal results. Two failures show a warning that says what wasn't done, with a CSC referral. There's never an invented answer, a crash, or a lost conversation.

---

## 11. Known gaps

| Gap | Detail |
|---|---|
| Trace events aren't sent to a monitoring tool | Events stay in the conversation state (last 40). The project plan recommends LangSmith, Langfuse or Grafana; that isn't built yet. Any exporter must keep the "no prompts, no applicant data" rule. |
| Denied tool names are logged as typed | On a `denied` event, `action` holds the model's raw tool name. Logging a fixed word such as `unknown_tool` would be safer. |
| Masking is pattern-based | `PII_RULES` catch formats (emails, phone, Aadhaar and account numbers), not names or addresses. |
| Code-only paths have no agent budget | The conversation budget limits what agents and one-off model calls use. Fixed code paths (no API key, registered-scheme eligibility, status reads) don't use it. |
| MCP connections are not `langchain-mcp-adapters` | The adapters (0.3.2, the latest) require `mcp<2`; Saathi uses MCP 2. Saathi's agents don't take raw MCP tools anyway; they call MCP through guarded `@tool` functions. When the adapters support MCP 2, startup can move to `MultiServerMCPClient` and the role check to a tool interceptor. |
| The eligibility rule-check retry isn't counted | Loop 3 (section 10) retries the rule engine once without counting it. It is free code, so this costs nothing, but it isn't visible in the tool budget. |

---

## 12. Appendix: a complete runnable mini version

This one file shows the whole pattern in miniature: strict schemas, tools as the allow-list, a task check inside a tool, `PIIMiddleware`, `ModelCallLimitMiddleware`, a Saathi-style budget middleware, and a scripted fake model. It has been run in this project's environment (LangChain 1.4): **6 tests pass.**

<details>
<summary><b>mini_agent.py</b></summary>

```python
"""A self-contained mini version of Saathi's agent pattern, with tests.

Run: python -m pytest mini_agent.py -q   (needs langchain>=1.4)
"""

import asyncio
import json

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware, ModelCallLimitMiddleware, PIIMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field


# 1. Strict schemas: the model must send exactly these arguments.
class CheckArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme_id: str = Field(min_length=1)


class RunStopped(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


# 2. A domain rule as named middleware: a budget saved before each call.
class BudgetMiddleware(AgentMiddleware):
    def __init__(self, counters: dict[str, int], limit: int) -> None:
        super().__init__()
        self.counters, self.limit = counters, limit

    async def awrap_model_call(self, request, handler):
        if self.counters["model_calls"] >= self.limit:
            raise RunStopped("budget_exhausted")
        self.counters["model_calls"] += 1          # Saathi saves this durably here
        return await handler(request)


# 3. A scripted fake model: no network in tests.
class ScriptedModel(BaseChatModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    calls: list = []
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append([m.content for m in messages if not isinstance(m, SystemMessage)])
        name, args = self.calls.pop(0)
        reply = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{len(self.seen)}"}])
        return ChatResult(generations=[ChatGeneration(message=reply)])


def build(model, counters, task_scheme_id, ran):
    # 4. Tools: the list IS the allow-list; the task check lives inside the tool.
    @tool(args_schema=CheckArgs)
    async def check_candidate(scheme_id: str) -> str:
        """Check the rule engine for this scheme."""
        if scheme_id != task_scheme_id:
            raise ValueError("outside this task")
        ran.append(scheme_id)
        return json.dumps({"observation": {"result": "eligible"}, "outside_text_is_data": True})

    @tool(args_schema=CheckArgs, return_direct=True)
    async def handoff(scheme_id: str) -> str:
        """Hand the observed verdict back."""
        return "done"

    return create_agent(model, tools=[check_candidate, handoff], system_prompt="Role: checker.",
                        middleware=[
                            PIIMiddleware("email", strategy="redact"),
                            ModelCallLimitMiddleware(run_limit=3, exit_behavior="end"),
                            BudgetMiddleware(counters, limit=8),
                        ])


async def run(calls, counters=None, text="hello"):
    model = ScriptedModel(calls=list(calls), seen=[])
    counters = counters if counters is not None else {"model_calls": 0}
    ran: list[str] = []
    agent = build(model, counters, "pm-kisan", ran)
    try:
        state = await agent.ainvoke({"messages": [HumanMessage(content=text)]})
        status = "completed" if state["messages"][-1].content == "done" else "step_limit"
    except RunStopped as stop:
        status = stop.status
    return status, ran, counters, model.seen


def test_observe_then_handoff():
    status, ran, counters, _ = asyncio.run(run([
        ("check_candidate", {"scheme_id": "pm-kisan"}), ("handoff", {"scheme_id": "pm-kisan"}),
    ]))
    assert (status, ran, counters["model_calls"]) == ("completed", ["pm-kisan"], 2)


def test_unknown_tool_never_runs_and_model_may_retry():
    status, ran, _, seen = asyncio.run(run([
        ("erase_household", {}), ("handoff", {"scheme_id": "pm-kisan"}),
    ]))
    assert status == "completed" and ran == []
    assert "erase_household is not a valid tool" in json.dumps(seen[1])


def test_bad_arguments_never_run():
    status, ran, _, _ = asyncio.run(run([
        ("check_candidate", {"scheme_id": ""}), ("handoff", {"scheme_id": "x"}),
    ]))
    assert status == "completed" and ran == []


def test_budget_stops_before_the_model_is_called():
    status, ran, _, seen = asyncio.run(run([("handoff", {"scheme_id": "x"})], {"model_calls": 8}))
    assert (status, ran, seen) == ("budget_exhausted", [], [])


def test_email_is_redacted_before_the_model_sees_it():
    _, _, _, seen = asyncio.run(run([("handoff", {"scheme_id": "x"})], text="mail a@b.com"))
    assert "a@b.com" not in json.dumps(seen) and "[REDACTED_EMAIL]" in json.dumps(seen)


def test_step_limit_ends_the_run():
    status, ran, _, _ = asyncio.run(run([("check_candidate", {"scheme_id": "pm-kisan"})] * 3))
    assert status == "step_limit"
```

</details>
