---
name: deploy-scheme-saathi
description: Safely deploy one Scheme Saathi image to the existing Azure frontend and backend Container Apps. Use when asked to deploy or redeploy Scheme Saathi.
---

# Deploy Scheme Saathi

Use `trigger-shared-deploy.ps1` to deploy the current pushed branch through
GitHub Actions. Team members do not need Azure credentials.

## Required process

1. Explain that the workflow validates the exact selected commit again before
   deployment.
2. Explain that the deployment updates the shared Azure frontend and backend
   Container Apps and may incur Azure build, registry, logging and runtime
   charges.
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
  - frontend app `scheme-saathi-ui`
  - backend app `scheme-saathi-api`
  - location `centralindia`
- Require a clean worktree and a pushed commit.
- Require validation inside the shared deployment workflow.
- Keep scale settings at minimum `0` and maximum `1`.
- Build one image and deploy it to both apps with separate startup command
  overrides; the frontend must use the backend app URL, not `localhost`.
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
