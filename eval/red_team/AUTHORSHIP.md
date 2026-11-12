# Red-team authorship and review

The current attack file has 30 cases, but its schema does not record an
`author` or `reviewed_by` for each case. Independent authorship is therefore
not yet evidenced.

## Review record

On 2026-11-12, the project approver confirmed authorship of
`RT-INFLATE-001`, `RT-MEMORY-001` through `RT-MEMORY-003`, and
`RT-OTHER-001`, `RT-OTHER-002`, and `RT-OTHER-005`; Vivian reviewed them.
Both were confirmed separate from the control implementers. Technical review
approves these seven as scenario briefs for implementation, not as executed
security evidence. They remain `stub` until deterministic synthetic setup,
runtime requests, and assertions are implemented and run.

Before execution, make `RT-INFLATE-001` identify the concrete scheme and
confirmed fact boundary; make `RT-MEMORY-001` seed only synthetic allowed facts;
and make `RT-MEMORY-002` / `RT-MEMORY-003` exercise distinct real API paths
with synthetic journey and draft IDs. Keep `RT-OTHER-005` focused on prior
conversation verdicts so it remains distinct from saved-memory access.

For new or revised attacks:

1. The attack author records an owner who did not implement the control under
   test.
2. A separate reviewer checks that the scenario is realistic, uses synthetic
   data, has an explicit expected behavior, and does not expose protected
   held-out cases.
3. Keep the attack input and expected outcome stable for a run; identify any
   edits with a new suite version.
4. Report `stub`, `runnable`, and executed counts separately. A runnable check
   is not evidence that the full runtime path was exercised.
5. If an attack or held-out case is shared with a control author, record the
   exposure and replace/reclassify affected held-out cases before claiming a
   final result.

The seven reviewed cases now carry authorship and review metadata in the case
schema and development report. The other 23 legacy cases still lack that
metadata, and all seven reviewed cases remain unexecuted stubs. The suite
therefore remains partial and does not establish 30 independently authored,
executed attacks.
