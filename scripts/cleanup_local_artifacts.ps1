Param(
    [switch]$WhatIf
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot

function Get-PathSizeBytes([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        return 0
    }

    $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) {
        return 0
    }

    if ($item.PSIsContainer) {
        $size = (Get-ChildItem -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        if ($null -eq $size) {
            return 0
        }
        return [int64]$size
    }

    return [int64]$item.Length
}

function Format-Size([int64]$bytes) {
    if ($bytes -ge 1GB) {
        return "{0:N2} GB" -f ($bytes / 1GB)
    }
    if ($bytes -ge 1MB) {
        return "{0:N2} MB" -f ($bytes / 1MB)
    }
    if ($bytes -ge 1KB) {
        return "{0:N2} KB" -f ($bytes / 1KB)
    }
    return "$bytes B"
}

function Remove-ArtifactPath([string]$path, [string]$label) {
    $fullPath = if ([System.IO.Path]::IsPathRooted($path)) {
        $path
    } else {
        Join-Path $repoRoot $path
    }

    if (-not (Test-Path -LiteralPath $fullPath)) {
        return
    }

    $sizeBytes = Get-PathSizeBytes $fullPath
    $sizeLabel = Format-Size $sizeBytes
    if ($WhatIf) {
        Write-Host "[WhatIf] Would remove $label ($sizeLabel): $fullPath"
        return
    }

    try {
        Remove-Item -LiteralPath $fullPath -Recurse -Force -ErrorAction Stop
        Write-Host "Removed $label ($sizeLabel): $fullPath"
    } catch {
        Write-Warning "Failed to remove $label ($sizeLabel): $fullPath - $($_.Exception.Message)"
    }
}

Write-Host "Cleaning local artifacts in: $repoRoot"
if ($WhatIf) {
    Write-Host "Running in WhatIf mode (no deletions)."
}

$fixedPaths = @(
    @{ Path = "build"; Label = "root build outputs" },
    @{ Path = ".venv"; Label = "Python virtualenv" },
    @{ Path = "mobile/build"; Label = "mobile Gradle build" },
    @{ Path = "wearos/build"; Label = "wearos Gradle build" },
    @{ Path = "shared/build"; Label = "shared Gradle build" },
    @{ Path = "motion-renderer/build"; Label = "motion-renderer Gradle build" },
    @{ Path = ".pytest_tmp"; Label = "pytest temp dir" },
    @{ Path = ".gradle"; Label = "Gradle cache" }
)

foreach ($entry in $fixedPaths) {
    Remove-ArtifactPath -path $entry.Path -label $entry.Label
}

$rootPatterns = @(
    "_tmp_*",
    ".pytest_*",
    ".codex-tmp-*",
    ".tmp-pytest-*",
    "build.protected-stale*"
)

foreach ($pattern in $rootPatterns) {
    Get-ChildItem -LiteralPath $repoRoot -Directory -Force -Filter $pattern -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-ArtifactPath -path $_.FullName -label $pattern
        }
}

$scratchFiles = @(
    "tmp_test_meta.json",
    "vlm_review_debug.json"
)

foreach ($fileName in $scratchFiles) {
    Remove-ArtifactPath -path $fileName -label "scratch file"
}

Get-ChildItem -LiteralPath $repoRoot -File -Force -Filter "migrated_workout_store_backup_*.json" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-ArtifactPath -path $_.FullName -label "workout store backup"
    }

Get-ChildItem -LiteralPath $repoRoot -File -Force -Filter ".tmp-*.png" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-ArtifactPath -path $_.FullName -label "scratch image"
    }

Write-Host "Cleanup complete."
