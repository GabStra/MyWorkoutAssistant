param(
    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [string]$ExerciseName,
    [string]$OutputSlug,
    [string]$Workspace = "build/exercise_motion",
    [string]$LiteRtModelRepo = "litert-community/gemma-4-E4B-it-litert-lm",
    [string]$LiteRtModelFile = "gemma-4-E4B-it.litertlm",
    [string]$VisionModel = "gemma-4-E4B-it",
    [int]$VisionPort = 8090,
    [ValidateSet("cpu", "gpu", "npu")]
    [string]$LiteRtBackend = "gpu",
    [double]$WindowSeconds = 8.0,
    [double]$OverlapSeconds = 4.0,
    [int]$FramesPerWindow = 6,
    [int]$MaxFrameWidth = 960,
    [double]$MergeGapSeconds = 2.0,
    [double]$ConfidenceThreshold = 0.45,
    [int]$HealthTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Get-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Get-PythonCommand {
    $venvPython = Join-Path (Get-RepoRoot) ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }
    return "python"
}

function Get-LiteRtCommand {
    $repoRoot = Get-RepoRoot
    $venvLiteRt = Join-Path $repoRoot ".venv\Scripts\litert-lm.exe"
    if (Test-Path -LiteralPath $venvLiteRt) {
        return $venvLiteRt
    }
    return "litert-lm"
}

function Test-LiteRtModelImported {
    param(
        [string]$CommandPath,
        [string]$ModelRef
    )

    $output = & $CommandPath list 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to list LiteRT-LM models.`n$output"
    }
    return ($output | Select-String -SimpleMatch $ModelRef) -ne $null
}

function Ensure-LiteRtModelImported {
    param(
        [string]$CommandPath,
        [string]$RepoId,
        [string]$ModelFile,
        [string]$ModelRef
    )

    if (Test-LiteRtModelImported -CommandPath $CommandPath -ModelRef $ModelRef) {
        return
    }

    & $CommandPath import --from-huggingface-repo $RepoId $ModelFile $ModelRef
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to import LiteRT-LM model '$ModelRef' from '$RepoId/$ModelFile'."
    }
}

function Test-PortInUse {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    return $null -ne $connection
}

$repoRoot = Get-RepoRoot
$pythonCommand = Get-PythonCommand
$liteRtCommand = Get-LiteRtCommand
$resolvedVideoPath = Resolve-StrictPath $VideoPath

if ([string]::IsNullOrWhiteSpace($OutputSlug)) {
    $OutputSlug = [System.IO.Path]::GetFileNameWithoutExtension($resolvedVideoPath)
}

$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Workspace))
$outputRoot = Join-Path $workspaceRoot $OutputSlug
$framesDir = Join-Path $outputRoot "segment_detection\frames"
$resultJson = Join-Path $outputRoot "segment_detection\segment_detection.json"
New-Item -ItemType Directory -Force -Path $framesDir | Out-Null

Ensure-LiteRtModelImported `
    -CommandPath $liteRtCommand `
    -RepoId $LiteRtModelRepo `
    -ModelFile $LiteRtModelFile `
    -ModelRef $VisionModel

$pythonArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "detect-segment",
    "--video-path", $resolvedVideoPath,
    "--out-json", $resultJson,
    "--frames-dir", $framesDir,
    "--model", $VisionModel,
    "--litert-command", $liteRtCommand,
    "--litert-backend", $LiteRtBackend,
    "--window-seconds", "$WindowSeconds",
    "--overlap-seconds", "$OverlapSeconds",
    "--frames-per-window", "$FramesPerWindow",
    "--max-frame-width", "$MaxFrameWidth",
    "--merge-gap-seconds", "$MergeGapSeconds",
    "--confidence-threshold", "$ConfidenceThreshold"
)
if (-not [string]::IsNullOrWhiteSpace($ExerciseName)) {
    $pythonArgs += @("--exercise-name", $ExerciseName)
}

& $pythonCommand @pythonArgs
if ($LASTEXITCODE -ne 0) {
    throw "exercise segment detection failed with exit code $LASTEXITCODE."
}
