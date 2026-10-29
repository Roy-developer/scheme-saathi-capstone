---
name: deploy-scheme-saathi
description: Safely deploy the existing Scheme Saathi Streamlit frontend to its Azure Container App. Use when asked to deploy or redeploy the Scheme Saathi UI.
---

# Deploy Scheme Saathi

Use `trigger-shared-deploy.ps1` to deploy the current pushed branch through
GitHub Actions. Team members do not need Azure credentials.

## Required process

1. Explain that the workflow validates the exact selected commit again before
   deployment.
2. Explain that the deployment updates the shared Azure Container App and may
   incur Azure build, registry, logging and runtime charges.
3. Run `trigger-shared-deploy.ps1 -DryRun`.
4. If the checks fail, stop and explain the failure. Do not bypass a failed Git,
   GitHub Actions or Azure resource check.
5. If the checks pass and the user has explicitly requested deployment, run the
   trigger script without `-DryRun`.
6. Report the selected branch, commit, workflow URL and deployment result.

## Safety rules

- Never create, rename or delete Azure resources.
- Deploy only the current clean, pushed branch.
- Use the trusted workflow definition from `main`.
- Allow only one shared deployment at a time.
- Deploy only to:
  - resource group `rg-scheme-saathi-dev`
  - environment `cae-scheme-saathi-dev`
  - app `scheme-saathi-ui`
  - location `centralindia`
- Require a clean worktree and a pushed commit.
- Require validation inside the shared deployment workflow.
- Keep scale settings at minimum `0` and maximum `1`.
- Do not print credentials, tokens, subscription IDs or tenant IDs.
- Do not retry a failed deployment without first finding the cause.

## Commands

Dry run:

```powershell
& ".github\skills\deploy-scheme-saathi\trigger-shared-deploy.ps1" -DryRun
```

Deploy:

```powershell
& ".github\skills\deploy-scheme-saathi\trigger-shared-deploy.ps1"
```
