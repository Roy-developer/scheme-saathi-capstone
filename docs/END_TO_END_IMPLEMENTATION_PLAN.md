# Scheme Saathi: one complete user journey

> **This is a proposal for the team to discuss.** It is not an approved policy,
> a final design, or a list of assigned people. Agree the scheme, policy,
> owners, and dates together before building against it.

## The idea in one sentence

Help a person check one possible welfare scheme, understand the result, and
review a **mock** application—without letting AI decide eligibility or sending
anything to a real government service.

## What we have now

- A Streamlit screen that shows a synthetic scheme example.
- A small FastAPI service that reports health and version information.
- Seven made-up examples for the Maharashtra widow-pension scheme.
- A demo showing that changing a form changes its fingerprint.

**What we do not have yet:** the real backend journey, scheme search, rule
evaluation, question asking, secure approval, mock submission, or restart and
forget behavior. The current scheme rules are still marked as a draft for
review. Its document requirements are not verified.

## Picture the journey

```text
 PERSON
   |
   v
 "I want to learn about widow pension"
   |
   v
 SAATHI shows the scheme and its official source
   |
   v
 SAATHI asks only the facts needed for the rules
   |
   v
 RULE CHECKER (ordinary code, not AI)
   |
   +---- A fact is missing ------> Ask a question; show "Need more information"
   |
   +---- A rule is not met ------> Explain why; do not make an application
   |
   +---- All reviewed rules pass -> Show a clearly marked MOCK form
                                       |
                                       v
                               Person checks the form
                                  /           \
                              edits            approves
                                |                 |
                          approval clears        v
                                          MOCK PORTAL only
                                                  |
                                                  v
                                      Show mock receipt/status
```

The AI can help understand a request and explain the result. **It cannot make
the eligibility decision.** A tested rule checker makes that decision and
shows which official rule it used.

## What the person experiences

| What the person does | What Saathi should do |
|---|---|
| Starts the demo | Clearly say this is a synthetic demonstration, not a government decision or real application. |
| Asks about widow pension in Maharashtra | Show the candidate scheme and its official source. |
| Answers questions about age, widow status, and BPL status | Ask only for information that could change the result. Do not ask for Aadhaar, bank details, or uploads in the first version. |
| Has not confirmed BPL status | Say **“We need more information”** and ask about BPL status. Do not guess. |
| Meets or does not meet the reviewed rules | Explain which rule led to the result and link to the source. |
| Asks about documents | Say that the requirements have not been verified yet. Do not invent a list. |
| Qualifies in the synthetic demo | See and check a form clearly labelled **MOCK — NOT SUBMITTED**. |
| Changes the form | The old approval is cleared; the person must review the changed form again. |
| Approves the unchanged form | Send it only to the mock portal and show a mock receipt. Never submit to a real portal. |
| Leaves and returns, or chooses “forget” | Resume the synthetic demo or clear its saved state. Do not store real personal information. |

The first example can use the existing synthetic case where BPL status is
unknown. A second run can use the eligible synthetic example to show the mock
form and approval. Role 1 must review the draft scheme interpretation before
the team describes these results as policy-correct.

## How all six roles contribute

The role numbers below come from the project brief. **The repository does not
name the role owners yet.** The team should fill in owners and backups together.

| Role | In everyday language | What this role gives the next role |
|---|---|---|
| **1. Domain and product** | Checks what the scheme really says and what we should tell people. | Reviewed scheme rules, official source, unclear points, and example cases. |
| **2. Knowledge and memory** | Makes official scheme information easy to find and cite. | A source passage with its link, date, and identifier. |
| **3. Agents and orchestration** | Connects the steps of the conversation. | A flow that gathers facts, calls the right services, and explains their result. |
| **4. Tools, control and security** | Builds safe, limited tools and protects approval. | A rule-checking tool, a mock portal, and controls that prevent unsafe submission. |
| **5. Evaluation and red-team** | Checks answers independently and tries to find failures. | Test examples and attack checks kept separate from the people tuning the system. |
| **6. Deployment and operations** | Makes the whole thing easy to run and check. | A local run command, health checks, automated tests, and later deployment. |

## Build it in this order

Each step should work before the team builds on top of it. Some roles can work
in parallel once the team agrees what they are exchanging.

### 1. Agree on the demo

Together, decide:

- Is the widow-pension example the right first journey?
- What should the demo show, and what must it clearly say it cannot do?
- Who owns each role, and who is the backup?
- Which policy questions still need an answer?

**Done when:** everyone can describe the same demo and its limits.

### 2. Check the scheme information

- **Role 1** checks the official page and the meaning of each eligibility rule.
- **Role 2** makes the page and relevant passage findable, keeping the source
  link and collection date.
- **Role 5** prepares small expected-answer examples before implementation
  tuning begins.

**Done when:** each test example has a reviewed answer or is clearly marked
uncertain. Keep future held-out tests away from the builders.

### 3. Agree on what services exchange

The UI, API, rule checker, and other tools need to agree on the shape of the
information they send each other. Decide this together; this plan does not
freeze those formats.

At minimum, agree how to represent:

- a person's answers, including answers not yet known;
- a scheme rule and where that rule came from;
- the result, the reason, and any missing information;
- a form, its approval, and errors;
- service addresses and health checks.

**Done when:** the roles that build and test these pieces have reviewed the
same examples and interfaces.

### 4. Make the rule checker

- **Role 4** builds the plain-code checker.
- **Role 1** checks the rule meaning.
- **Role 2** supplies source references.
- **Role 5** checks the answers against its prewritten examples.

The checker must return one of: **eligible**, **not eligible**, or **need more
information**. It must show the source. Unknown facts must not be treated as
“no.”

**Done when:** the same answers always give the same result, and each result
can be checked against a source.

### 5. Connect the conversation

- **Role 3** connects the questions, source lookup, and rule checker.
- **Role 4** limits which tools the conversation can use.
- **Role 5** checks that the system asks useful questions and handles unsafe
  requests.

For example, if BPL status is unknown, the system asks about it. It does not
guess and does not claim eligibility yet.

**Done when:** one synthetic case can be entered, checked, and explained
without changing the rule checker's answer.

### 6. Connect the screen

- **Role 6** connects the existing Streamlit screen to the API.
- Keep conversation state in the backend, not only in the browser screen.
- Show the result, missing facts, and source in English, Hindi, or Marathi.

**Done when:** a teammate can run it on their computer and complete the
synthetic check without Azure access.

### 7. Add the mock form and approval

- **Role 4** protects the approval and mock submission.
- **Role 3** connects the conversation to these tools.
- **Role 6** makes the flow run and retain only the needed demo state.
- **Role 5** tests edits, repeated submits, and attempts to bypass approval.

An approval must apply to the exact form shown. If any field changes, ask the
person to review and approve again. A mock receipt is the end of this demo;
there is no real submission.

**Done when:** only an unchanged, explicitly approved synthetic form can reach
the mock portal.

### 8. Test the whole journey and make it easy to run

- **Role 5** tests expected answers, citations, unsafe requests, and failures.
- **Role 6** provides one local startup command, service health checks, and CI.
- **Role 4** checks that unsafe tool calls and unapproved submissions are
  blocked.
- All roles review their own part and help with the demo walkthrough.

Later, after the local version works, the team can decide on dashboards,
broader evaluation, Docker Compose, and Azure deployment.

**Done when:** a teammate can start the system, run the journey, see the
evidence, test approval invalidation, and explain what is still only a mock.

## Team decisions still needed

Write down the team's answers; do not assume this proposal has settled them.

1. Do we agree to use this scheme and journey first?
2. Who owns each of the six roles, and who is each backup?
3. Has Role 1 checked the scheme rules and source?
4. Which small examples will Role 5 use for development testing?
5. Which service interfaces do the relevant roles agree on?
6. What is required for the first demo, and what can wait?
7. What are the dates and completion checks?

## Final demo checklist

- [ ] The user sees the synthetic-demo warning.
- [ ] The source and its date are shown.
- [ ] Missing information leads to a question, not a guess.
- [ ] A plain-code rule checker decides eligibility.
- [ ] Each result shows its reason and source.
- [ ] The same case gets the same result in all supported languages.
- [ ] Unverified document requirements are not invented.
- [ ] Editing the form clears its previous approval.
- [ ] Only an unchanged, approved form can reach the mock portal.
- [ ] No real person data is stored or submitted.
- [ ] Another teammate can start and test the journey.
