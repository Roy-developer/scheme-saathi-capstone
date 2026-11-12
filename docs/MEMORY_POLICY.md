# Household memory policy

**Version:** 1.0.0  
**Status:** Prototype policy; 90-day retention is a conservative implementation
default pending R1/R2 approval.  
**Scope:** Synthetic demonstration data only. Do not enter real applicant data.

## What is stored and why

When a user explicitly opts in and chooses **Save my answers**, the return-code
store may retain known facts for the purpose of pre-filling a later synthetic
eligibility interview. It stores the typed fact payload, fact IDs, locale,
consent/policy version, and creation/update/expiry timestamps.

Only facts with approved definition and privacy reviews are eligible. Unknown
and declined values, derived facts, facts with pending reviews, and
`highly_sensitive` facts are excluded. The current registry marks date of birth
and widow status as highly sensitive, so they are not saved. Other sensitive
facts are retained only after the separate memory-consent action.

## Consent, expiry, correction, and deletion

- Demonstration consent is not memory consent. A separate, unchecked-by-default
  consent control is required to load or save a return-code profile.
- Memory consent is recorded with its grant time and this policy version.
- The prototype expires a saved record after 90 days. The value is provisional
  until R1/R2 approve the retention period.
- A user may update an existing profile by explicitly saving again. The current
  save replaces the known eligible facts; it does not merge unreviewed facts.
- The UI's **Forget my data** action sends one request to delete both journey
  data and household memory. If one store fails, the API reports an incomplete
  deletion and the action can be retried; a retry is safe if some records were
  already deleted.

## Legacy and migration behavior

Records without current consent, policy version, allowed fact IDs, or a valid
future expiry are rejected and deleted on access. There is no implicit
grandfathering of older return-code records.

## Active journey state

The active graph state retains at most 40 recent conversation turns and 40
recent agent handoffs, alongside separately bounded trace events. This limits
the current state used by the workflow; it does not prune historical SQLite
checkpoints created before the current state update. The whole conversation's
checkpoints are removed by the forget action. Checkpoint-level retention and
pruning remain to be verified before any stronger retention claim.

## Review required

R1/R2 must approve the privacy-filtered fact set, consent language, 90-day
retention, and correction/deletion behavior before this prototype policy is
treated as an approved product policy or used with real applicant data.
