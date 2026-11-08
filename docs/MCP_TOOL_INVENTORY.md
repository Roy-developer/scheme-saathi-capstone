# MCP Services and Tools: Inventory and Build Guide

This document has two jobs:

1. **Inventory.** List every tool Scheme Saathi has, which server it lives on, and how risky it is.
2. **Guide.** Explain, from zero, how these servers and tools work, so someone new can understand them and build the same thing themselves.

If you already know the project and just want the list, jump to the [Quick reference](#quick-reference) at the end.

---

## Contents

0. [Start here](#0-start-here)
1. [The big picture](#1-the-big-picture)
2. [What happens when the app starts](#2-what-happens-when-the-app-starts)
3. [The tool catalogue](#3-the-tool-catalogue)
4. [What a tool call looks like](#4-what-a-tool-call-looks-like)
5. [Inputs and errors](#5-inputs-and-errors)
6. [Safety rules](#6-safety-rules)
7. [The eligibility agent's own actions](#7-the-eligibility-agents-own-actions)
8. [The mock portal](#8-the-mock-portal)
9. [Document checklists: status and safe updates](#9-document-checklists-status-and-safe-updates)
10. [Build it yourself, step by step](#10-build-it-yourself-step-by-step)
11. [How it's tested](#11-how-its-tested)
12. [Quick reference](#quick-reference)

---

## 0. Start here

### Who this is for

Anyone who knows basic Python (functions, classes, dictionaries) but has never used MCP. By the end you'll know what each Saathi tool does, how the servers start and talk to each other, and how to build your own server with a permission guard in front of it.

### The two-minute version

- A **tool** is a Python function that the AI (or our backend) can ask to run, for example "check this user's documents."
- Tools are grouped into **4 small servers**, each with one area of work: rules, scheme knowledge, document checks, and the application portal.
- When the app starts, it launches those servers and checks that each one has **exactly** the tools we expect. If anything is off, the app refuses to start.
- Every tool call goes through a **guard** that checks whether the caller is allowed to use that tool. See [`MCP_PERMISSIONS_WALKTHROUGH.md`](MCP_PERMISSIONS_WALKTHROUGH.md).
- A fifth process is a small **pretend government portal** (a local website with its own database) where draft applications are stored.

### Glossary

Read these once. Every term is used later.

| Term | What it means here |
|---|---|
| **MCP** (Model Context Protocol) | A standard way for a program to say "here are my tools" and for another program to say "please run this tool with these inputs." We use the official `mcp` Python library. |
| **MCP server** | A program that offers tools. In Saathi, each server is a short Python file. |
| **MCP client** | The object that connects to a server and calls its tools. Our API holds one client per server. |
| **Tool** | One Python function published by a server, for example `check_documents`. |
| **Process** | A separately running program. Each MCP server runs in its own process, so a crash in one doesn't take down the others. |
| **stdio** | "Standard input/output." The client starts the server as a child process and they talk by writing text to each other's input and output, with no network involved. |
| **HTTP** | The normal web protocol. The mock portal is a small local website, so it's reached over HTTP. |
| **Lifespan** | Code that FastAPI runs once when the API starts (and again when it stops). Saathi starts its servers there. |
| **Fail closed** | When something is wrong, refuse and stop rather than carrying on in an unsafe state. |
| **Read-only** | The tool only looks at data and never changes anything. |
| **Write** | The tool creates or changes data. |
| **Destructive** | A write that's hard or impossible to undo, like submitting a form. |
| **Idempotent** | Doing it twice has the same effect as doing it once. Submitting the same approved draft twice won't create two submissions. |
| **Pydantic model** | A Python class that describes the shape of some data (field names and types) and rejects data that doesn't fit. |
| **Schema** | A description of what inputs a tool accepts, generated automatically from the function's type hints. |
| **Annotation** | A label on a tool saying whether it's read-only, destructive, and so on. |
| **Actor / role** | Which part of the system is calling, for example `documents` or `human_approval`. Decides what it may do. |
| **Journey** (`journey_id`) | One user's case, from first question to submitted form. |
| **Draft** | An application form that hasn't been submitted yet. |
| **Revision** | A version number of a draft. It goes up every time the draft changes. |
| **Fingerprint** | A short code computed from content. If the content changes even slightly, the fingerprint changes, so it proves "this is exactly the same content." |
| **Checkpoint** | The workflow's saved state for a journey, so it can pause (for example, waiting for a human) and resume later. |
| **Synthetic** | Made-up test data, not real people or real government records. |

---

## 1. The big picture

```
                          ┌──────────────────────────────────────────┐
  User ─► UI ─► FastAPI ─►│  Guard (ServiceClientRouter)             │
                API       │  checks role, then routes by tool name   │
                          └───┬──────────┬───────────┬──────────┬────┘
                              │ stdio    │ stdio     │ stdio    │ stdio
                              ▼          ▼           ▼          ▼
                        rule-engine  schemes-kb   doc-check  mock-portal
                        (MCP server) (MCP server) (MCP server)(MCP server)
                                                                │ HTTP
                                                                ▼
                                                        Portal website
                                                        (FastAPI + SQLite)
```

Facts about this layout:

- When the API starts (in its lifespan), it starts **one private HTTP mock-portal process** and **four separate stdio MCP processes**.
- **Each service has its own entry point** (its own small Python file). There's no single "combined" server that holds every tool. Keeping them separate means each process can only do its own job.
- The `mock-portal` MCP server doesn't store anything itself. It forwards requests over HTTP to the portal website, which owns the database.

The four entry points:

| Service | File | Run as |
|---|---|---|
| `rule-engine` | [`src/mcp_servers/rule_engine_server.py`](../src/mcp_servers/rule_engine_server.py) | `python -m src.mcp_servers.rule_engine_server` |
| `schemes-kb` | [`src/mcp_servers/schemes_kb_server.py`](../src/mcp_servers/schemes_kb_server.py) | `python -m src.mcp_servers.schemes_kb_server` |
| `doc-check` | [`src/mcp_servers/doc_check_server.py`](../src/mcp_servers/doc_check_server.py) | `python -m src.mcp_servers.doc_check_server` |
| `mock-portal` | [`src/mcp_servers/mock_portal_server.py`](../src/mcp_servers/mock_portal_server.py) | `python -m src.mcp_servers.mock_portal_server` |

You normally **don't** start these yourself. The API starts them.

---

## 2. What happens when the app starts

All of this is in the `lifespan` function in [`src/api/app.py`](../src/api/app.py).

1. **Load the scheme rules.** If they're missing or broken, the API refuses to start.
2. **Start the portal website** as its own process and wait until it answers a health check.
3. **For each of the 4 services:**
   1. Start it as a child process (`python -m <module>`), connected over stdio.
   2. Ask it: *"which tools do you have?"* (`client.list_tools()`).
   3. Compare the answer with the expected list in `SERVICE_TOOLS` ([`service_routing.py`](../src/mcp_servers/service_routing.py)).
   4. If any tool is **missing** or **unexpected**, stop with an error like:
      ```
      MCP service doc-check tool inventory mismatch; missing=['check_documents'], unexpected=[]
      ```
      This is **fail closed**: the API never serves requests with a wrong set of tools.
   5. Keep the connected client.
4. **Wrap all 4 clients in one guard**: `ServiceClientRouter(clients)`.
5. **Start serving requests.**

From then on, every tool call is **routed by tool name**: the guard looks up which service owns the tool (for example, `check_documents` → `doc-check`) and sends the call there, but only after the permission checks pass.

---

## 3. The tool catalogue

There are 11 tools across 4 services.

**How to read the table:**
- **Risk:** 🟢 read-only, 🟡 write, 🔴 destructive write.
- **Roles that may call it** comes from `ACTOR_TOOLS` in [`service_routing.py`](../src/mcp_servers/service_routing.py). `api_read` is the role for the website's read-only pages.
- **Access and result (details)** is the precise technical description.

| Service | Tool | In plain words | Risk | Roles that may call it | Access and result (details) |
|---|---|---|---|---|---|
| `rule-engine` | `evaluate_eligibility(scheme_id, profile)` | Decides whether a household qualifies for a scheme, using fixed rules | 🟢 | `api_read`, `intake`, `eligibility` | Deterministic, read-only rule evaluation; typed eligibility response, never LLM-decided. |
| `rule-engine` | `required_facts(scheme_id)` | Lists which facts about the user are needed for that decision | 🟢 | `api_read`, `intake` | Read-only list of facts declared by the versioned rule package. |
| `schemes-kb` | `search_schemes(query, jurisdiction, language, limit)` | Searches scheme information | 🟢 | `api_read`, `eligibility` | Read-only ranked source passages. |
| `schemes-kb` | `get_scheme(scheme_id)` | Gets basic details of one scheme | 🟢 | `api_read`, `eligibility` | Read-only corpus identity, languages, source IDs, and review statuses. |
| `schemes-kb` | `get_documents(scheme_id)` | Gets the list of documents a scheme needs | 🟢 | `api_read`, `documents` | Read-only direct load of the shared versioned checklist; returns groups, alternatives, conditions, citations, fingerprints, and explicit trust status. |
| `doc-check` | `check_documents(scheme_id, documents)` | Compares what the user says they have against that list | 🟢 | `documents` | Read-only metadata comparison using the same fresh checklist loader; does not inspect or authenticate document contents. |
| `mock-portal` | `create_draft(...)` | Creates a draft application | 🟡 | `application` | Write to the isolated local portal DB; synthetic drafts only. |
| `mock-portal` | `get_draft(journey_id, draft_id)` | Reads a draft, only within its own journey | 🟢 | `api_read`, `application` | Read-only, scoped to the supplied journey. |
| `mock-portal` | `get_status(journey_id, draft_id)` | Reads whether a draft is pending, approved, rejected or submitted | 🟢 | `api_read`, `application` | Read-only draft/approval/rejection/mock-submission status. |
| `mock-portal` | `submit_draft(journey_id, draft_id, revision, fingerprint, approval_token)` | Submits the form, but only the exact version a human approved | 🔴 | `application` | Destructive, idempotent write; the portal accepts only the exact human-approved revision and fingerprint. |
| `mock-portal` | `mock_portal(action, ...)` | One gateway for many portal actions: read, write, approve, reject, clean up, dependency control | 🔴 | `api_read`, `application`, `human_approval`, `session_cleanup`, `dependency_control` (each limited to certain actions) | Current trusted API/workflow action gateway for scoped draft reads/writes, exact approval, rejection, cleanup and dependency control. Models never receive this unrestricted gateway. |

### Notes on the table

- **Being able to call `mock_portal` doesn't mean being able to do everything with it.** Each role may only use certain `action` values (the `PORTAL_ACTIONS` table). For example, only `human_approval` may use `approve` and `reject`.
- **"Models never receive this unrestricted gateway"** means the AI is never handed a raw connection to `mock_portal`. It always goes through the guard, which limits it to its role's allowed actions and its own journey.
- **`submit_draft` also needs an `approval_token`.** This is a one-time permission slip created when a human approves. The backend keeps it and never shows it to the user (see `_public_application_record` in [`app.py`](../src/api/app.py)).
- **`evaluate_eligibility` is "never LLM-decided."** The AI never decides whether someone qualifies. Fixed, versioned rules do. The AI can only ask for the result.

---

## 4. What a tool call looks like

Behind the scenes, a call is just: **tool name + a dictionary of inputs → a result**.

### A read-only call

```python
result = await client.call_tool("required_facts", {"scheme_id": "IGNWPS-MH"})
```

On success:
- `result.is_error` is `False`.
- `result.structured_content` holds the data, already decoded into Python dictionaries and lists.

This is how our code reads results (for example, in [`src/workflow/eligibility.py`](../src/workflow/eligibility.py)):

```python
if result.is_error or result.structured_content is None:
    ...  # treat it as a failure
data = result.structured_content
```

### A failed call

```python
result = await client.call_tool("required_facts", {"scheme_id": "NO-SUCH-SCHEME"})
```

- `result.is_error` is `True`.
- The error text is the shared JSON error format (see section 5):
  ```json
  {"error":{"code":"not_found","message":"Unknown scheme."}}
  ```

### A write call

```python
await guard.call_tool("create_draft", {
    "journey_id": "conv-42",
    "scheme_id": "IGNWPS-MH",
    "profile": {...},
    "documents": {...},
})
```

Same shape: name plus inputs. The differences are that the guard only allows it for the `application` role, and that it changes data in the portal database.

---

## 5. Inputs and errors

### Inputs are checked before your code runs

Each tool's **input schema is generated automatically** from Pydantic models and the function's type hints. For example:

```python
def required_facts(scheme_id: str) -> list[str]:
```

MCP reads `scheme_id: str` and publishes a schema saying "this tool needs one text input called `scheme_id`." If a caller leaves it out or sends the wrong type, **MCP rejects the call before the function runs.** You don't write that checking yourself.

### Labels on each tool

**Read/write hints are published as MCP annotations**, so any client can see how risky a tool is:

```python
@mcp.tool(
    annotations=ToolAnnotations(
        title="List required scheme facts",
        readOnlyHint=True,       # only reads
        destructiveHint=False,   # doesn't destroy anything
        idempotentHint=True,     # safe to repeat
        openWorldHint=False,     # doesn't reach the outside internet
    )
)
```

Annotations are **labels, not locks.** They describe the tool; the guard is what actually enforces permissions.

### One error format for every service

All services report errors in the same JSON shape:

```json
{"error": {"code": "invalid_input", "message": "..."}}
```

There are exactly 5 codes:

| Code | Meaning |
|---|---|
| `invalid_input` | The inputs were wrong or incomplete. |
| `not_found` | The thing asked for doesn't exist (for example, an unknown scheme). |
| `conflict` | The request clashes with the current state (for example, the draft changed since it was approved). |
| `service_unavailable` | A service needed for this isn't reachable right now. |
| `internal_error` | Something unexpected went wrong inside the service. |

This shape is defined once in [`src/mcp_servers/contracts.py`](../src/mcp_servers/contracts.py). Tools raise errors with the helper `tool_error(code, message)`:

```python
raise tool_error("not_found", "Unknown scheme.")
```

### Errors don't repeat what the user sent

**Schema and portal validation errors don't echo submitted values.** If a user sends their name and date of birth and something is wrong, the error says *what kind* of problem it was, not the personal data itself. That keeps private information out of error messages and logs.

---

## 6. Safety rules

These rules decide **who may do what**. The full beginner explanation of how they're enforced is in [`MCP_PERMISSIONS_WALKTHROUGH.md`](MCP_PERMISSIONS_WALKTHROUGH.md).

| Rule | Why |
|---|---|
| The Phase 3 dependency actions (`begin_profile_change`, `reconcile_profile`, `bind_documents`, `bind_rules`, `dependency_status`) belong **only** to the code-owned `dependency_control` actor. | These keep a draft consistent when the user's profile, documents or rules change. Only trusted code may run them, never the AI. |
| **Application actors can't approve.** | The agent that prepares a form must never approve its own work. |
| **`human_approval` is bound only when resuming an exact human decision.** | The approve and reject powers only exist at the moment a real person has clicked Approve or Reject. |
| **Portal changes carry the checkpoint's expected profile version.** | If the user's profile changed in the meantime, the portal sees the version doesn't match and rejects the change instead of saving outdated data. |
| **Invalidation and reconciliation aren't the AI's choice.** | Deciding that old data is out of date, and fixing it, is done by fixed code rules, not by the model. |

---

## 7. The eligibility agent's own actions

The eligibility agent has four small actions of its own: `check_candidate`, `handoff_verdict`, `request_clarification` and `refer_for_help`.

- These are **typed workflow wrappers**: small helper functions inside the workflow code.
- They are **not** extra MCP services, and they are **not** verdicts written by the model.
- When they need rules or scheme information, they still call `rule-engine` and `schemes-kb` **through the guard, as the `eligibility` role**, so they get only that role's limited permissions.

In other words, giving the agent a helper doesn't give it any extra power.

---

## 8. The mock portal

The portal is a small separate website that stands in for a government application portal.

| Fact | Value |
|---|---|
| App | `src.portal.app:app` (FastAPI) |
| Address | `SCHEME_SAATHI_PORTAL_URL`, default `http://127.0.0.1:8765` (must be localhost with an explicit port) |
| Database | SQLite file at `SCHEME_SAATHI_PORTAL_DB`, default `data/runtime/portal.sqlite3` |
| Started by | the API's lifespan ([`src/api/portal_service.py`](../src/api/portal_service.py)) |
| Other ports | The existing API (8000) and UI (8501) ports are unchanged. |

> ⚠️ **It's local and synthetic only.** The portal has **no** connection to any government system. Every draft and submission in it is test data.

---

## 9. Document checklists: status and safe updates

### Current status

- The two pilot files under `data/schemes/document_checklists/` are currently **explicitly demo-only**.
- The **document evidence corpus is empty.**
- Using a checklist as "source-backed" (trusted) requires **human approval of the exact file contents**. Until that exists, the system **fails closed** and doesn't treat the checklists as trusted.

### How to update a checklist safely

Always use the helper. **Never edit active checklist files by hand.**

1. **Prepare one complete JSON record at a time** and have it reviewed.
2. **Pass its encoded bytes to the helper:**
   ```python
   from src.documents.publication import publish_checklist_file

   publish_checklist_file(filename, content)   # content is bytes
   ```
3. **Order matters:** publish the **evidence corpus first**, then **each affected checklist**.
4. **Each checklist needs fresh human approval** of those exact bytes. Updating evidence **immediately makes old approvals stale**, so they must be redone.

**What the helper does:**
- Checks the file's structure and links.
- **Atomically** replaces the one file (all at once, so no one ever sees a half-written file).
- Increases a shared revision number.
- Holds the same cross-process lock as portal transactions, so a publish and a portal change can't interfere with each other.

**What the helper does NOT do:**
- It **doesn't approve** the data.
- It **doesn't check who the reviewer is.**

| ✅ Do | ❌ Don't |
|---|---|
| Use `publish_checklist_file` for every update | Edit files in `data/schemes/document_checklists/` by hand |
| Publish evidence before checklists | Publish a checklist that points at evidence not yet published |
| Get fresh approval after any evidence change | Assume an old approval still counts |

Manual edits skip this whole process and **aren't protected against race conditions** (two things changing the same data at once).

---

## 10. Build it yourself, step by step

This section builds a tiny version of the Saathi setup from nothing: **one MCP server, one tool, a client, a permission guard, and a test**. Every piece mirrors a real Saathi file.

The examples below were run against this project's environment (`mcp` 2.x).

### Step 1: Write a server with one tool

Create `greeting_server.py`:

```python
"""A tiny MCP server with one read-only tool."""

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel

mcp = MCPServer("greeting")            # 1. name the server


class Greeting(BaseModel):             # 2. describe the output shape
    message: str


@mcp.tool(                             # 3. publish the function as a tool
    annotations=ToolAnnotations(
        title="Say hello",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def say_hello(name: str) -> Greeting:  # 4. type hints become the input schema
    """Return a greeting for one person."""
    return Greeting(message=f"Hello, {name}!")


if __name__ == "__main__":
    mcp.run()                          # 5. run over stdio
```

What each part does:
1. `MCPServer("greeting")` creates a server named `greeting`.
2. `Greeting` is a Pydantic model for the result. **Return a Pydantic model, not a plain `dict`.** With a model, the client receives the data in `structured_content`; with a plain `dict` it doesn't.
3. `@mcp.tool(...)` publishes the function so clients can call it by name, with the risk labels from section 5.
4. `name: str` becomes the input schema. Calling it without `name` is rejected automatically.
5. `mcp.run()` starts the server and waits for a client over stdio.

**In Saathi:** this is [`rule_engine_server.py`](../src/mcp_servers/rule_engine_server.py) plus the `register_tools` function in [`tools/eligibility.py`](../src/mcp_servers/tools/eligibility.py). Saathi puts the tools in a separate `register_tools(mcp)` function so the server file stays tiny.

### Step 2: Call the tool from a client

Create `call_it.py` in the same folder:

```python
import asyncio
import sys

from mcp import Client, StdioServerParameters


async def main():
    # How to start the server: "python greeting_server.py"
    server = StdioServerParameters(command=sys.executable, args=["greeting_server.py"])

    async with Client(server) as client:        # starts the server and connects
        tools = await client.list_tools()        # "which tools do you have?"
        print([tool.name for tool in tools.tools])

        result = await client.call_tool("say_hello", {"name": "Asha"})
        print(result.is_error, result.structured_content)


asyncio.run(main())
```

Run `python call_it.py`. You should see:

```
['say_hello']
False {'message': 'Hello, Asha!'}
```

> 💡 **What are `async` and `await`?** Calling a tool means waiting for another process to answer. `async def` marks a function that can wait without freezing the whole program, and `await` is where it waits. `asyncio.run(main())` starts the waiting-capable function from normal code. For now, just copy the pattern.

**In Saathi:** this is the loop in the `lifespan` function of [`app.py`](../src/api/app.py), which builds a `StdioServerParameters` for each service and opens a `Client`.

### Step 3: Check the tool list at startup (fail closed)

Before using a server, check that it has exactly the tools you expect:

```python
EXPECTED = {"greeting": {"say_hello"}}

tools = await client.list_tools()
found = {tool.name for tool in tools.tools}
if found != EXPECTED["greeting"]:
    raise RuntimeError(f"greeting server has the wrong tools: {sorted(found)}")
```

**In Saathi:** this is the inventory mismatch check in [`app.py`](../src/api/app.py) against `SERVICE_TOOLS`.

### Step 4: Put a guard in front of the server

Create `guard.py`:

```python
"""A tiny permission guard in front of MCP servers."""

ALLOWED_TOOLS = {                       # who may use which tools (allow-list)
    "greeter": {"say_hello"},
    "reader": set(),                    # may use nothing
}

SERVICE_TOOLS = {                       # which server owns which tools
    "greeting": {"say_hello"},
}


class PermissionDenied(Exception):
    pass


class Guard:
    def __init__(self, clients, role):
        if role not in ALLOWED_TOOLS:
            raise PermissionDenied("Unknown role.")
        self.clients = clients          # {"greeting": <client>}
        self.role = role                # set by OUR code, never by the AI

    async def call_tool(self, name, arguments):
        # Check 1: is this tool allowed for this role?
        if name not in ALLOWED_TOOLS[self.role]:
            raise PermissionDenied("This role may not use this tool.")
        # Check 2: the caller can't choose its own role.
        if "role" in arguments:
            raise PermissionDenied("Arguments cannot set the role.")
        # All checks passed: find the owning server and run the tool.
        owners = [service for service, tools in SERVICE_TOOLS.items() if name in tools]
        if len(owners) != 1:
            raise PermissionDenied("No single server owns this tool.")
        return await self.clients[owners[0]].call_tool(name, arguments)
```

Use it:

```python
async with Client(server) as greeting_client:
    clients = {"greeting": greeting_client}

    greeter = Guard(clients, role="greeter")
    result = await greeter.call_tool("say_hello", {"name": "Asha"})
    print(result.structured_content)          # {'message': 'Hello, Asha!'}

    reader = Guard(clients, role="reader")
    await reader.call_tool("say_hello", {"name": "Asha"})
    # raises PermissionDenied: This role may not use this tool.
```

> ⚠️ **The most important rule:** give the AI the **guard**, never the raw `client`. If the AI can reach the client directly, the guard does nothing.

**In Saathi:** this is `ServiceClientRouter` in [`service_routing.py`](../src/mcp_servers/service_routing.py). Saathi's guard adds two more checks: portal actions (`PORTAL_ACTIONS`) and same-journey (`journey_id`). See [`MCP_PERMISSIONS_WALKTHROUGH.md`](MCP_PERMISSIONS_WALKTHROUGH.md).

### Step 5: Test that a blocked call never reaches the server

Create `test_guard.py`:

```python
import asyncio

import pytest

from guard import Guard, PermissionDenied


class FakeServer:
    """Stands in for a real client. It only counts calls."""

    def __init__(self):
        self.calls = 0

    async def call_tool(self, name, arguments):
        self.calls += 1
        return "ok"


def test_allowed_role_reaches_server():
    fake = FakeServer()
    guard = Guard({"greeting": fake}, role="greeter")
    asyncio.run(guard.call_tool("say_hello", {"name": "Asha"}))
    assert fake.calls == 1


def test_blocked_role_never_reaches_server():
    fake = FakeServer()
    guard = Guard({"greeting": fake}, role="reader")
    with pytest.raises(PermissionDenied):
        asyncio.run(guard.call_tool("say_hello", {"name": "Asha"}))
    assert fake.calls == 0


def test_arguments_cannot_set_role():
    fake = FakeServer()
    guard = Guard({"greeting": fake}, role="greeter")
    with pytest.raises(PermissionDenied):
        asyncio.run(guard.call_tool("say_hello", {"name": "Asha", "role": "admin"}))
    assert fake.calls == 0
```

Run `python -m pytest test_guard.py`. All 3 tests should pass.

The key line is `assert fake.calls == 0`. It proves a blocked call never reached the server, not just that an error appeared.

**In Saathi:** this is `test_denied_calls_never_execute` in [`tests/test_mcp_permissions.py`](../tests/test_mcp_permissions.py).

### Step 6: Grow it into the Saathi shape

Once the tiny version works, these are the steps to the full design:

| Add this | How | Saathi file |
|---|---|---|
| More servers | One file per area of work, each with its own `MCPServer(...)` | `src/mcp_servers/*_server.py` |
| Tools in their own module | `register_tools(mcp)` functions | `src/mcp_servers/tools/*.py` |
| Shared error format | `tool_error(code, message)` | `contracts.py` |
| Start everything at app startup | FastAPI `lifespan` that opens all clients and checks inventories | `src/api/app.py` |
| Per-journey checks | Store `journey_id` on the guard and compare on every portal call | `service_routing.py` |
| Multi-action tool | A second allow-list for `action` values | `PORTAL_ACTIONS` |
| Role binding | A `for_actor(role, journey_id)` method that returns a new guard | `service_routing.py` |

### Checklist for adding a new tool to Saathi

1. Write the function in the right `src/mcp_servers/tools/*.py` file, inside `register_tools`, with type hints, a Pydantic return type, and `ToolAnnotations`.
2. Raise errors with `tool_error(...)` using one of the 5 codes, and never put user-submitted values in the message.
3. Add the tool name to the right service in `SERVICE_TOOLS`. Otherwise the startup inventory check fails.
4. Add it to `ACTOR_TOOLS` **only** for roles that really need it.
5. Add a row to [section 3](#3-the-tool-catalogue) and to the [Quick reference](#quick-reference).
6. Add tests: one showing it works for an allowed role, one showing a forbidden role is blocked with zero server calls.

### Common mistakes

| Mistake | What goes wrong |
|---|---|
| Giving the AI the raw client | The guard is bypassed completely. |
| Letting the AI pass its role in the arguments | The AI can promote itself to any role. |
| Using a block-list ("forbid X") instead of an allow-list | Any new tool is allowed by default. |
| Returning a plain `dict` from a tool | `structured_content` comes back empty. |
| Forgetting to update `SERVICE_TOOLS` | The API refuses to start (inventory mismatch). |
| Putting user data in error messages | Personal information ends up in logs. |
| Combining all tools in one server | One crash or bug affects everything, and every tool shares one process's access. |

---

## 11. How it's tested

| Test file | What it checks |
|---|---|
| [`tests/test_mcp_services.py`](../tests/test_mcp_services.py) | Exact tool discovery, input-schema rejection, structured errors, dispatch ownership, and the shared checklist version and fingerprint for both pilots. |
| [`tests/test_document_checklists.py`](../tests/test_document_checklists.py) | Checklist schema, evidence, approval and mutation gates. |
| [`tests/test_api_eligibility.py`](../tests/test_api_eligibility.py) | API startup discovery and the generic eligibility path. |
| [`tests/test_api_applications.py`](../tests/test_api_applications.py) | The exact-approval flow through the independent portal HTTP process. |
| [`tests/test_mcp_permissions.py`](../tests/test_mcp_permissions.py) | Forbidden calls never execute; each role can use only its allowed portal actions. |

Run them from the `scheme-saathi-capstone` folder:

```
..\venv\Scripts\python.exe -m pytest tests/test_mcp_services.py tests/test_mcp_permissions.py
```

> These automated checks **don't** claim manual browser acceptance. Someone still needs to click through the UI to confirm it works for a real user.

To watch the permission guard work, run the practice script [`scripts/try_permissions.py`](../scripts/try_permissions.py).

---

## Quick reference

| MCP service | Tool | Access and result |
|---|---|---|
| `rule-engine` | `evaluate_eligibility(scheme_id, profile)` | Deterministic, read-only rule evaluation; typed eligibility response, never LLM-decided. |
| `rule-engine` | `required_facts(scheme_id)` | Read-only list of facts declared by the versioned rule package. |
| `schemes-kb` | `search_schemes(query, jurisdiction, language, limit)` | Read-only ranked source passages. |
| `schemes-kb` | `get_scheme(scheme_id)` | Read-only corpus identity, languages, source IDs, and review statuses. |
| `schemes-kb` | `get_documents(scheme_id)` | Read-only direct load of the shared versioned checklist; returns groups, alternatives, conditions, citations, fingerprints, and explicit trust status. |
| `doc-check` | `check_documents(scheme_id, documents)` | Read-only metadata comparison using the same fresh checklist loader; does not inspect or authenticate document contents. |
| `mock-portal` | `create_draft(...)` | Write to the isolated local portal DB; synthetic drafts only. |
| `mock-portal` | `get_draft(journey_id, draft_id)` | Read-only, scoped to the supplied journey. |
| `mock-portal` | `get_status(journey_id, draft_id)` | Read-only draft/approval/rejection/mock-submission status. |
| `mock-portal` | `submit_draft(journey_id, draft_id, revision, fingerprint, approval_token)` | Destructive, idempotent write; the portal accepts only the exact human-approved revision and fingerprint. |
| `mock-portal` | `mock_portal(action, ...)` | Current trusted API/workflow action gateway for scoped draft reads/writes, exact approval, rejection, cleanup and dependency control. Models never receive this unrestricted gateway. |
