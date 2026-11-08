# Tool Permissions in Scheme Saathi: A Beginner's Guide

This guide is for someone who has **never worked with permissions before**. You don't need to know anything about security. If you know basic Python (variables, `if`, functions, dictionaries), you have enough to follow it.

All the code we'll talk about is in one short file: [`src/mcp_servers/service_routing.py`](../src/mcp_servers/service_routing.py) (about 120 lines).

---

## Part 0: First, some words you'll need

**Tool.** A Python function the AI is allowed to ask for. For example, `check_documents` checks a user's documents, and `submit_draft` submits an application form.

**MCP.** The system Scheme Saathi uses to run tools. You don't need to know how it works. Just think: "MCP is how the AI asks for a tool to be run."

**Agent.** One part of the AI that has one job. Scheme Saathi has several agents:

| Agent | Its job |
|---|---|
| intake agent | asks the user questions |
| eligibility agent | finds schemes the user qualifies for |
| documents agent | checks the user's documents |
| application agent | fills in and submits the form |

**Role** (called `actor` in the code). A label saying which agent is calling, for example `"documents"` or `"application"`.

**Permission.** A rule that says **who** is allowed to do **what**.

**Conversation** (called `journey_id` in the code). One user's case. Every user gets their own ID, like `"conv-42"`.

---

## Part 1: Why do we need permissions at all?

An AI can make mistakes. It might:

- try to submit a form when it was only supposed to check documents
- try to approve a form, which only a human should do
- get confused and touch **another user's** form

We can't fully trust what the AI asks for. So **before any tool runs, our code checks whether the request is allowed.** If it isn't, the tool doesn't run.

That's all "permissions" means here.

---

## Part 2: The office building analogy

Keep this picture in mind for the rest of the guide:

| In the building | In the code |
|---|---|
| 🏢 Rooms | Tools (`check_documents`, `submit_draft`, ...) |
| 🧑‍💼 Employees | Agents |
| 🪪 ID badge | Role + conversation, given by our code |
| 💂 Security guard | The function `call_tool` |
| 📋 Guard's rulebook | The dictionaries `ACTOR_TOOLS` and `PORTAL_ACTIONS` |

**How it works:**

1. Our code gives each agent a badge. The agent **can't make its own badge.**
2. The agent walks up to the guard and asks to enter a room.
3. The guard looks at the badge, checks the rulebook, and says **yes** or **no**.
4. Only on **yes** does the agent get into the room (the tool runs).

The rest of this guide shows each of these four steps in the code.

---

## Part 3: The rulebook

### Rulebook 1: which tools each role may use

```python
ACTOR_TOOLS = {
    "intake":         frozenset({"required_facts", "evaluate_eligibility"}),
    "eligibility":    frozenset({"evaluate_eligibility", "search_schemes", "get_scheme"}),
    "documents":      frozenset({"get_documents", "check_documents"}),
    "application":    frozenset({"create_draft", "get_draft", "get_status",
                                 "submit_draft", "mock_portal"}),
    "human_approval": frozenset({"mock_portal"}),
    # ... a few more roles
}
```

**How to read it.** Take this line:

```python
"documents": frozenset({"get_documents", "check_documents"}),
```

In plain English: *"The documents role may use `get_documents` and `check_documents`. Nothing else."*

**The Python bits:**
- `{ "key": value, ... }` is a **dictionary**: a lookup table. You give it a key and get back a value.
  `ACTOR_TOOLS["documents"]` gives back `{"get_documents", "check_documents"}`.
- `frozenset({...})` is a **list that can't be changed** while the program runs. That's on purpose, so nothing can quietly add permissions later.

**Important idea: allow-list.** We write down only what **is** allowed. Anything not written down is **forbidden**. If someone forgets to add a tool here, the agent just gets blocked, which is the safe kind of mistake.

#### Try it

Using the table above, answer these:
1. May the `documents` role use `submit_draft`?
2. May the `eligibility` role use `search_schemes`?

<details>
<summary>Answers</summary>

1. **No.** `submit_draft` isn't in the documents list.
2. **Yes.** `search_schemes` is in the eligibility list.

</details>

### Rulebook 2: which "buttons" each role may press on the portal

One tool, `mock_portal`, is special. It's **one room with several buttons inside**. The agent says which button it wants with an `action`:

```python
call_tool("mock_portal", {"action": "approve", ...})   # wants to press "approve"
call_tool("mock_portal", {"action": "submit", ...})    # wants to press "submit"
```

Being allowed into the room isn't enough. Each **button** has its own permission list:

```python
PORTAL_ACTIONS = {
    "api_read":       frozenset({"list_drafts", "get_draft", "get_status"}),
    "application":    frozenset({"list_drafts", "get_draft", "get_status",
                                 "create_draft", "edit_draft", "submit"}),
    "human_approval": frozenset({"get_draft", "approve", "reject"}),
    # ... a few more roles
}
```

Look closely: **`approve` and `reject` appear only under `human_approval`.** That's how the code makes sure only a human can approve a form. The application agent can submit, but it can't approve its own work.

### Rulebook 3: which server owns each tool (an address book)

```python
SERVICE_TOOLS = {
    "rule-engine": frozenset({"evaluate_eligibility", "required_facts"}),
    "schemes-kb":  frozenset({"search_schemes", "get_scheme", "get_documents"}),
    "doc-check":   frozenset({"check_documents"}),
    "mock-portal": frozenset({"create_draft", "get_draft", "get_status",
                              "submit_draft", "mock_portal"}),
}
```

This one is **not** about permission. It's the building directory: once the guard says yes, it uses this to find which server actually runs the tool. For example, `check_documents` lives on the `doc-check` server.

---

## Part 4: Giving out the badge

Before an agent can ask for anything, **our code** gives it a badge using a method called `for_actor`:

```python
router = base.for_actor("documents", "conv-42")
#                        ↑ role        ↑ conversation
```

This creates a guard object that remembers:
- `actor = "documents"`: who is calling
- `journey_id = "conv-42"`: which user's case they're working on

Here's the code:

```python
def for_actor(self, actor, journey_id=None):
    if actor not in ACTOR_TOOLS:
        raise MCPToolError("Unknown tool caller.")
    return ServiceClientRouter(self.clients, actor, journey_id)
```

Line by line:
1. If the role name isn't in the rulebook (for example, a typo), stop with an error.
2. Otherwise, build a **new** guard object that remembers this role and conversation.

**The most important point in this guide:**

> The role is set by **our Python code**, never by the AI.

The AI is only handed the finished guard. It can ask for tools, but it can't change its badge.

Where our code does this:
- [`src/workflow/journey.py`](../src/workflow/journey.py): each agent gets its own role.
- [`src/api/app.py`](../src/api/app.py): the website's read-only pages get the `"api_read"` role.

---

## Part 5: The guard (`call_tool`), one check at a time

Every time an agent wants a tool, it calls:

```python
router.call_tool(name, arguments)
```

- `name` is the tool it wants, for example `"check_documents"`.
- `arguments` is a dictionary of extra details, for example `{"journey_id": "conv-42"}`.

Inside `call_tool`, two more values come from the badge:
- `self.actor` is the role, for example `"documents"`.
- `self.journey_id` is the conversation, for example `"conv-42"`.

> 💡 **What's `self`?** It means "this guard object." `self.actor` means "the role written on this guard's badge."

> 💡 **What's `raise`?** It means "stop right now and report an error." When the code reaches `raise`, **nothing after it runs**, so the tool never runs.

The guard asks four questions in order. Any "no" stops everything.

### Question 1: is this tool on your list?

```python
if name not in ACTOR_TOOLS[self.actor]:
    raise MCPToolError("This caller is not allowed to use this tool.")
```

**Worked example:** the documents agent asks for `submit_draft`.

Swap in the real values:
```python
if "submit_draft" not in ACTOR_TOOLS["documents"]:
```
`ACTOR_TOOLS["documents"]` is `{"get_documents", "check_documents"}`.
Is `"submit_draft"` missing from that list? **Yes.** So the code runs `raise`.

❌ **Blocked.** The form isn't submitted.

### Question 2: is this button allowed? (portal tools only)

```python
if name in SERVICE_TOOLS["mock-portal"]:      # is this a portal tool?

    # Work out which button is being pressed:
    if name == "mock_portal":
        action = arguments.get("action")      # read it from the arguments
    elif name == "submit_draft":
        action = "submit"
    else:
        action = name                         # e.g. "get_draft"

    if action not in PORTAL_ACTIONS.get(self.actor, frozenset()):
        raise MCPToolError("This caller is not allowed to use this portal action.")
```

*(In the real file, the "work out which button" part is squeezed into one line. It does the same thing.)*

This only happens for portal tools. Other tools, like `check_documents`, **skip questions 2 and 3.**

**Worked example:** the application agent asks for `mock_portal` with `"action": "approve"`.

1. Is `mock_portal` a portal tool? **Yes**, so we go inside.
2. `action` becomes `"approve"`.
3. Is `"approve"` in `PORTAL_ACTIONS["application"]`? That list is `list_drafts, get_draft, get_status, create_draft, edit_draft, submit`. **No.**

❌ **Blocked.** Only `human_approval` can approve.

### Question 3: is this your conversation? (portal tools only)

```python
    if self.journey_id is None or arguments.get("journey_id") != self.journey_id:
        raise MCPToolError("Portal calls require the bound journey context.")
```

In plain English: *"If your badge has no conversation, or you're asking about a different conversation from the one on your badge, stop."*

**Worked example:** the badge says `conv-42`, but the request says `{"journey_id": "conv-99"}`.
`"conv-99"` is not equal to `"conv-42"`.

❌ **Blocked.** One user's agent can't touch another user's form, even if it has the right role.

### Question 4: are you trying to fake your role?

```python
if any(key in arguments for key in ("actor", "caller", "trusted_actor")):
    raise MCPToolError("Tool arguments cannot set caller identity.")
```

In plain English: *"If the request contains a field called `actor`, `caller` or `trusted_actor`, stop."*

**Worked example:** the documents agent sends `check_documents` with `{"actor": "human_approval"}`.
It's trying to pretend to be a human approver. The arguments contain `"actor"`.

❌ **Blocked.** The role only ever comes from the badge, never from the request.

### All four passed: run the tool

```python
owners = [service for service, tools in SERVICE_TOOLS.items() if name in tools]
if len(owners) != 1 or owners[0] not in self.clients:
    raise ValueError(f"No unique MCP service owns tool {name!r}.")
return await self.clients[owners[0]].call_tool(name, arguments)
```

In plain English:
1. Look in the address book (`SERVICE_TOOLS`) for the server that owns this tool. For `check_documents`, that's `"doc-check"`.
2. If exactly one server doesn't own it, something is set up wrong, so stop.
3. Send the request to that server and return its answer.

✅ **This last line is the only place in the whole file where a tool actually runs.** Every check above is a gate in front of it.

---

## Part 6: The whole journey of one request

Let's follow **the documents agent asking for `check_documents`**, from start to finish:

```
1. Our code makes the badge:
       router = base.for_actor("documents", "conv-42")

2. The AI asks:
       router.call_tool("check_documents", {})

3. The guard checks:
       Q1  Is check_documents on the documents list?    YES ✅
       Q2  Is it a portal tool?                          NO → skip Q2 and Q3
       Q4  Does {} contain "actor"?                      NO  ✅

4. Find the owner:   check_documents → "doc-check"

5. Run it:           self.clients["doc-check"].call_tool("check_documents", {})

6. The answer comes back to the AI.
```

And here's the same thing for **the application agent trying to approve**:

```
1. Badge:       for_actor("application", "conv-42")
2. AI asks:     call_tool("mock_portal", {"action": "approve", "journey_id": "conv-42"})
3. Q1  Is mock_portal on the application list?           YES ✅
   Q2  Is "approve" on the application button list?      NO  ❌  → raise

   Stop. Steps 4 to 6 never happen. The portal server is never contacted.
```

---

## Part 7: "Whose `call_tool` runs at the very end?"

This confuses most people at first, so here it is slowly.

There are **two different** `call_tool` methods:

1. **The guard's** `call_tool`: the checks we just walked through.
2. **The server's** `call_tool`: the one that actually does the work.

The guard keeps a dictionary of servers called `self.clients`. On its last line, it picks the right server out of that dictionary and calls **that server's** `call_tool`:

```python
self.clients["doc-check"].call_tool(...)
#  ↑ the guard's dictionary  ↑ the server's own method
```

**What's in `self.clients` depends on where the code is running:**

| Where | What's in `self.clients` | What happens |
|---|---|---|
| The real app ([`app.py`](../src/api/app.py)) | real connections to the servers | the real tool runs |
| Tests and the practice script | `FakeServer` objects | nothing real happens; the fake just notes "I was called" |

The guard doesn't care which kind it has. It only needs something with a `call_tool` method. That's why we can test the guard safely with fake servers.

> This isn't "overriding." The guard and the server are separate objects. The guard **holds** the servers and **passes the job on** to one of them.

---

## Part 8: How we know it works (tests)

The tests in [`tests/test_mcp_permissions.py`](../tests/test_mcp_permissions.py) use **fake servers that count how many times they were called**.

For every forbidden request, the test checks:

```python
assert service.calls == 0
```

This proves the guard stopped the request **before** it reached any server. It's a stronger check than just "an error appeared."

---

## Part 9: Try it yourself

There's a practice script: [`scripts/try_permissions.py`](../scripts/try_permissions.py). It sends example requests through the **real** guard, using fake servers.

Run it from the `scheme-saathi-capstone` folder:

```
..\venv\Scripts\python.exe scripts\try_permissions.py
```

You'll see output like:

```
documents asks for submit_draft {'journey_id': 'conv-42'}
   BLOCKED: This caller is not allowed to use this tool.
   (no server was called)
```

**Practice:** at the bottom of the script, change an example (for example, change `"application"` to `"human_approval"`). **Guess the result first**, then run it and see if you were right.

---

## Part 10: Common tasks

**"I want to let a role use a new tool."**
Add the tool name to that role's set in `ACTOR_TOOLS`:

```python
"documents": frozenset({"get_documents", "check_documents", "my_new_tool"}),
```

**"I want to let a role press a new portal button."**
Make sure the role has `mock_portal` in `ACTOR_TOOLS`, then add the button to its set in `PORTAL_ACTIONS`.

**"I'm adding a whole new tool."**
1. Add it to the right server in `SERVICE_TOOLS` (so the guard knows where it lives).
2. Add it to every role that should use it in `ACTOR_TOOLS`.
3. Add a test showing that a role **without** permission is blocked with zero server calls.

**"My agent's call is getting blocked."**
Read the error message. It tells you which question failed:

| Error message | Which question | What to check |
|---|---|---|
| `not allowed to use this tool` | Q1 | Is the tool in `ACTOR_TOOLS` for this role? |
| `not allowed to use this portal action` | Q2 | Is the action in `PORTAL_ACTIONS` for this role? |
| `require the bound journey context` | Q3 | Does `journey_id` in the arguments match the badge? |
| `cannot set caller identity` | Q4 | Remove `actor` / `caller` from the arguments |

> ⚠️ Before giving a role more permissions, ask: **does this agent really need it to do its one job?** Give each role the smallest list that works.

---

## Summary: the five rules

1. **One guard, one door.** Every tool call goes through `call_tool`. There's no other way to reach a server.
2. **Allow-list.** Only what's written down is allowed. Everything else is blocked.
3. **Our code gives the badge, never the AI.** The role is set with `for_actor`.
4. **Check the data, not just the tool.** An agent may only touch its own conversation.
5. **Test that "blocked" means "never ran."** Fake servers must show zero calls.

If you remember just one sentence:

> **Before any tool runs, a guard checks the caller's badge against a written list, and any "no" stops the tool from running.**
