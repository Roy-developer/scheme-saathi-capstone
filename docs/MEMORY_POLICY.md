# Household memory policy

**Version:** 1.0.0  
**Status:** Prototype policy; the project approver selected 90-day retention for
consented return-code memory on 2026-11-12.
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
- A saved return-code memory expires after 90 days, as approved by the project
  approver on 2026-11-12.
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
checkpoints created before the current state update. The project approver
selected no automatic expiry for historical SQLite journey/checkpoint data on
2026-11-12. Checkpoints remain until explicitly forgotten; the forget action
removes the conversation's live checkpoint thread.

**Backup deletion:** with backups enabled, the API records a pending deletion
on the configured share before changing live records and refreshes the current
backups before returning 204. A failed refresh returns 503 and retains the
marker; startup replays pending deletions before serving. In-process API
requests wait while deletion runs, preventing concurrent requests from
reintroducing the same data during the refresh. Synthetic restart tests cover
stale and partially refreshed snapshots and retain an unrelated journey.

This assumes one backend replica and a correctly functioning durable share;
Azure execution and failure durability have not been verified. Pending markers
can temporarily contain a return code and opaque checkpoint IDs, so the share
requires appropriate access controls. This is logical removal from current
snapshots, not proof of physical erasure or deletion of Azure snapshots,
versions, or other external copies. New requests after deletion may create new
data.

## Review required

The approved retention choices do not authorize real applicant data. The
privacy-filtered fact set, consent language, and correction/deletion behavior
still require product/privacy review before real-applicant use.
