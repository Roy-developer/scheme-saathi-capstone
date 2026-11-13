# E3 freeze proposal (draft for Role 5 review), 2026-11-13

Status: DRAFT PROPOSAL. Not applied. `eval/freeze/manifest.json` is unchanged. No paid or model calls were made. No held-out data was read.

Scope: E3 ("Did the Reflexion lessons help?") measures extraction exact-match on development check-split cases, before and after playbook 1.0.0. Source: `eval/experiments/e3_playbook.json`.

## (a) Exact E3 pins proposed for freeze

| Pin | Proposed value | Source / how verified |
|---|---|---|
| Model ID | `nvidia/nemotron-3.5-lightning:free` | Default of `DEFAULT_EXTRACTION_MODEL` in `src/rule_extraction_reflexion/scheme_rules.py` (line 88). Supplied by env var **`OPENROUTER_RULE_EXTRACTION_MODEL`** (name only; if unset, the default applies). Value of the env var not read. |
| Prompt identifier | **None exists.** The prompt is an unnamed constant, `EXTRACTION_SYSTEM_PROMPT`, in `src/rule_extraction_reflexion/extractor.py` (line 43). It has no version ID and no hash entry in the manifest. Proposal: pin its SHA-256 over the Python string value as a new `prompts` entry, e.g. `extraction.system.v1`. The hash method still needs to be defined by Role 5 or the team. |
| Playbook version | `1.0.0` (`data/schemes/playbooks/1.0.0.json`) | `e3_playbook.json` and file `version` field. |
| Playbook content hash | `a60303d5a255b5abef4dfd896c8dae0bba6c16488cea4b8de0157c2f69ee1401` | Recomputed read-only and matches `content_hash` in the file and in `e3_playbook.json`. Method (`playbook_hash` in `src/rule_extraction_reflexion/playbook.py`): SHA-256 of UTF-8 JSON of `{"version": ..., "lessons": [...]}`, with `sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`. |
| Playbook file SHA-256 (bytes) | `cb1b56b223da68b1e97451543fb64cf2c099834c9b45ced8f792553e79045c1c` | `sha256sum` over the file bytes. Optional extra pin. |
| Case file | `data/schemes/rule_extraction_cases_dev.json` | SHA-256 over file bytes: `6bfac007e47eb63afb54766b180a880bdc941b7240bdcbdc38f2cea416f0d9d0`. |
| Split definition | `split == "check"` (6 cases) | Filter in `build_cases` (`scheme_rules.py`, line 112). Case IDs (`clause_id`): see below. |

Check-split case IDs (6):
1. `PMKISAN-GUIDELINES-2020-3` (pmkisan_in.v1.json)
2. `PMKISAN-GUIDELINES-2020-4.1(b)(iv)` (pmkisan_in.v1.json)
3. `PMKISAN-GUIDELINES-2020-4.1(b)(v)` (pmkisan_in.v1.json)
4. `PMKISAN-GUIDELINES-2020-4.1(b)(vi)` (pmkisan_in.v1.json)
5. `IGNWPS-MH-ELIGIBILITY-01` (ignwps_mh.v1.json)
6. `IGNOAPS-MH-ELIGIBILITY-01` (ignoaps_mh.v1.json)

Also in scope for the freeze: the lesson `3dae54216ec572a646f95287aec6b113f1d088c8f147032f690651dd542f1e32` (tag `exclusion_clause`). Note from `e3_playbook.json`: it will not apply to the inclusion-clause check cases (IGNWPS, IGNOAPS). The 6 check cases carry `topic_tags`: `inclusion_clause` for PMKISAN-GUIDELINES-2020-3, IGNWPS-MH-ELIGIBILITY-01 and IGNOAPS-MH-ELIGIBILITY-01 (3 cases); `exclusion_clause` for PMKISAN-GUIDELINES-2020-4.1(b)(iv), (v) and (vi) (3 cases).

Run settings to freeze with the pins: `--runs 3`, `--split check`, `--playbook 1.0.0`, same model and prompt for before and after arms.

## (b) What Role 5 must confirm

1. The model ID to freeze is the extraction model (`OPENROUTER_RULE_EXTRACTION_MODEL`, default Nemotron free route), not the chat model `openai/gpt-4o-mini`. Confirm this is the intended E3 model.
2. A named version and SHA-256 hash for `EXTRACTION_SYSTEM_PROMPT`, and the hashing method for it.
3. The playbook pins: `1.0.0`, content hash `a6030...1401`, and the file-bytes hash.
4. The case file hash `6bfac007...d0` and the split definition (`split == "check"`, 6 cases above). Confirm no `split` None entry (1 case has no split) is in scope.
5. That the held-out extraction set stays untouched. This proposal does not read `eval/held_out/` or `data/heldout/`.
6. That the E3 claim is development-only (`eval_set: development_check_until_held_out_authorized`).
7. The rule-package pins for the 5 packages used by the check cases (`package_sha256` in the case file and `rule_packages.sha256` in the manifest) match. Not verified in this pass.

## (c) Stale or conflicting existing manifest entries

| Manifest field | Current value | Problem | Proposed change |
|---|---|---|---|
| `model.chat_model` | `openai/gpt-4o-mini` | This is the chat model (`DEFAULT_CHAT_MODEL` in `src/llm_client.py`). It is not the E3 extraction model. A reader could mistake it for the E3 model. | Keep for chat. Add a separate `extraction_model` block (see d). Do not use it for E3. |
| `model.chat_model_env_override` | `OPENROUTER_CHAT_MODEL` | Correct for chat. Does not cover extraction. | No change. |
| `playbook.path` | `data/schemes/rule_extractor_playbook.json` | Points at a different file from the one E3 uses. E3 uses `data/schemes/playbooks/1.0.0.json`. | Change to `data/schemes/playbooks/1.0.0.json`, or add a new `e3_playbook` block. |
| `playbook.sha256` | `6543e8ca4cae008d8d79cc64fb72eb7669be17e894ec89d15d91f3cc8d4e07e7` | Does not match the current file at `rule_extractor_playbook.json`, whose SHA-256 is `37dc729fddd07cf4653729f1e8d077693d53885a44959af1f2493fe0eb464a68`. It also does not match the E3 playbook (`a6030...`, content hash). Stale. | Set to the E3 playbook file hash or content hash, with the matching path. Decide which hash method to use. |
| `prompts.prompt_version` and `prompts.entries` | `scheme-saathi-phase4-v1`; entries for application, documents, eligibility, intake, single, supervisor (en/hi/mr) | None of these cover the extraction prompt. The E3 prompt is missing. | Add a new `extraction` entry (see d). Do not change existing entries. |
| `purpose` | "Phase 5 evaluation freeze pins (offline). Not an authorization for paid runs." | Correct. | No change. |
| `paid_runs.status` | `BLOCKED` | Still blocked. E3 needs paid OpenRouter runs. | Keep `BLOCKED` until explicit approval is recorded outside the manifest. |
| `approval.restricted_run_gate.authorised` | `conditional` | Requires threshold sign-offs in the threshold decisions file. Only Roy-developer has signed (`thresholds_status`). | Keep. Do not change without sign-offs. |
| `approval.approver_role` | "to be confirmed in review" | Freeze owner not confirmed. | Role 5 to confirm. |

Other items not checked: `rule_packages.sha256` (5 packages) and `attack_suite` hash against files on disk.

## (d) Proposed manifest block (snippet for proposal only; not written to the manifest)

```json
{
  "e3_extraction_freeze": {
    "experiment_id": "E3",
    "status": "proposed_pending_role5_review",
    "extraction_model": {
      "model_id": "nvidia/nemotron-3.5-lightning:free",
      "env_override": "OPENROUTER_RULE_EXTRACTION_MODEL",
      "source": "src/rule_extraction_reflexion/scheme_rules.py DEFAULT_EXTRACTION_MODEL"
    },
    "extraction_prompt": {
      "identifier": "extraction.system.v1",
      "source": "src/rule_extraction_reflexion/extractor.py EXTRACTION_SYSTEM_PROMPT",
      "sha256": "<TO BE COMPUTED AND REVIEWED: hash method not yet defined>"
    },
    "playbook": {
      "path": "data/schemes/playbooks/1.0.0.json",
      "version": "1.0.0",
      "content_hash": "a60303d5a255b5abef4dfd896c8dae0bba6c16488cea4b8de0157c2f69ee1401",
      "content_hash_method": "sha256 of UTF-8 canonical JSON {version, lessons}, sort_keys, separators (',',':'), ensure_ascii=False",
      "file_sha256": "cb1b56b223da68b1e97451543fb64cf2c099834c9b45ced8f792553e79045c1c"
    },
    "case_file": {
      "path": "data/schemes/rule_extraction_cases_dev.json",
      "sha256": "6bfac007e47eb63afb54766b180a880bdc941b7240bdcbdc38f2cea416f0d9d0"
    },
    "split": {
      "field": "split",
      "value": "check",
      "case_ids": [
        "PMKISAN-GUIDELINES-2020-3",
        "PMKISAN-GUIDELINES-2020-4.1(b)(iv)",
        "PMKISAN-GUIDELINES-2020-4.1(b)(v)",
        "PMKISAN-GUIDELINES-2020-4.1(b)(vi)",
        "IGNWPS-MH-ELIGIBILITY-01",
        "IGNOAPS-MH-ELIGIBILITY-01"
      ]
    },
    "runs": 3,
    "paid_runs": "BLOCKED until explicit human approval recorded outside this manifest"
  }
}
```

## (e) Approvals required and from whom

1. Role 5 (freeze owner): review and confirm items (b) 1-7. The manifest says the freeze owner is "to be confirmed in review."
2. Project lead (Roy-developer): approves the frozen configuration and the budget cap. Recorded 2026-11-12 as `approved_by_project_lead`. Re-approval is needed if the pins change, because the approval covers the frozen configuration.
3. Threshold owners other than Roy-developer: still to sign, per `approval.thresholds_status`. Required before any restricted run.
4. Explicit human approval for paid runs: recorded outside the manifest (`paid_runs.requires`). Current status: BLOCKED.
5. Held-out extraction set: Role 5 only. Not in scope for this proposal.
6. Playbook lesson reviewer: Roy-developer (lesson `3dae5...1e32`). Already recorded in the playbook.
