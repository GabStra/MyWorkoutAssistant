Param(
    [ValidateSet("wear", "phone", "all")]
    [string]$Target = "all"
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$packageName = "com.gabstra.myworkoutassistant.debug"

# Model prefixes as reported by `adb devices -l` (underscores, not hyphens).
$jobs = @()
if ($Target -eq 'wear' -or $Target -eq 'all') {
    $jobs += [pscustomobject]@{
        ModelPrefixes = @('SM_L', 'SM_R')
        ApkPath = Join-Path $repoRoot 'wearos/build/outputs/apk/debug/wearos-debug.apk'
    }
}
if ($Target -eq 'phone' -or $Target -eq 'all') {
    $jobs += [pscustomobject]@{
        ModelPrefixes = @('SM_S')
        ApkPath = Join-Path $repoRoot 'mobile/build/outputs/apk/debug/mobile-debug.apk'
    }
}

function Install-AndCompile([string]$serial, [string]$apkPath) {
    Write-Host "== $serial"
    adb -s $serial install -r -d $apkPath
    adb -s $serial shell "cmd package compile -m speed -f $packageName"
}

$deviceLines = (adb devices -l) | Select-Object -Skip 1
foreach ($job in $jobs) {
    if (-not (Test-Path $job.ApkPath)) { throw "Missing APK: $($job.ApkPath) (run the assemble task first)" }
    $matched = 0
    foreach ($line in $deviceLines) {
        if ($line -notmatch '^\s*(\S+)\s+device\b') { continue }
        $serial = $Matches[1]
        if ($line -notmatch 'model:(\S+)') { continue }
        $model = $Matches[1]
        $isTargetDevice = $false
        foreach ($prefix in $job.ModelPrefixes) { if ($model -like "$prefix*") { $isTargetDevice = $true } }
        if (-not $isTargetDevice) { continue }
        Install-AndCompile $serial $job.ApkPath
        $matched++
    }
    if ($matched -eq 0) { Write-Warning "No connected device matching $($job.ModelPrefixes -join '/')" }
}
