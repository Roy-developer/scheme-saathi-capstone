# Evaluation freeze

No Phase 5 evaluation freeze is approved yet. This directory is reserved for a
reviewed manifest before any paid comparison or final held-out run.

The manifest must pin the provider and model ID, prompt/middleware versions,
tool allowlists, call/token/cost budgets, active rule-package and registry
hashes, Reflexion playbook hash, red-team suite version, and memory-policy
version. E1 arms and before/after comparisons must share the same pins.

The `nvidia/nemotron-3.5-lightning:free` smoke on 2026-11-12 checked the
OpenRouter client with a generic prompt only. It did not freeze production
settings or authorize evaluation runs.
