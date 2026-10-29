[CmdletBinding()]
param(
    [string]$Workflow = "frontend-checks.yml"
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
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
        throw "Could not determine the current Git branch."
    }

    $changes = @(git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $changes.Count -gt 0) {
        throw "The worktree must be clean. Commit or discard changes before validation."
    }

    $upstream = (
        git rev-parse --abbrev-ref --symbolic-full-name "@{u}"
    ).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $upstream) {
        throw "The branch has no upstream. Push it before validation."
    }

    $unpushed = [int](git rev-list --count "@{u}..HEAD")
    if ($LASTEXITCODE -ne 0 -or $unpushed -ne 0) {
        throw "The branch has $unpushed unpushed commit(s). Push before validation."
    }

    $commit = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read the current Git commit."
    }

    $runsJson = gh run list `
        --workflow $Workflow `
        --commit $commit `
        --limit 1 `
        --json databaseId,status,conclusion,headSha,url
    if ($LASTEXITCODE -ne 0) {
        throw "Could not query GitHub Actions."
    }
    $runs = $runsJson | ConvertFrom-Json

    if ($runs.Count -eq 0) {
        Invoke-Checked -Description "Start GitHub Actions validation" -Command {
            gh workflow run $Workflow --ref $branch
        }

        $run = $null
        for ($attempt = 1; $attempt -le 12; $attempt++) {
            Start-Sleep -Seconds 5
            $runsJson = gh run list `
                --workflow $Workflow `
                --commit $commit `
                --event workflow_dispatch `
                --limit 1 `
                --json databaseId,status,conclusion,headSha,url
            if ($LASTEXITCODE -ne 0) {
                throw "Could not find the dispatched GitHub Actions run."
            }
            $dispatchedRuns = $runsJson | ConvertFrom-Json
            if ($dispatchedRuns.Count -gt 0) {
                $run = $dispatchedRuns[0]
                break
            }
        }
        if ($null -eq $run) {
            throw "The dispatched GitHub Actions run did not appear in time."
        }
    }
    else {
        $run = $runs[0]
    }

    if ($run.headSha -ne $commit) {
        throw "GitHub Actions returned a run for a different commit."
    }

    if ($run.status -ne "completed") {
        Invoke-Checked -Description "Wait for GitHub Actions validation" -Command {
            gh run watch $run.databaseId --exit-status
        }
        $run = gh run view $run.databaseId `
            --json databaseId,status,conclusion,headSha,url |
            ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) {
            throw "Could not read the completed GitHub Actions run."
        }
    }

    if ($run.status -ne "completed" -or $run.conclusion -ne "success") {
        throw "GitHub Actions validation did not succeed. Do not deploy."
    }

    Write-Host "Validation passed."
    Write-Host "Commit: $commit"
    Write-Host "Workflow run: $($run.databaseId)"
    Write-Host "URL: $($run.url)"
}
finally {
    Pop-Location
}
