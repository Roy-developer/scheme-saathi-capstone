# Durable pending approvals (proposal for review)

Status: proposal only. Not implemented.

## Problem

`scheme_saathi.pending_approvals` is an in-process up/down counter.
`src/observability/metrics.py:33` holds `_pending_approvals_open`, which
starts at 0 after a restart. Increments happen at
`src/api/app.py:1069` (`create_application_draft`) and decrements at
`src/api/app.py:1242` (`update_application_approval`). Replicas each count
their own drafts, so the value drifts from portal truth.

## Option A: derive from portal `list_drafts`

On startup and periodically, read waiting drafts from the portal and set
the gauge from that count. The portal is already the source of truth.
`list_drafts` is at `src/portal/repository.py:718` and filters by
`journey_id`, so a new portal action (for example `count_waiting`) is needed
to count across journeys. Use an observable gauge, not an up/down counter.

## Option B: persist in the journey store and reconcile

Record each pending approval in the journey store (`AsyncSqliteStore`,
created at `src/api/app.py:425`, held at `app.py:508`) and reconcile against
the portal on startup. This needs a new schema, a reconciliation job, and a
second source of truth to keep in sync.

## Recommendation

Option A. It adds no new persistence, avoids a second source of truth, and
fixes restart and multi-replica drift in one place. Option B is only worth
the cost if the portal cannot expose a cross-journey count.

## Open questions

- Acceptable portal load for periodic counting.
- Whether `count_waiting` may be exposed to the `api_read` routing set
  (`src/mcp_servers/service_routing.py:33`).
