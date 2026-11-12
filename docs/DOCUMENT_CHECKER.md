# Document uploads and Document checker

Status: built and tested locally. **Not committed, pushed or deployed.**
Data rule: synthetic data only. Never upload real identity documents.

## Why we are doing this

The interview tells a citizen which schemes they may be eligible for and which
documents they need. Before this feature, the app only let people tick
"available" on a checklist. Nothing showed whether the right file existed, or
whether the name and date of birth on the document matched the profile.
Mismatches are a common reason applications are returned.

Goals:
- Let people attach one file per required document (PDF, JPG or PNG, max 20 MB).
- Warn early when the typed details do not match the profile.
- Let a human resolve each warning and sign it off.
- Show scheme readiness even when only some documents are present.

## What it does

### Upload documents tab
- One uploader per required document. Uploading marks the document `available`.
- Files are stored on the backend disk under
  `<upload dir>/<conversation>/<document_id>/<uuid>.<ext>`, with a sha256 hash.
- Replacing or removing a file clears everything tied to the old file.
- The backend accepts only PDF/JPG/PNG and rejects files over 20 MB (HTTP 413).

### Document checker tab
A deterministic checker (no AI) compares the name and date of birth typed for
each document with the profile.

| Code | Meaning | How it is fixed |
|---|---|---|
| `name_mismatch` | Typed name differs from profile | Human acknowledges, or correct the value |
| `date_of_birth_mismatch` | Typed date differs from profile | Same |
| `cannot_compare` | A value is missing | Same |
| `file_problem` | File unreadable or invalid | Upload a new file |
| `no_file` | No file uploaded | Upload a file |
| `same_file_reused` | One file attached to two documents of the same scheme | Human acknowledges, or upload the right file |
| `file_name_mismatch` | Name read from the file differs from profile | Human acknowledges, or upload the right file |
| `file_date_of_birth_mismatch` | Date read from the file differs from profile | Same |

- **Resolve:** a person can acknowledge a warning (with a note) or reopen it.
  The acknowledgment is tied to a fingerprint of the file hash, typed values,
  profile name and checklist. Any change voids it.
- **Reviewer sign-off:** a reviewer can sign off a document. It is keyed to the
  file hash, so replacing the file voids it.
- **Mode (citizen or CSC):** records who acted. A citizen uses the app for their
  own household. A CSC (Common Service Centre) operator acts on someone's
  behalf. It does not change eligibility.
- **Readiness:** the "Show document readiness" button summarises each scheme as
  ready or what is still missing, including with partial documents.

### Optional: suggested values from the file (LLM reading)
- Off unless a reader is configured. **Azure Document Intelligence** in our own tenant
  (`SCHEME_SAATHI_DOCINTEL_ENDPOINT` and `..._KEY`) is preferred.
- The **OpenRouter vision model** (default `nvidia/nemotron-3.5-super-vl:free`, change with
  `OPENROUTER_VISION_MODEL`) is used only when switched on explicitly with
  `SCHEME_SAATHI_VISION_READER=openrouter`. An OpenRouter key alone no longer turns it on,
  because it sends the whole, unmasked image to an outside provider: an ID number in an
  image is pixels, so text masking cannot remove it first. Use it with synthetic documents
  only. It reads only **JPG or PNG**; PDFs must be typed.
- Either way, the reader only transcribes. The transcript is masked with
  `mask_sensitive_text` (Aadhaar, phone, email, account numbers), then plain code picks the
  values that sit next to a "Name" or "DOB" label.
- Free models may log prompts: synthetic documents only.
- "Read name and date from file" shows a suggestion. The user must press Accept
  to copy it into the fields. It never fills them silently.
- Suggestions apply only while the file hash is unchanged.
- **Validation against the profile:** once a suggestion exists, the checker also compares
  the values read from the file with the confirmed profile. A difference gives
  `file_name_mismatch` or `file_date_of_birth_mismatch` (acknowledgeable; voided if the
  file or the values read change). No suggestion means no extra warning.

### After submission: under review, then human review
- When a draft is submitted to the mock portal, the app shows **Under review**
  with the checker and reviewer sign-off below it. The tabs themselves are only
  shown before a draft exists.
- The checker reuses the answers last saved for the scheme (the backend keeps
  them), so no form is needed.
- When every uploaded document is signed off and the overall result is
  `complete` or `complete_with_acknowledged_warnings`, the message changes to
  **Human review complete**.
- Review is advisory. Nothing forces it before submission.
- **Where the reviewer sees the files:** under each document, tick "View uploaded
  file". Images are shown inline; PDFs show a note and a Download button. The file
  is fetched only when ticked, from
  `GET /api/v1/journey/{id}/documents/files/{document_id}/content`, which checks
  the stored hash and sends `nosniff` and `no-store`. The server path is never
  exposed. **Reviewer access code:** set the env var
  `SCHEME_SAATHI_REVIEWER_CODE` (on Azure, as a Container App secret) and the
  file content route and reviewer sign-off/undo require the header
  `X-Reviewer-Code` (compared in constant time; 403 otherwise). The checker tab
  then shows a "Reviewer access code" box, and files and sign-off stay hidden
  until it is entered. If the variable is unset, everything is open (local demo
  mode). This is one shared code, not per-person login, and the name a reviewer
  types is still self-declared. Review stays optional by design: it happens after
  submission and does not block the draft.
- **Rejected draft:** the application summary stays visible, with the rejection
  message and "Edit and reopen draft". The checker and "View uploaded file" are
  shown below it so the files can still be opened.

## All cases

### Upload
| Case | Result |
|---|---|
| PDF, JPG or PNG up to 20 MB | Stored; document marked `available` |
| Other file type | Rejected (HTTP 415) |
| File over 20 MB | Rejected (HTTP 413), also while streaming |
| Empty file | Rejected |
| Unknown document id | Rejected (HTTP 404) |
| Unknown conversation | HTTP 404 |
| Replace a file | Old file removed; resolutions, suggestion and review for it void |
| Remove a file | File and everything tied to it deleted |
| Same file used for two documents of one scheme | `same_file_reused` warning on both; acknowledgeable |
| File changed or missing on disk | `file_problem`; viewing it returns HTTP 409 (hash mismatch) or 404 |
| Reviewer views a file | Image inline, PDF by download; fetched only when ticked |

### Checker issues
| Case | Result |
|---|---|
| Typed name differs from profile | `name_mismatch`; acknowledgeable |
| Typed date differs from profile | `date_of_birth_mismatch`; acknowledgeable |
| Value missing, cannot compare | `cannot_compare`; acknowledgeable |
| File unreadable | `file_problem`; upload a new file |
| No file | `no_file`; upload a file |
| Acknowledge with a note (3+ characters) | Issue shows acknowledged |
| Reopen an acknowledgment | Issue is unresolved again |
| File, typed values, profile name or checklist changes | Acknowledgment voided |

### Overall result
| Overall | Meaning |
|---|---|
| `complete` | All applicable requirements in place |
| `complete_with_acknowledged_warnings` | In place, with acknowledged warnings |
| `needs_attention` | An open warning, file problem or unknown condition |
| `incomplete` | A required document is missing |
| `requirements_unverified` | Checklist not usable; nothing is claimed |

### Readiness (per scheme)
`ready` (complete or acknowledged), `partial` (some in place or needs
attention), `none` (nothing in place). Eligibility is shown beside it,
unchanged.

### Reviewer sign-off
| Case | Result |
|---|---|
| No file uploaded | Sign-off refused (HTTP 404) |
| Reviewer name (2+ characters) with optional note | Recorded with time |
| Remove review | Cleared |
| File replaced | Sign-off voided |

### Suggested values (OCR)
| Case | Result |
|---|---|
| Azure not configured | Button hidden; extract returns 503 |
| No file stored | Refused |
| Nothing readable | "No name or date could be read" |
| Name or date found | Shown; applied only after Accept |
| File replaced | Suggestion dropped |

### Draft and submission
| Case | Result |
|---|---|
| Checklist complete | "Prepare synthetic draft" available (checker is not a gate) |
| Checklist incomplete | Draft button not shown |
| Draft rejected | "Rejected" message; can reopen |
| Draft stale | Reload the checklist; the Upload and Document checker tabs are shown there too |
| Submitted | Receipt, then **Under review** |

All checker text exists in English, Hindi and Marathi.

## Sync with the backend and what is not disrupted

- All logic lives in the FastAPI backend under
  `/api/v1/journey/{conversation_id}/documents/...`. The Streamlit UI only calls
  those routes through `src/ui/api_client.py`, so UI and backend share one
  source of truth.
- Eligibility, the interview and the existing draft flow are unchanged. The
  draft flow still requires `checklist_complete`. The checker adds no new gate
  and cannot make a draft possible when documents are missing.
- Forgetting a conversation also deletes its files, resolutions, suggestions and
  reviews.
- The uploads database and directory are included in the existing backup to the
  Azure file share.
- Existing tests were changed only to mock the new file-list call.

## Gaps and limits

1. **No proof of genuineness.** The checker does not verify a document is real
   or government-issued. That needs DigiLocker, Aadhaar secure QR or government
   APIs, which involve real personal data and are out of scope. Human review is
   the validation method for now.
2. **LLM reading is only lightly tested.** On synthetic samples the free Nemotron VL model
   read English well and Hindi mostly well (a few wrong characters). On a Marathi sample it
   misread a surname and a year (`शिंदे` as `शेडे`, 1958 as 1986), which would raise a false
   mismatch. Always check a suggestion against the file before accepting it. A larger image
   did not fix it. Other free vision models were tried and none worked: the Gemma 4 models
   returned 429 rate limits, `nemotron-3-nano-omni` was very slow and returned nothing, and
   `inkling-2-small` is blocked outside agentic harnesses. The Azure call has also never run
   against the real service.
3. **Only name and date of birth** are compared, and only when a label sits next
   to the value.
4. **Possible loss of recent uploads.** The backend scales to zero and backup
   runs about every 5 minutes, so up to about 5 minutes of uploads can be lost.
   Run a single replica, since files live on its disk.
5. **No malware scanning or retention policy** for uploaded files.
6. **Compliance:** no sign-off yet on keeping extracted text.
7. **Not yet verified:** a clean full test-suite run after the OCR and sign-off
   work (recent runs hung and were stopped), and a manual browser pass. One
   earlier failure,
   `test_new_clause_is_added_to_the_cases_file_and_flagged_for_a_split`, was
   already failing before this work.
8. **Skipped:** an info note in the checker when the confirmed value differs
   from the OCR suggestion.

## Where to see it locally

Run `.venv\Scripts\python.exe -m src.run_services`. UI: http://127.0.0.1:8501,
API: http://127.0.0.1:8000. Complete an interview to an eligible result
(IGNOAPS-MH is easiest), click "Load demo document checklist", then use the
"Upload documents" and "Document checker" tabs.

## Deployment (when approved)

Commit and push, pass the GitHub Actions checks for that commit, then redeploy
the frontend and backend Container Apps with the backend at one replica.
Role 6 (Deployment and operations engineer) is still TBD in the README.
