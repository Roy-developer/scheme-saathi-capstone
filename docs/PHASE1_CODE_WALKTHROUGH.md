# Phase 1 code walkthrough: one path for every scheme

This guide explains what Phase 1 built, in plain English. It is written for a
new developer who has not seen this code before. It follows one request from
the screen to the rule engine and back. It also lists every edge case Phase 1
handles.

Phase 1 plan: [PHASE_WISE_IMPLEMENTATION_PLAN.md](PHASE_WISE_IMPLEMENTATION_PLAN.md).

---

## The problem Phase 1 solves

Before Phase 1, the two schemes worked in two different ways:

| | Widow pension (IGNWPS-MH) | PM-KISAN (PM-KISAN-IN) |
|---|---|---|
| Rule file | `src/rules/packages/` | a separate `src/rules/pmkisan/` folder |
| Rule format | widow-only shape | its own shape |
| Engine | `evaluate_mock_eligibility` | a separate `evaluate_pmkisan_eligibility` |
| Path | UI → journey graph → MCP tool → engine | UI → its own API route → engine (no graph, no MCP) |

Two of everything means double the bugs and double the work for each new
scheme. It also blocks Phase 2, where the intake agent must ask questions for
**any** scheme.

**After Phase 1, every scheme has:**

- one profile shape (`HouseholdProfile`);
- one rule file format (JSON in `src/rules/packages/`);
- one engine (`evaluate_mock_eligibility`);
- one path: UI → journey graph → MCP tool → engine.

**What the user sees has not changed.** Phase 1 only changes the plumbing
behind the screen.

---

## The big picture

```
 You click "Check eligibility"
          │
          ▼
 ┌──────────────────────┐   Step 5
 │ UI  src/ui/app.py    │   turns your answers into a profile
 └─────────┬────────────┘
           │ POST /api/v1/journey
           ▼
 ┌──────────────────────┐   Step 4
 │ API  src/api/app.py  │   the web "front door"
 └─────────┬────────────┘
           ▼
 ┌──────────────────────────────┐   Step 4
 │ Journey graph                │   orchestrator → intake → eligibility
 │ src/workflow/journey.py      │   intake checks the request first
 └─────────┬────────────────────┘
           │ MCP call (separate program)
           ▼
 ┌──────────────────────────────────────┐   Step 4
 │ MCP tool                             │   looks up the scheme's rules
 │ src/mcp_servers/tools/eligibility.py │
 └─────────┬────────────────────────────┘
           ▼
 ┌──────────────────────────────┐   Step 3
 │ Engine src/api/eligibility.py│   checks each rule → verdict + evidence
 └─────────┬────────────────────┘
           │ reads
           ▼
 ┌────────────────────────────────────┐   Steps 1 and 2
 │ Profile + rules                    │
 │ src/rules/models.py                │
 │ src/rules/packages/*.json          │
 └────────────────────────────────────┘
```

We read it from the bottom up: first the data (Steps 1–2), then the engine
(Step 3), then how a request travels (Step 4), then the screen (Step 5).

### Meet our test people

We use these synthetic (made-up) people throughout. The application date is
always **30 October 2026**.

| Person | Facts | Expected result |
|---|---|---|
| **Sunita** | widow, born 30 Oct 1976 (age 50), BPL card shown | widow pension: eligible |
| **Meera** | widow, born 31 Oct 1986 (one day short of 40) | widow pension: not eligible (too young) |
| **Lata** | widow, age 50, did not show BPL card | widow pension: need more information |
| **Ramesh** | farmer with land, paid income tax last year | PM-KISAN: not eligible |
| **Gopal** | farmer with land, every exclusion "No" | PM-KISAN: eligible (mock only) |
| **Kamla** | farmer, answered "Unknown" to everything | PM-KISAN: need more information |

---

## Step 1: The household profile (`src/rules/models.py`)

### What it is

`HouseholdProfile` is a **form with blanks**. It holds every fact any scheme
might need. Each blank can be:

- `True` / `False` (yes / no), or a date;
- `None`, meaning **not known yet**.

```python
class HouseholdProfile(RulePackageModel):
    date_of_birth: date | None = None
    application_date: date | None = None
    is_widow: bool | None = None
    bpl_card_shown: bool | None = None
    landholding_family_in_state_records: bool | None = None
    institutional_landholder: bool | None = None
    # ... 6 more PM-KISAN facts
```

It is a **Pydantic model**. Pydantic checks the type of every value for us.
If a value has the wrong type, Pydantic raises a `ValidationError` before any
rule runs.

### Why "not known" (`None`) is so important

Before Phase 1, the widow profile had to be complete. One missing fact meant
the whole request was rejected. That makes a question-by-question chat
impossible.

Now a profile can start empty and fill up over time:

```
Start:          everything None
After answer 1: date_of_birth = 1976-10-30
After answer 2: is_widow = True
...
```

The engine (Step 3) treats `None` as "ask about this", not as "no". In
Phase 2, the intake agent will use this to decide what to ask next.

### Age is calculated, not stored

```python
@property
def age(self) -> int | None:
    if self.date_of_birth is None or self.application_date is None:
        return None
    return calculate_age_on(self.date_of_birth, self.application_date)
```

- `@property` lets you write `profile.age` as if it were a stored field.
- If either date is unknown, age is unknown (`None`).
- **Why not store age?** If we stored both age and date of birth, they could
  disagree (age 30 but born in 1976). Which one is true? Calculating it gives
  **one source of truth**. Rule: *do not store a value you can calculate.*

`fact_value(name)` is a small helper. It returns `profile.age` for `"age"`,
and the normal field for anything else. The engine uses it so it can treat
real and calculated facts the same way.

### Safety checks inside the profile

`validate_dates` runs automatically when a profile is created:

| Input | What happens |
|---|---|
| Born **after** the application date | Rejected: "date_of_birth cannot be after application_date" |
| Age over 125 | Rejected: "age on application_date cannot exceed 125" |
| Only one of the two dates known | Allowed. Age is just `None` for now |

The model also has `extra="forbid"`. An unknown field such as
`favourite_colour` is rejected ("Extra inputs are not permitted"). This stops
typos such as `is_widdow` from being silently ignored.

### Edge cases for Step 1

| Case | Result | Why |
|---|---|---|
| `HouseholdProfile()` (nothing given) | Valid; every fact `None` | Empty is allowed so the chat can start blank |
| `is_widow="maybe"` | Rejected | Not a yes/no value |
| `is_widow="yes"`, `"true"` or `"1"` | Accepted as `True` | Pydantic converts these common strings. Phase 2 code must still convert chat answers carefully |
| Born 29 Feb 1984, application 28 Feb 2024 | Age **39** | The birthday counts on 1 March in non-leap years, so the 40th birthday has not happened yet |
| Only `date_of_birth` given | Age `None` | Both dates are needed |

---

## Step 2: The rule packages (`src/rules/packages/*.json`)

### What they are

Each scheme has **one JSON file** that describes its rules as data. The
Python code never says "age must be 40". The JSON says it, and the code reads
it. To add a scheme, you add a JSON file, not Python.

Files:

- `ignwps_mh.v1.json`: widow pension, 4 rules.
- `pmkisan_in.v1.json`: PM-KISAN, 8 rules.

### The parts of a package

```json
{
  "scheme_id": "IGNWPS-MH",
  "package_version": "1.0.0",
  "approval_status": "approved_for_mock_portal",
  "approval_scope": "synthetic_mock_portal_only",
  "source": { "publisher": "...", "source_url": "...", "official_eligibility_text": "..." },
  "required_facts": ["date_of_birth", "application_date", "is_widow", "bpl_card_shown"],
  "reasons": {
    "eligible": "All reviewed mock conditions are met ...",
    "not_eligible": "One or more required mock scheme conditions are not met.",
    "need_more_information": "Show a government BPL card ..."
  },
  "rules": [ ... ]
}
```

| Part | Meaning |
|---|---|
| `scheme_id` | The scheme's unique name |
| `approval_status`, `approval_scope` | Who approved it and for what (synthetic mock only) |
| `source` | Where the rules came from, used as evidence |
| `required_facts` | Every fact this scheme needs. Phase 2 intake reads this list to know what to ask |
| `reasons` | The message shown for each verdict |
| `notice`, `unresolved_checks` | Optional warnings. PM-KISAN uses them to say it is based on 2020 guidelines |
| `rules` | The conditions |

### One rule

```json
{
  "rule_id": "IGNWPS-MH-AGE-MIN-01",
  "field": "age",
  "operator": "gte",
  "value": 40,
  "source_clause_id": "IGNWPS-MH-ELIGIBILITY-01"
}
```

Read it as: **"age must be greater than or equal to 40."**

| Operator | Meaning | Allowed with |
|---|---|---|
| `eq` | equal to | yes/no facts (`true` / `false`) |
| `gte` | greater than or equal to | `age` only (a whole number 0–125) |
| `lte` | less than or equal to | `age` only (a whole number 0–125) |

### "Must have" and "must not have" in one format

PM-KISAN needs both kinds of rule:

```json
{ "field": "landholding_family_in_state_records", "operator": "eq", "value": true }
{ "field": "income_tax_paid_last_assessment_year", "operator": "eq", "value": false }
```

- Land: the family **must have** land (`true`).
- Income tax: paying it **excludes** the family, so it **must be** `false`.

### The special rule: "show proof" instead of "rejected"

```json
{
  "rule_id": "IGNWPS-MH-BPL-01",
  "field": "bpl_card_shown",
  "operator": "eq",
  "value": true,
  "if_not_met": "need_more_information",
  "missing_field_label": "government_bpl_card"
}
```

Normally, failing a rule means **not eligible**. But a widow who did not show a
BPL card may still be poor; she may just not have it with her. So:

- `if_not_met: "need_more_information"` means failing this rule asks for proof
  instead of rejecting her.
- `missing_field_label` is the friendlier name shown in the missing list
  (`government_bpl_card` instead of `bpl_card_shown`).

### How the files are loaded and checked

`RulePackageProvider` (`src/rules/data_provider.py`) loads every
`*.json` file in the folder once, when the API and MCP server start. Each file
is checked against the `RulePackage` model. **If any file is wrong, the app
refuses to start.** It is better to fail at startup than to give a wrong
verdict later.

### Edge cases for Step 2 (all stop the app at startup)

| Mistake in a JSON file | Error |
|---|---|
| Two rules with the same `rule_id` | "Policy rule IDs must be unique" |
| A rule uses a fact not listed in `required_facts` | "Rules use facts missing from required_facts" |
| `required_facts` lists a fact twice | "required_facts must be unique" |
| `age` with `eq`, or age value outside 0–125 | "Invalid operator or value" |
| A yes/no fact with `gte`, or value `1` instead of `true` | "Invalid operator or value" |
| Minimum age higher than maximum age | "Minimum age cannot exceed maximum age" |
| Age rule but no `age_as_of` | "Age rules require age_as_of" |
| Two files with the same `scheme_id` | "Duplicate rule package for scheme" |
| No JSON files at all | "No scheme rule packages were found" |
| Any unknown key (typo) | Rejected, because extra fields are forbidden |

---

## Step 3: The engine (`src/api/eligibility.py`)

### What it does

`evaluate_mock_eligibility(profile, package)` takes **one profile** and
**one rule package**, and returns a verdict. It uses no AI. The same input
always gives the same output.

### Part A: checking one rule

```python
def _rule_is_met(rule, value):
    if rule.operator == "eq":
        return value == rule.value
    if rule.operator == "gte":
        return value >= rule.value
    return value <= rule.value      # lte
```

### Part B: sorting every rule into a group

```python
for rule in package.rules:
    value = profile.fact_value(rule.field)

    if value is None:                     # we don't know the fact
        unresolved_rules.append(rule)
        # add the unknown fact names to missing_fields
    elif not _rule_is_met(rule, value):   # we know it, and it fails
        if rule.if_not_met == "not_eligible":
            failed_rules.append(rule)
        else:                             # e.g. BPL card → ask for proof
            unresolved_rules.append(rule)
            # add the label to missing_fields
    # otherwise the rule passed; nothing to do
```

Every rule ends up **passed**, **failed** or **unresolved**.

### Part C: choosing the verdict (order matters)

```python
if failed_rules:        result = "not_eligible"
elif unresolved_rules:  result = "need_more_information"
else:                   result = "eligible"
```

1. **Any failed rule → not eligible.** Unknown facts do not matter any more;
   asking more questions would waste the person's time. The missing list is
   emptied.
2. **Otherwise, anything unknown → need more information**, with the list of
   what is missing.
3. **Otherwise → eligible.**

### Part D: the response

```
scheme_id                which scheme
result                   eligible / not_eligible / need_more_information
reason                   from the package's "reasons"
age_on_application_date  calculated age, or None
missing_fields           what to ask or show next
deciding_rule_ids        the rules that decided this verdict
evidence                 for each deciding rule: source URL, text, clause, location
notice                   optional warning from the package (PM-KISAN 2020 notice)
unresolved_checks        things this mock cannot check
```

"Deciding rules" means:

- not eligible → the **failed** rules;
- need more information → the **unresolved** rules;
- eligible → **all** rules.

### Our test people through the engine

| Person | Result | Deciding rules | Missing |
|---|---|---|---|
| Sunita (age 50, widow, card) | eligible | all 4 | none |
| Meera (one day short of 40) | not eligible | `IGNWPS-MH-AGE-MIN-01` | none |
| Lata (card not shown) | need more information | `IGNWPS-MH-BPL-01` | `government_bpl_card` |
| Ramesh (paid income tax) | not eligible | `PMKISAN-INCOME-TAX-01` | none |
| Gopal (all clear) | eligible (with 2020 notice) | all 8 | none |
| Kamla (all unknown) | need more information | all 8 | all 8 facts |

### Edge cases for Step 3

| Case | Result | Why |
|---|---|---|
| Empty widow profile | need more information; missing `is_widow`, `date_of_birth`, `application_date`, `government_bpl_card` | Nothing known yet |
| Age exactly 40, or exactly 79 | eligible | Limits are inclusive (`gte` / `lte`) |
| Age 39 (one day short of 40) | not eligible (`AGE-MIN-01`) | Below minimum |
| Age 80 | not eligible (`AGE-MAX-01`) | Above maximum |
| Not a widow **and** no BPL card | not eligible (`WIDOW-01` only); missing list empty | A failure wins over "need proof" |
| Widow, age 50, card **not shown** (`False`) | need more information (`government_bpl_card`) | `if_not_met` turns failure into "show proof" |
| Widow, card shown, only date of birth known | need more information; missing `application_date` only | Only the unknown input is listed, not the known one |
| PM-KISAN: income tax `True`, everything else unknown | not eligible (`INCOME-TAX-01`) | One failure is enough; no need to ask 7 more questions |
| PM-KISAN: no land **and** NRI | not eligible; both rules listed | Every failed rule is reported |
| Widow pension result | `notice` is empty | Only PM-KISAN's package has a notice |

---

## Step 4: How a request travels (API → graph → MCP → engine)

### Hop 1: the API (`src/api/app.py`)

```python
@app.post("/api/v1/journey")
async def journey(journey_request, request):
    return await run_journey(request.app.state.journey_graph, journey_request)
```

At **startup**, the API:

1. loads all rule packages (refuses to start if any are broken);
2. starts the MCP server as a **separate program** and connects to it;
3. builds the journey graph **once** and keeps it for every request;
4. opens the SQLite checkpoint store that remembers each conversation.

There is also `POST /api/v1/schemes/{scheme_id}/evaluate`. It skips the graph
and calls the MCP tool directly. It now works for **both** schemes. The old
PM-KISAN-only route was removed.

### Hop 2: the journey graph (`src/workflow/journey.py`)

The graph is a set of steps (**nodes**) joined by arrows (**edges**):

```
START → orchestrator_agent → intake_agent ──(conditional edge)──► eligibility_agent → END
                                          └─────────────────────► END (stopped early)
```

- A normal **edge** always goes from A to B.
- A **conditional edge** looks at the state, then chooses where to go.

**`orchestrator_agent`** writes a one-line plan. In Phase 2 it becomes a real
supervisor that plans and replans.

**`intake_agent`** is the **gatekeeper**. It runs these checks in order and
stops at the first problem:

| Check | If it fails | Status returned |
|---|---|---|
| 1. Was a scheme chosen? | "Choose a scheme before checking eligibility." | `need_information` |
| 2. Does the scheme have a rule package? | "This scheme is information-only..." | `information_only` |
| 3. Was any profile sent at all? | Lists that scheme's `required_facts` | `need_information` |
| 4. Is the profile valid (`HouseholdProfile`)? | Lists the bad fields | `invalid_input` |
| All passed | continue | `ready_for_eligibility` |

`route_after_intake` sends the request to `eligibility_agent` **only** when
the status is `ready_for_eligibility`. Otherwise the graph ends, and the rule
engine is never called.

**What Phase 1 changed in the graph:**

- Check 2 now finds PM-KISAN, because its JSON is in the shared folder.
- Check 3 lists the facts from the scheme's own `required_facts`. It used to
  be a fixed widow list.
- Check 4 uses `HouseholdProfile`. It used to be a widow-only model that
  rejected PM-KISAN answers.

**`eligibility_agent`** sends the profile to the MCP tool and returns the
verdict.

The **checkpointer** saves the state after each step, keyed by
`conversation_id`. Sending the same ID again continues the same conversation.

### Hop 3: the MCP call (`src/workflow/eligibility.py`)

```python
result = await client.call_tool(
    "evaluate_eligibility",
    {"scheme_id": scheme_id, "profile": profile.model_dump(mode="json")},
)
return EligibilityResponse.model_validate(result.structured_content)
```

The rule tool runs in a **separate program**. The graph cannot read the
rules directly; it can only **ask the tool**. This is called **least
privilege**: each part gets only the access it needs.

**Why check the reply when our own code made it?** The reply crosses a
boundary between two programs as JSON. Like a form that comes back from
another office, it might be broken, from an old version, or half-finished
after a crash. `EligibilityResponse.model_validate` confirms that the reply has
the right fields and types. If it doesn't, we raise an error; we never show a
broken verdict. *Rule: check any data that comes from another program, even
if you wrote that program.*

### Hop 4: the MCP tool (`src/mcp_servers/tools/eligibility.py`)

```python
package = rule_packages.get(scheme_id)
if package is None:
    raise ToolError(f"Unknown scheme: {scheme_id}")
return evaluate_mock_eligibility(profile, package)
```

It looks up the scheme's rules and runs the engine from Step 3.

### Edge cases for Step 4

| Case | What happens |
|---|---|
| No `scheme_id` | `need_information`, missing `scheme_id`; engine not called |
| `scheme_id` with no rules (for example `PMAY-G-IN`) | `information_only`; engine **not** called (a test proves it) |
| Scheme chosen but no `profile` | `need_information`, listing that scheme's required facts |
| Profile with `"maybe"`, a bad date or an unknown field | `invalid_input`, listing the bad fields; engine not called |
| Profile valid but partly empty (`{}` included) | Passes intake; the engine returns `need_more_information` |
| MCP tool crashes or sends a broken reply | API returns HTTP **502** "A journey tool is unavailable"; no verdict shown |
| `/schemes/UNKNOWN/evaluate` | HTTP **404** "Unknown scheme"; MCP not called |
| `/schemes/{id}/evaluate` with date of birth after application date | HTTP **422** (validation error) |
| Same `conversation_id` sent twice | The saved conversation continues; earlier turns are kept |

---

## Step 5: The screen (`src/ui/app.py`)

### How Streamlit works

Every click makes Streamlit **run the whole file again from top to bottom**.
Normal variables are lost on each rerun. To remember things, such as the
result or the conversation ID, we store them in `st.session_state`, a
dictionary that survives reruns.

### Choosing which screen to show

```python
if st.session_state.journey_started:          # you clicked Continue
    if back_button_clicked: ...                # go back to search
    elif scheme_id == "PM-KISAN-IN":           # PM-KISAN form
        ...
        st.stop()                              # draw nothing below this
else:                                          # search screen
    ...
    st.stop()
# below here: the widow pension screen (consent, example person, result)
```

`st.stop()` means "stop drawing here". It is how one file shows different
screens. Without it, the PM-KISAN form would also show the widow-pension screen
underneath.

### The PM-KISAN form

```python
answers[field_name] = {"Unknown": None, "No": False, "Yes": True}[answer]
```

This turns the drop-down choice into the exact values `HouseholdProfile`
expects. "Unknown" becomes `None`, so "not known" reaches the engine.

### The call: the main Phase 1 change on screen

```python
journey = run_journey(JourneyRequest(
    action="evaluate",
    conversation_id=<the saved ID, or a new one>,
    scheme_id="PM-KISAN-IN",
    profile=answers,
))
```

- **Before:** PM-KISAN called its own route and skipped the graph and MCP.
- **Now:** it uses the same `run_journey` as widow pension.
- The **same `conversation_id`** is reused, so the backend sees one
  conversation, not a new stranger each time. Phase 2 depends on this for the
  chat.

### Showing the result

- The verdict is saved in `st.session_state.pmkisan_eligibility_result`.
- The screen shows:
  - the verdict (green eligible, red not eligible, yellow need more
    information);
  - the reason;
  - the notice, **only if** the package has one;
  - the unknown answers and what this mock cannot check;
  - one expandable box per deciding rule, with source text, location and
    link.
- If the graph stopped early (for example `invalid_input`), there is no
  result, so the graph's message is shown as an error instead.

Widow pension still uses the example-person screen: consent → choose an
example → check → draft → approve → mock submit. That is unchanged.

### Edge cases for Step 5

| Case | What the user sees |
|---|---|
| API not running | "Could not reach the journey API. Start the API and try again." |
| API returns an error (502) | "The journey API returned HTTP 502." |
| Graph stopped early (no result) | The graph's message, shown as an error |
| All PM-KISAN answers "Unknown" | Yellow "check the answers"; list of 8 unknown answers |
| Back button | Clears the chosen scheme, conversation ID and results; returns to search |
| Widow pension result | No notice box (that package has no notice) |

---

## How Phase 1 is tested

Run the whole suite from the repository folder:

```powershell
cd C:\Users\Admin\OneDrive\Documents\Saathi\scheme-saathi-capstone
..\venv\Scripts\python.exe -m pytest -q
```

Expected: **99 passed**.

| Test file | What it proves |
|---|---|
| `tests/test_api_eligibility.py` | Age limits, BPL card, not-a-widow, evidence, unknown scheme (404), bad dates (422), PM-KISAN exclusions, eligible, missing land, unknowns, **PM-KISAN through the journey graph and MCP** |
| `tests/test_ui_fixtures.py` | Rule-file mistakes are rejected, and **both schemes load from one registry** |
| `tests/test_journey_graph.py` | Graph routing, information-only schemes never call the engine, missing profile, conversation memory |
| `tests/test_ui_app.py` | Search → Continue → check works on screen for **both** schemes using the journey API |
| `tests/test_workflow_state.py` | Phase 2 contracts: helpers can only talk to the supervisor; a changed plan must give a reason |

### Try it yourself in Python

```python
from datetime import date
from src.rules.models import HouseholdProfile
from src.rules.data_provider import RulePackageProvider
from src.api.eligibility import evaluate_mock_eligibility

pkg = RulePackageProvider().get("IGNWPS-MH")
lata = HouseholdProfile(
    is_widow=True,
    date_of_birth=date(1976, 10, 30),
    application_date=date(2026, 10, 30),
    bpl_card_shown=False,
)
r = evaluate_mock_eligibility(lata, pkg)
print(r.result, r.deciding_rule_ids, r.missing_fields)
# need_more_information ['IGNWPS-MH-BPL-01'] ['government_bpl_card']
```

### Manual UI test checklist

- [ ] Widow pension: search, choose IGNWPS-MH, Continue, consent, check. The
      result matches the old one.
- [ ] Widow pension: prepare draft → approve → submit to mock portal still
      works.
- [ ] PM-KISAN: land "Yes" and every exclusion "No" → eligible, with the 2020
      notice.
- [ ] PM-KISAN: income tax "Yes" → not eligible with
      `PMKISAN-INCOME-TAX-01`.
- [ ] PM-KISAN: leave answers "Unknown" → need more information, listing
      them.

---

## Phase 2 contracts added (not used yet)

`src/workflow/state.py` defines the shapes the supervisor and specialists
will use in Phase 2:

| Contract | Meaning | Safety rule |
|---|---|---|
| `PlanStep` | One step, owned by one specialist (intake, search, eligibility, documents, application) | Unique step IDs |
| `Plan` | The visible checklist, with a version number | A version above 1 **must** say why it changed (`replan_reason`) |
| `CandidateVerdict` | The verdict for one candidate scheme | Typed result values only |
| `Handoff` | A message between the supervisor and a specialist | Specialists may only talk to the supervisor, never to each other |

---

## Files changed in Phase 1

| File | Change |
|---|---|
| `src/rules/models.py` | Rewritten: `HouseholdProfile` and a generic `Rule` / `RulePackage` |
| `src/rules/packages/ignwps_mh.v1.json` | Converted to the shared format (`required_facts`, `reasons`, BPL `if_not_met`) |
| `src/rules/packages/pmkisan_in.v1.json` | **New location**; converted to the shared format |
| `src/api/eligibility.py` | One generic engine for every scheme |
| `src/api/app.py` | PM-KISAN-only route removed; the generic route serves every scheme |
| `src/mcp_servers/tools/eligibility.py`, `src/workflow/eligibility.py`, `src/workflow/journey.py` | Use `HouseholdProfile` and package `required_facts` |
| `src/ui/api_client.py`, `src/ui/app.py` | PM-KISAN goes through `run_journey` |
| `src/workflow/state.py` | **New**: Phase 2 contracts |
| Removed | `src/api/pmkisan_eligibility.py`, `src/rules/pmkisan/` |
| Tests | Updated for the new format, plus new tests for the shared path and contracts |

---

## Key lessons

1. **Rules are data, not code.** A new scheme means a new JSON file.
2. **"Not known" is not "no".** `None` leads to a question, never to a
   rejection.
3. **Calculate, don't store,** values that come from other values (age).
4. **Fail early and loudly.** Broken rule files stop the app at startup; bad
   input stops at intake.
5. **A failure wins.** Once one rule fails, stop asking questions.
6. **Check data that crosses between programs,** even your own.
7. **Least privilege.** The graph asks the MCP tool; it never reads the rules
   itself.
8. **The AI never decides eligibility.** The engine is plain code.
