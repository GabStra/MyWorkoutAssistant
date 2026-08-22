#Requires -Version 5.1

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
)

function Test-IsAdmin {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Start-AdminElevation {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-RepoRoot", "`"$RepoRoot`""
    )
    Start-Process -FilePath "pwsh" -ArgumentList $arguments -Verb RunAs -Wait | Out-Null
}

function Reset-PathAcl {
    param(
        [string]$Path
    )

    $userPrincipal = "$env:USERDOMAIN\$env:USERNAME"

    & takeown /f $Path /r /d y 2>$null
    & icacls $Path /reset /t /c 2>$null
    & icacls $Path /grant:r "Administrators:(F)" /t /c 2>$null
    & icacls $Path /grant:r "SYSTEM:(F)" /t /c 2>$null
    & icacls $Path /grant:r "${userPrincipal}:(F)" /t /c 2>$null
    & attrib -r -s -h $Path /s /d 2>$null
}

function Remove-LockedPath {
    param(
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $true
    }

    Reset-PathAcl -Path $Path

    $empty = Join-Path $env:TEMP "mwa_empty_$([Guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $empty -Force | Out-Null
    $null = robocopy $empty $Path /mir /r:1 /w:1 /nfl /ndl /njh /njs
    Remove-Item -LiteralPath $empty -Force -Recurse -ErrorAction SilentlyContinue

    $null = cmd /c "rmdir /s /q `"$Path`" 2>nul"
    Remove-Item -LiteralPath $Path -Force -Recurse -ErrorAction SilentlyContinue

    return -not (Test-Path -LiteralPath $Path)
}

if (-not (Test-IsAdmin)) {
    Write-Host "Re-launching cleanup with administrator privileges..."
    Start-AdminElevation
    exit 0
}

Write-Host "Running locked-artifact cleanup as administrator in: $RepoRoot"

$patterns = @(
    "build",
    ".pytest_tmp",
    "_tmp_*",
    ".pytest_*",
    ".pytest-*",
    ".codex-tmp-*",
    ".tmp-pytest-*",
    "build.protected-stale*"
)

$targets = New-Object System.Collections.Generic.List[string]
$seen = @{}

foreach ($pattern in $patterns) {
    Get-ChildItem -LiteralPath $RepoRoot -Directory -Force -Filter $pattern -ErrorAction SilentlyContinue |
        ForEach-Object {
            if (-not $seen.ContainsKey($_.FullName)) {
                $seen[$_.FullName] = $true
                [void]$targets.Add($_.FullName)
            }
        }
}

$failed = New-Object System.Collections.Generic.List[string]
foreach ($target in ($targets | Sort-Object { $_.Length } -Descending)) {
    Write-Host "Removing $target ..."
    if (Remove-LockedPath -Path $target) {
        Write-Host "  removed"
    } else {
        Write-Host "  FAILED"
        [void]$failed.Add($target)
    }
}

if ($failed.Count -gt 0) {
    Write-Warning "Some paths could not be removed:"
    $failed | ForEach-Object { Write-Warning "  $_" }
    exit 1
}

Write-Host "Locked-artifact cleanup complete."
exit 0
