# Held-out evaluation cases (policy only)

**Do not commit protected persona files in this directory.**

Capstone rules:

- About 20 development cases may live in `eval/development/`.
- At least 40 held-out cases belong in Role-5-only storage (or a private location with repository permissions that builders and the agent cannot read).
- CI for the application must not checkout, package, index, print, or upload held-out fixtures.
- The in-repo harness (`scripts/evaluate_eligibility_dev.py`) **rejects** any set with `split != "development"` or `protected: true`.

When held-out storage is ready, keep the same persona schema as development (`eval/schema.py`) and run scoring only from a controlled Role-5 environment after freezing prompts, rules, and lessons.
