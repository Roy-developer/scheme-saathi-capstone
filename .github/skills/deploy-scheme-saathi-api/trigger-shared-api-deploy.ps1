[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$Workflow = "shared-api-deploy.yml"
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
    # Deploy the checked-out branch so members do not manually copy its name.
    $branch = (git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
        throw "Check out the backend branch that should be deployed."
    }

    # Only committed and pushed content can be validated by GitHub Actions.
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

    # Manual deployment workflows must be registered on the default branch.
    gh workflow view $Workflow --repo $repo *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "$Workflow must be merged into main before API deployment."
    }

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
    if ("AZURE_API_APP" -notin $configuredVariables) {
        throw "The shared-dev environment is missing AZURE_API_APP."
    }

    Write-Host "Checks passed."
    Write-Host "Repository: $repo"
    Write-Host "Branch: $branch"
    Write-Host "Commit: $commit"

    if ($DryRun) {
        Write-Host "Dry run complete. No workflow was started."
        exit 0
    }

    # Match both title and trigger time so an older run cannot be mistaken for
    # the deployment started by this command.
    $startedAt = [DateTimeOffset]::UtcNow.AddSeconds(-5)
    Invoke-Checked -Description "Start shared API deployment" -Command {
        gh workflow run $Workflow `
            --repo $repo `
            --ref main `
            --field "ref=$branch"
    }

    $run = $null
    $expectedTitle = "Shared API: $branch"
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        Start-Sleep -Seconds 5
        $runs = gh run list `
            --repo $repo `
            --workflow $Workflow `
            --event workflow_dispatch `
            --limit 20 `
            --json databaseId,displayTitle,createdAt,url |
            ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) {
            throw "Could not find the shared API workflow run."
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
        throw "The shared API workflow run did not appear in time."
    }

    Invoke-Checked -Description "Wait for shared API deployment" -Command {
        gh run watch $run.databaseId --repo $repo --exit-status
    }

    Write-Host "Shared API deployment passed."
    Write-Host "Branch: $branch"
    Write-Host "Commit: $commit"
    Write-Host "Workflow: $($run.url)"
}
finally {
    Pop-Location
}
