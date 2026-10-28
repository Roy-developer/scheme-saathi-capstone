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
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string]$Description,
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

Push-Location $repoRoot
try {
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

    az containerapp env show `
        --name $Environment `
        --resource-group $ResourceGroup `
        --query name `
        --output tsv *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Azure Container Apps environment '$Environment' was not found in '$ResourceGroup'."
    }

    az containerapp show `
        --name $AppName `
        --resource-group $ResourceGroup `
        --query name `
        --output tsv *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Container App '$AppName' was not found in '$ResourceGroup'."
    }

    Write-Host "Checks passed."
    Write-Host "Commit: $commit"
    Write-Host "Target: $ResourceGroup/$AppName"

    if ($DryRun) {
        Write-Host "Dry run complete. No Azure resources were changed."
        exit 0
    }

    Invoke-Checked -Description "Build and deploy source" -Command {
        az containerapp up `
            --name $AppName `
            --resource-group $ResourceGroup `
            --location $Location `
            --environment $Environment `
            --source $repoRoot `
            --ingress external `
            --target-port 8501 `
            --output none
    }

    $version = "git-$($commit.Substring(0, 7))"
    Invoke-Checked -Description "Apply scale-to-zero settings" -Command {
        az containerapp update `
            --name $AppName `
            --resource-group $ResourceGroup `
            --min-replicas 0 `
            --max-replicas 1 `
            --set-env-vars "APP_VERSION=$version" `
            --output none
    }

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
