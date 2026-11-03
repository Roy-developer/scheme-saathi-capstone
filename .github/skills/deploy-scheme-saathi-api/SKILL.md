---
name: deploy-scheme-saathi-api
description: Validate and deploy the current pushed branch to the shared Scheme Saathi FastAPI Azure Container App. Use for backend/API deployment or testing.
---

# Deploy Scheme Saathi API

Use `trigger-shared-api-deploy.ps1` to deploy the current pushed branch through
the trusted workflow on `main`. Team members need GitHub access, not Azure
credentials.

## Required process

1. Explain that the workflow validates the exact selected commit.
2. Explain that it updates the one shared API and may incur Azure build,
   registry, logging and runtime charges.
3. Run the script with `-DryRun`.
4. Stop on any Git, GitHub Actions or configuration failure.
5. If checks pass and deployment was explicitly requested, run without
   `-DryRun`.
6. Report the branch, commit, workflow URL, API URL and result.

## Safety rules

- Deploy only a clean, pushed branch.
- Use the trusted workflow definition from `main`.
- Allow only one shared API deployment at a time.
- Create or update only `scheme-saathi-api` in `rg-scheme-saathi-dev`.
- Use external ingress on port `8000`.
- Keep minimum replicas `0` and maximum replicas `1`.
- Never print credentials, tokens, subscription IDs or tenant IDs.
- Do not retry a failure before finding its cause.

## Commands

Dry run:

```powershell
& ".github\skills\deploy-scheme-saathi-api\trigger-shared-api-deploy.ps1" -DryRun
```

Deploy:

```powershell
& ".github\skills\deploy-scheme-saathi-api\trigger-shared-api-deploy.ps1"
```
