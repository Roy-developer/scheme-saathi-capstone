# Held-out evaluation cases (Role 5 only)

**Do not commit protected persona files in this directory.**

Capstone / PDF rules:

- About 20 development cases may live in `eval/development/` (this repo currently keeps a larger development boundary set; that is fine for tuning).
- At least **40 held-out** cases belong in Role-5-only storage.
- CI for the application must not checkout, package, index, print, or upload held-out fixtures. `scripts/check_held_out_custody.py` fails the workflow if files under `eval/held_out/local/` are tracked.
- The default harness (`scripts/evaluate_eligibility_dev.py`) **rejects** protected / held-out sets.
- Held-out scoring uses `scripts/evaluate_eligibility_held_out.py` from a controlled Role-5 environment only.

## Local generation (gitignored)

```bash
python scripts/generate_held_out_personas.py
# writes eval/held_out/local/personas_held_out_v1.json  (≥40, protected)

python scripts/evaluate_eligibility_held_out.py
```

`eval/held_out/local/` is gitignored. The Dockerfiles copy explicit application
and scheme-data paths and do not copy this directory. The local repository
currently contains no held-out persona file; do not generate or tune held-out
cases until the freeze and custody owners authorize the work.

If a protected case is exposed, stop scoring it as held-out, record the
exposure, reclassify it as development, and replace it before making a final
held-out claim. Dual independent labels (Role 1 + teammate) and three frozen
held-out repeats remain required.
