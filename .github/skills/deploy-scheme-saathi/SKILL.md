---
name: deploy-scheme-saathi
description: Safely deploy the existing Scheme Saathi Streamlit frontend to its Azure Container App. Use when asked to deploy or redeploy the Scheme Saathi UI.
---

# Deploy Scheme Saathi

Use `deploy.ps1` from this skill directory for frontend deployments.

## Required process

1. Invoke `validate-scheme-saathi` and require a successful exact-commit
   GitHub Actions result.
2. Explain that the deployment updates an existing Azure Container App and may
   incur Azure build, registry, logging and runtime charges.
3. Run the script with `-DryRun` first.
4. If the checks fail, stop and explain the failure. Do not bypass a failed Git,
   GitHub Actions or Azure resource check.
5. If the checks pass and the user has explicitly requested deployment, run the
   script without `-DryRun`.
6. Report the deployed Git commit, Azure revision, stable application URL and
   health result.

## Safety rules

- Never create, rename or delete Azure resources.
- Deploy only from `role6-deployment-ops-roy`.
- Deploy only to:
  - resource group `rg-scheme-saathi-dev`
  - environment `cae-scheme-saathi-dev`
  - app `scheme-saathi-ui`
  - location `centralindia`
- Require a clean worktree and a pushed commit.
- Require the `Frontend checks` workflow to pass for the same commit.
- Keep scale settings at minimum `0` and maximum `1`.
- Do not print credentials, tokens, subscription IDs or tenant IDs.
- Do not retry a failed deployment without first finding the cause.

## Commands

Dry run:

```powershell
& ".github\skills\deploy-scheme-saathi\deploy.ps1" -DryRun
```

Deploy:

```powershell
& ".github\skills\deploy-scheme-saathi\deploy.ps1"
```
