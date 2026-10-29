<#
.SYNOPSIS
Validates and deploys the approved Scheme Saathi UI commit to Azure.

.DESCRIPTION
Refuses deployment unless the required branch is clean, pushed, and has a
successful Frontend checks run for its exact HEAD commit. It then builds that
commit in the existing registry, updates the existing Container App, waits for
the new revision, and verifies the public Streamlit health endpoint.

.PARAMETER DryRun
Runs all local, GitHub, and Azure target checks without building or deploying.

.PARAMETER ResourceGroup
Existing Azure resource group that contains the shared development resources.

.PARAMETER Location
Required Azure location, in normalized Azure CLI form.

.PARAMETER Environment
Existing Azure Container Apps environment to verify.

.PARAMETER AppName
Existing Azure Container App to update.

.PARAMETER RequiredBranch
Only this branch may be deployed by the script.

.EXAMPLE
.\deploy.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$ResourceGroup = "rg-scheme-saathi-dev",
    [string]$Location = "centralindia",
    [string]$Environment = "cae-scheme-saathi-dev",
    [string]$AppName = "scheme-saathi-ui",
    [string]$RequiredBranch = "role6-deployment-ops-roy"
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string]$Description,
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    Write-Host "==> $Description"
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Command
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }
}

function Invoke-CheckedOutput {
    param(
        [Parameter(Mandatory)]
        [string]$Description,
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    Write-Host "==> $Description"
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $Command
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }
    return $output
}

Push-Location $repoRoot
try {
    # These Git and Actions gates bind deployment to reviewed, remotely
    # reproducible content rather than uncommitted or unpushed local files.
    $branch = (git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne $RequiredBranch) {
        throw "Deployment requires branch '$RequiredBranch'; current branch is '$branch'."
    }

    $changes = @(git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $changes.Count -gt 0) {
        throw "The worktree must be clean. Commit or discard changes before deployment."
    }

    git rev-parse --abbrev-ref --symbolic-full-name "@{u}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "The branch has no upstream. Push it before deployment."
    }

    $unpushed = [int](git rev-list --count "@{u}..HEAD")
    if ($LASTEXITCODE -ne 0 -or $unpushed -ne 0) {
        throw "The branch has $unpushed unpushed commit(s). Push before deployment."
    }

    # All later image and workflow checks use this immutable commit identifier.
    $commit = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read the current Git commit."
    }

    $workflowJson = gh run list `
        --workflow frontend-checks.yml `
        --branch $RequiredBranch `
        --limit 1 `
        --json databaseId,status,conclusion,headSha
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read the Frontend checks workflow."
    }

    $workflowRuns = @($workflowJson | ConvertFrom-Json)
    if ($workflowRuns.Count -ne 1) {
        throw "No Frontend checks workflow run was found."
    }

    $workflow = $workflowRuns[0]
    if (
        $workflow.headSha -ne $commit -or
        $workflow.status -ne "completed" -or
        $workflow.conclusion -ne "success"
    ) {
        throw "Frontend checks must pass for commit $commit before deployment."
    }

    $accountState = (az account show --query state --output tsv).Trim()
    if ($LASTEXITCODE -ne 0 -or $accountState -ne "Enabled") {
        throw "Azure CLI is not authenticated to an enabled subscription."
    }

    Invoke-Checked -Description "Verify Azure Container Apps environment" -Command {
        az containerapp env show `
            --name $Environment `
            --resource-group $ResourceGroup `
            --output none
    }

    Invoke-Checked -Description "Verify existing Container App" -Command {
        az containerapp show `
            --name $AppName `
            --resource-group $ResourceGroup `
            --output none
    }

    # Discover the registry from the existing app instead of accepting an
    # arbitrary registry target from the command line.
    $registryServer = (
        Invoke-CheckedOutput -Description "Read existing registry" -Command {
            az containerapp show `
                --name $AppName `
                --resource-group $ResourceGroup `
                --query "properties.configuration.registries[0].server" `
                --output tsv
        }
    ).Trim()
    if (-not $registryServer.EndsWith(".azurecr.io")) {
        throw "The existing app does not use an Azure Container Registry."
    }
    $registryName = $registryServer.Split(".")[0]
    $appLocation = (
        Invoke-CheckedOutput -Description "Verify existing app location" -Command {
            az containerapp show `
                --name $AppName `
                --resource-group $ResourceGroup `
                --query location `
                --output tsv
        }
    ).Trim().Replace(" ", "").ToLowerInvariant()
    if ($appLocation -ne $Location.ToLowerInvariant()) {
        throw "Container App '$AppName' is not in '$Location'."
    }

    Write-Host "Checks passed."
    Write-Host "Commit: $commit"
    Write-Host "Target: $ResourceGroup/$AppName"

    if ($DryRun) {
        Write-Host "Dry run complete. No Azure resources were changed."
        exit 0
    }

    $imageTag = "git-$($commit.Substring(0, 12))"
    $image = "$registryServer/${AppName}:$imageTag"
    $buildRunId = (
        Invoke-CheckedOutput -Description "Queue source build" -Command {
            az acr build `
                --registry $registryName `
                --image "${AppName}:$imageTag" `
                --no-logs `
                --query runId `
                --output tsv `
                $repoRoot
        }
    ).Trim()
    if (-not $buildRunId) {
        throw "Azure Container Registry did not return a build run ID."
    }

    # ACR returning a run ID means the build was queued, not completed. Poll
    # the server-side status before allowing that image tag to be deployed.
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        $buildStatus = (
            Invoke-CheckedOutput -Description "Check build $buildRunId" -Command {
                az acr task show-run `
                    --registry $registryName `
                    --run-id $buildRunId `
                    --query status `
                    --output tsv
            }
        ).Trim()
        if ($buildStatus -eq "Succeeded") {
            break
        }
        if ($buildStatus -notin @("Queued", "Started", "Running")) {
            throw "Azure build $buildRunId finished with status '$buildStatus'."
        }
        if ($attempt -eq 40) {
            throw "Azure build $buildRunId did not finish in time."
        }
        Start-Sleep -Seconds 15
    }

    # Scale-to-zero controls idle cost; max one replica avoids splitting
    # Streamlit's in-memory session state across concurrent replicas.
    Invoke-Checked -Description "Deploy built image" -Command {
        az containerapp update `
            --name $AppName `
            --resource-group $ResourceGroup `
            --image $image `
            --min-replicas 0 `
            --max-replicas 1 `
            --set-env-vars "APP_VERSION=$imageTag" `
            --output none
    }

    # Do not treat the update command as readiness. Wait until Azure reports
    # the latest revision itself as ready and the app as running.
    $app = $null
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        $appJson = az containerapp show `
            --name $AppName `
            --resource-group $ResourceGroup `
            --query "{latest:properties.latestRevisionName,ready:properties.latestReadyRevisionName,running:properties.runningStatus,fqdn:properties.configuration.ingress.fqdn}" `
            --output json
        if ($LASTEXITCODE -ne 0) {
            throw "Could not read Container App status."
        }

        $app = $appJson | ConvertFrom-Json
        if (
            $app.latest -eq $app.ready -and
            $app.running -eq "Running"
        ) {
            break
        }

        if ($attempt -eq 20) {
            throw "The latest revision did not become ready in time."
        }

        Start-Sleep -Seconds 15
    }

    # Exercise public ingress, application startup, and the health endpoint.
    # Retries also allow time for the first scale-from-zero request.
    $url = "https://$($app.fqdn)"
    $healthy = $false
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        try {
            $response = Invoke-WebRequest `
                -Uri "$url/_stcore/health" `
                -UseBasicParsing `
                -TimeoutSec 30
            if ($response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        }
        catch {
            if ($attempt -eq 12) {
                throw "The deployed revision did not pass its public health check."
            }
        }

        Start-Sleep -Seconds 10
    }

    if (-not $healthy) {
        throw "The deployed revision did not pass its public health check."
    }

    Write-Host "Deployment complete."
    Write-Host "Commit: $commit"
    Write-Host "Revision: $($app.ready)"
    Write-Host "URL: $url"
    Write-Host "Health: healthy"
}
finally {
    Pop-Location
}
