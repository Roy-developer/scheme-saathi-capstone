# Red-team authorship and review

The current attack file has 30 cases, but its schema does not record an
`author` or `reviewed_by` for each case. Independent authorship is therefore
not yet evidenced.

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

The current suite remains partial until the case schema/report includes
authorship and independent review metadata and the memory/approval cases are
executed.
