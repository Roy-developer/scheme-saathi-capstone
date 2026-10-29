[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$Workflow = "shared-dev-deploy.yml"
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
    # The workflow deploys the checked-out branch so members do not need to
    # type or copy branch names into commands.
    $branch = (git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
        throw "Check out the branch that should be deployed."
    }

    # GitHub can validate only committed, pushed content. Refuse to present a
    # successful workflow result for local changes that were not included.
    $changes = @(git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $changes.Count -gt 0) {
        throw "The worktree must be clean. Commit or discard changes before deployment."
    }

    $upstream = (
        git rev-parse --abbrev-ref --symbolic-full-name "@{u}"
    ).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $upstream) {
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

    $repo = (
        gh repo view --json nameWithOwner --jq ".nameWithOwner"
    ).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $repo) {
        throw "Could not determine the GitHub repository."
    }

    # Always execute the reviewed workflow definition from main. The selected
    # member branch supplies application code, not deployment permissions.
    gh workflow view $Workflow --repo $repo --ref main *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "$Workflow must be merged into main before shared deployment."
    }

    # Check names only. Values are intentionally not printed because the skill
    # needs to confirm configuration, not expose account identifiers.
    $requiredVariables = @(
        "AZURE_ACR_NAME",
        "AZURE_CLIENT_ID",
        "AZURE_CONTAINER_APP",
        "AZURE_CONTAINER_ENVIRONMENT",
        "AZURE_LOCATION",
        "AZURE_RESOURCE_GROUP",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_TENANT_ID"
    )
    $configuredVariables = @(
        gh variable list `
            --env shared-dev `
            --repo $repo `
            --json name `
            --jq ".[].name"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read the shared-dev GitHub environment variables."
    }
    $missingVariables = @(
        $requiredVariables |
            Where-Object { $_ -notin $configuredVariables }
    )
    if ($missingVariables.Count -gt 0) {
        throw "Missing shared-dev variables: $($missingVariables -join ', ')."
    }

    Write-Host "Checks passed."
    Write-Host "Repository: $repo"
    Write-Host "Branch: $branch"
    Write-Host "Commit: $commit"

    if ($DryRun) {
        Write-Host "Dry run complete. No workflow was started."
        exit 0
    }

    # Record the trigger time and expected run title so an older deployment of
    # the same branch cannot be mistaken for the new workflow run.
    $startedAt = [DateTimeOffset]::UtcNow.AddSeconds(-5)
    Invoke-Checked -Description "Start shared development deployment" -Command {
        gh workflow run $Workflow `
            --repo $repo `
            --ref main `
            --field "ref=$branch"
    }

    $run = $null
    $expectedTitle = "Shared dev: $branch"
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        Start-Sleep -Seconds 5
        $runs = gh run list `
            --repo $repo `
            --workflow $Workflow `
            --event workflow_dispatch `
            --limit 20 `
            --json databaseId,displayTitle,createdAt,status,url |
            ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) {
            throw "Could not find the shared deployment workflow run."
        }
        $run = $runs |
            Where-Object {
                $_.displayTitle -eq $expectedTitle -and
                [DateTimeOffset]$_.createdAt -ge $startedAt
            } |
            Sort-Object createdAt -Descending |
            Select-Object -First 1
        if ($null -ne $run) {
            break
        }
    }
    if ($null -eq $run) {
        throw "The shared deployment workflow run did not appear in time."
    }

    # gh streams job progress and returns a failure exit code if validation,
    # Azure build, revision readiness, or health verification fails.
    Invoke-Checked -Description "Wait for shared deployment" -Command {
        gh run watch $run.databaseId --repo $repo --exit-status
    }

    $completedRun = gh run view $run.databaseId `
        --repo $repo `
        --json conclusion,status,url |
        ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read the completed shared deployment."
    }
    if (
        $completedRun.status -ne "completed" -or
        $completedRun.conclusion -ne "success"
    ) {
        throw "The shared development deployment did not succeed."
    }

    Write-Host "Shared development deployment passed."
    Write-Host "Branch: $branch"
    Write-Host "Commit: $commit"
    Write-Host "Workflow: $($completedRun.url)"
}
finally {
    Pop-Location
}
