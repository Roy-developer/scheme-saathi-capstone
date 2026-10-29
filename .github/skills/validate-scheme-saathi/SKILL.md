---
name: validate-scheme-saathi
description: Run and verify Scheme Saathi GitHub Actions checks for the exact pushed commit before deployment. Use when asked to test, validate, verify, or prepare Scheme Saathi for deployment.
---

# Validate Scheme Saathi

Use `validate.ps1` from this skill directory before invoking
`deploy-scheme-saathi`.

## Required process

1. Run the validation script.
2. If an exact-commit workflow run already exists, reuse it.
3. If no run exists, start `Frontend checks` through `workflow_dispatch`.
4. Wait for the run to finish.
5. Report the commit, workflow run, status and URL.
6. Invoke the deployment skill only after validation succeeds and the user has
   explicitly requested deployment.

## Checks performed by GitHub Actions

- Install the application and declared development dependencies.
- Compile Python sources.
- Run all pytest unit and fixture tests.
- Verify fixture data is included in the installed Python package.

## Safety rules

- Do not install pytest or project dependencies on the user's computer.
- Require a clean worktree.
- Require the current commit to be pushed to its upstream branch.
- Validate the exact current commit, not merely the latest branch run.
- Do not bypass, ignore or automatically rerun a failed workflow.
- Do not call the deployment skill after a failed or incomplete validation.

## Command

```powershell
& ".github\skills\validate-scheme-saathi\validate.ps1"
```
