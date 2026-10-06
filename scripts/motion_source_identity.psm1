Set-StrictMode -Version Latest

function Get-MotionSubmoduleWorktreeSha256 {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $gitmodulesPath = Join-Path $RepoRoot ".gitmodules"
    $relativePaths = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $gitmodulesPath -PathType Leaf) {
        $configuredPaths = @(
            & git -C $RepoRoot config --file $gitmodulesPath --get-regexp '^submodule\..*\.path$' 2>$null
        )
        $configExitCode = $LASTEXITCODE
        if ($configExitCode -gt 1) {
            throw "Unable to enumerate declared motion source submodules from '$gitmodulesPath'."
        }
        foreach ($configuredPath in $configuredPaths) {
            $configuredPathText = [string]$configuredPath
            $separatorIndex = $configuredPathText.IndexOf(' ')
            if ($separatorIndex -lt 0) {
                continue
            }
            $relativePath = $configuredPathText.Substring($separatorIndex + 1)
            if ([string]::IsNullOrWhiteSpace($relativePath)) {
                continue
            }
            $literalPathspec = ":(top,literal)$relativePath"
            $stagedEntries = @(
                & git -C $RepoRoot ls-files --stage -- $literalPathspec 2>&1
            )
            if ($LASTEXITCODE -ne 0) {
                throw "Unable to inspect motion source submodule index entry '$relativePath'."
            }
            foreach ($entry in $stagedEntries) {
                $entryText = [string]$entry
                $tabIndex = $entryText.IndexOf([char]9)
                if ($tabIndex -lt 0) {
                    continue
                }
                $metadata = $entryText.Substring(0, $tabIndex) -split ' '
                if (
                    $metadata.Count -ge 3 -and
                    $metadata[0] -eq "160000" -and
                    $entryText.Substring($tabIndex + 1) -ceq $relativePath
                ) {
                    $relativePaths.Add($relativePath)
                    break
                }
            }
        }
    }

    $builder = [System.Text.StringBuilder]::new()
    foreach ($relativePath in $relativePaths) {
        $submoduleRoot = Join-Path $RepoRoot $relativePath
        if (-not (Test-Path -LiteralPath $submoduleRoot -PathType Container)) {
            $identityJson = "uninitialized"
        } else {
            $submoduleIdentity = Get-MotionSourceIdentity -RepoRoot $submoduleRoot
            $identityJson = $submoduleIdentity | ConvertTo-Json -Compress -Depth 8
        }
        [void]$builder.Append($relativePath)
        [void]$builder.Append([char]0)
        [void]$builder.Append($identityJson)
        [void]$builder.Append([char]10)
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($builder.ToString())
    return [Convert]::ToHexString(
        [System.Security.Cryptography.SHA256]::HashData($bytes)
    ).ToLowerInvariant()
}

function Get-MotionSourceIdentity {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
    $commitOutput = & git -C $resolvedRoot rev-parse HEAD 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to identify the motion source commit: $($commitOutput -join ' ')"
    }
    $commit = ($commitOutput -join "`n").Trim()

    $statusOutput = & git -C $resolvedRoot status --porcelain=v1 --untracked-files=all --ignore-submodules=none 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the motion source worktree: $($statusOutput -join ' ')"
    }
    $statusText = ($statusOutput -join "`n").TrimEnd()

    $diffPath = Join-Path ([System.IO.Path]::GetTempPath()) ("motion-source-diff-{0}.bin" -f [guid]::NewGuid().ToString("N"))
    try {
        & git -C $resolvedRoot diff --binary HEAD "--output=$diffPath" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to fingerprint tracked motion source changes."
        }
        $trackedDiffSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $diffPath).Hash.ToLowerInvariant()
    } finally {
        Remove-Item -LiteralPath $diffPath -Force -ErrorAction SilentlyContinue
    }

    $untrackedPaths = @(& git -C $resolvedRoot ls-files --others --exclude-standard 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to enumerate untracked motion source files: $($untrackedPaths -join ' ')"
    }
    $untrackedBuilder = [System.Text.StringBuilder]::new()
    foreach ($relativePath in $untrackedPaths) {
        if ([string]::IsNullOrWhiteSpace([string]$relativePath)) {
            continue
        }
        $fullPath = Join-Path $resolvedRoot ([string]$relativePath)
        $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction SilentlyContinue
        if ($null -eq $item) {
            $kind = "unreadable"
            $contentIdentity = "unavailable"
        } elseif ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            $kind = "link"
            $contentIdentity = [string]$item.Target
        } elseif (-not $item.PSIsContainer) {
            $kind = "file"
            $contentIdentity = (Get-FileHash -Algorithm SHA256 -LiteralPath $fullPath).Hash.ToLowerInvariant()
        } else {
            $kind = "directory"
            $contentIdentity = ""
        }
        [void]$untrackedBuilder.Append([string]$relativePath)
        [void]$untrackedBuilder.Append([char]0)
        [void]$untrackedBuilder.Append($kind)
        [void]$untrackedBuilder.Append([char]0)
        [void]$untrackedBuilder.Append($contentIdentity)
        [void]$untrackedBuilder.Append([char]10)
    }
    $untrackedBytes = [System.Text.Encoding]::UTF8.GetBytes($untrackedBuilder.ToString())
    $untrackedContentSha256 = [Convert]::ToHexString(
        [System.Security.Cryptography.SHA256]::HashData($untrackedBytes)
    ).ToLowerInvariant()
    $statusBytes = [System.Text.Encoding]::UTF8.GetBytes($statusText)
    $statusSha256 = [Convert]::ToHexString(
        [System.Security.Cryptography.SHA256]::HashData($statusBytes)
    ).ToLowerInvariant()
    $submoduleWorktreeSha256 = Get-MotionSubmoduleWorktreeSha256 -RepoRoot $resolvedRoot

    return [pscustomobject]@{
        schemaVersion = 1
        gitCommit = $commit
        gitStatusSha256 = $statusSha256
        gitTrackedDiffSha256 = $trackedDiffSha256
        gitUntrackedContentSha256 = $untrackedContentSha256
        gitSubmoduleWorktreeSha256 = $submoduleWorktreeSha256
        gitUntrackedFileCount = @($untrackedPaths | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }).Count
        gitWorktreeClean = [string]::IsNullOrWhiteSpace($statusText)
    }
}

function Assert-MotionSourceIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Identity,
        [switch]$AllowDirtyWorktree
    )

    if ($Identity.gitWorktreeClean -eq $true) {
        return
    }
    if ($AllowDirtyWorktree) {
        Write-Warning "Running with an uncommitted motion source identity because -AllowDirtyWorktree was explicitly supplied."
        return
    }
    throw @"
Motion generation requires committed source code so a run and its resumed stages have a stable identity.
Commit or stash tracked, staged, untracked, and submodule changes, or pass -AllowDirtyWorktree for an explicitly identified development run.
Current commit: $($Identity.gitCommit)
Worktree status fingerprint: $($Identity.gitStatusSha256)
"@
}

Export-ModuleMember -Function Get-MotionSourceIdentity, Assert-MotionSourceIdentity
