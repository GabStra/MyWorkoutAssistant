param(
    [Parameter(Mandatory = $true)]
    [string]$WorkoutPlanPackageJson,

    [Parameter(Mandatory = $true)]
    [string]$MotionSummaryJson,

    [string]$OutputJson,

    [string]$Python = "python",

    [string]$MovementIdPrefix = "exercise-motion",

    [switch]$StrictIdMatch,

    [switch]$AllowEmpty
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")
$builder = Join-Path $scriptRoot "build_workout_plan_movement_package.py"

$resolvedPackagePath = (Resolve-Path $WorkoutPlanPackageJson).Path
$resolvedSummaryPath = (Resolve-Path $MotionSummaryJson).Path

if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $packageFile = Get-Item -LiteralPath $resolvedPackagePath
    $OutputJson = Join-Path $packageFile.DirectoryName "$($packageFile.BaseName)_with_movements$($packageFile.Extension)"
}

$builderArgs = @(
    $builder,
    "--workout-plan-package-json", $resolvedPackagePath,
    "--motion-summary-json", $resolvedSummaryPath,
    "--output-json", $OutputJson,
    "--movement-id-prefix", $MovementIdPrefix
)

if ($StrictIdMatch) {
    $builderArgs += "--strict-id-match"
}
if ($AllowEmpty) {
    $builderArgs += "--allow-empty"
}

Push-Location $repoRoot
try {
    & $Python @builderArgs
    if ($LASTEXITCODE -ne 0) {
        throw "build_workout_plan_movement_package.py failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
