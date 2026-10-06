param(
    [string]$MotionJsonPath = "build/exercise_motion/snatch-arranque/cleaned/motion.cleaned.json",
    [string]$Slug = "snatch-arranque",
    [string]$GroundMetadataPath,
    [switch]$KeepStagedAsset
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Resolve-RepoPath {
    param([string]$PathValue)
    $repoRoot = Get-RepoRoot
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $PathValue))
}

$repoRoot = Get-RepoRoot
$sourceJson = Resolve-RepoPath $MotionJsonPath
if (-not (Test-Path -LiteralPath $sourceJson)) {
    throw "Motion JSON not found: $sourceJson"
}

if ([string]::IsNullOrWhiteSpace($GroundMetadataPath)) {
    $defaultGroundMetadataPath = Join-Path (Split-Path -Parent $sourceJson) "ground.metadata.json"
    if (Test-Path -LiteralPath $defaultGroundMetadataPath) {
        $GroundMetadataPath = $defaultGroundMetadataPath
    }
}

$assetDir = Join-Path $repoRoot "wearos\src\debug\assets\exercise_motion\$Slug"
$assetPath = Join-Path $assetDir "motion.cleaned.json"
$groundAssetPath = Join-Path $assetDir "ground.metadata.json"
New-Item -ItemType Directory -Force -Path $assetDir | Out-Null
Copy-Item -LiteralPath $sourceJson -Destination $assetPath -Force
if (-not [string]::IsNullOrWhiteSpace($GroundMetadataPath)) {
    Copy-Item -LiteralPath $GroundMetadataPath -Destination $groundAssetPath -Force
}

try {
    & pwsh (Join-Path $repoRoot "scripts\run_wear_e2e.ps1") -TestClass "WearExerciseAnimationE2ETest"
    if ($LASTEXITCODE -ne 0) {
        throw "WearExerciseAnimationE2ETest failed with exit code $LASTEXITCODE."
    }
}
finally {
    if (-not $KeepStagedAsset) {
        if (Test-Path -LiteralPath $assetPath) {
            Remove-Item -LiteralPath $assetPath -Force
        }
        if (Test-Path -LiteralPath $groundAssetPath) {
            Remove-Item -LiteralPath $groundAssetPath -Force
        }
        $parent = Split-Path -Parent $assetPath
        if ((Test-Path -LiteralPath $parent) -and -not (Get-ChildItem -LiteralPath $parent -Force | Select-Object -First 1)) {
            Remove-Item -LiteralPath $parent -Force
        }
    }
}
