param(
    [string]$ExerciseSlug,
    [string]$ExerciseName,

    [string]$VideoPath,
    [string]$YouTubeUrl,

    [string]$Workspace = "build/exercise_motion",
    [string]$GvhmrRepoPath,
    [string]$BodyModelRoot,
    [string]$GvhmrPython = "python",
    [switch]$UseWslForGvhmr,
    [string]$WslDistro = "Ubuntu",
    [string]$WslCondaRoot = "/home/gabriele/miniforge3",
    [string]$WslEnvName = "gvhmr",
    [switch]$SkipSegmentDetection,
    [switch]$UseSourceAsIs,
    [string]$LiteRtModelRepo = "litert-community/gemma-4-E4B-it-litert-lm",
    [string]$LiteRtModelFile = "gemma-4-E4B-it.litertlm",
    [string]$VisionModel = "gemma-4-E4B-it",
    [int]$VisionPort = 8090,
    [ValidateSet("cpu", "gpu", "npu")]
    [string]$LiteRtBackend = "gpu",
    [ValidateSet("incam", "global")]
    [string]$GvhmrCoordinateSpace = "incam",
    [switch]$StaticCamera
)

$ErrorActionPreference = "Stop"

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Get-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Get-ContainerWorkspacePath {
    param(
        [string]$HostPath,
        [string]$RepoRoot
    )

    $resolvedHostPath = [System.IO.Path]::GetFullPath($HostPath)
    $resolvedRepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
    if (-not $resolvedHostPath.StartsWith($resolvedRepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path '$resolvedHostPath' is not inside repo root '$resolvedRepoRoot'."
    }

    $relative = $resolvedHostPath.Substring($resolvedRepoRoot.Length).TrimStart('\')
    $containerRelative = $relative -replace '\\', '/'
    if ([string]::IsNullOrWhiteSpace($containerRelative)) {
        return "/workspace"
    }
    return "/workspace/$containerRelative"
}

function Get-PythonCommand {
    $venvPython = Join-Path (Get-RepoRoot) ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }
    return "python"
}

function Convert-ToExerciseSlug {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return "exercise-motion"
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    $normalized = [System.Text.RegularExpressions.Regex]::Replace($normalized, "[^a-z0-9]+", "-")
    $normalized = $normalized.Trim("-")
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return "exercise-motion"
    }
    return $normalized
}

if ([string]::IsNullOrWhiteSpace($VideoPath) -and [string]::IsNullOrWhiteSpace($YouTubeUrl)) {
    throw "Provide either -VideoPath or -YouTubeUrl."
}

if (-not [string]::IsNullOrWhiteSpace($VideoPath) -and -not [string]::IsNullOrWhiteSpace($YouTubeUrl)) {
    throw "Provide only one of -VideoPath or -YouTubeUrl."
}

if ($SkipSegmentDetection -and $UseSourceAsIs) {
    throw "Use only one of -SkipSegmentDetection or -UseSourceAsIs."
}

$repoRoot = Get-RepoRoot
$defaultGvhmrRepoPath = Join-Path $repoRoot "third_party\GVHMR"
if ([string]::IsNullOrWhiteSpace($GvhmrRepoPath)) {
    $GvhmrRepoPath = $defaultGvhmrRepoPath
}
if ([string]::IsNullOrWhiteSpace($BodyModelRoot)) {
    $BodyModelRoot = Join-Path $GvhmrRepoPath "inputs\checkpoints\body_models"
}
$resolvedGvhmrRepoPath = Resolve-StrictPath $GvhmrRepoPath
$resolvedBodyModelRoot = Resolve-StrictPath $BodyModelRoot
$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Workspace))
$pythonCommand = Get-PythonCommand
$resolvedInputVideoPath = $null

if ([string]::IsNullOrWhiteSpace($ExerciseSlug) -and -not [string]::IsNullOrWhiteSpace($YouTubeUrl)) {
    $titleScript = @"
import json
from yt_dlp import YoutubeDL
info = YoutubeDL({'quiet': True, 'noplaylist': True}).extract_info(r'''$YouTubeUrl''', download=False)
print(json.dumps(info['title'], ensure_ascii=True))
"@
    $resolvedTitle = & $pythonCommand -c $titleScript
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to resolve YouTube title. Ensure yt-dlp is installed in the repo Python environment."
    }
    $resolvedTitleJson = ($resolvedTitle | Select-Object -Last 1).Trim()
    if ([string]::IsNullOrWhiteSpace($resolvedTitleJson)) {
        throw "Resolved an empty YouTube title payload."
    }
    $ExerciseSlug = [System.Text.Json.JsonSerializer]::Deserialize($resolvedTitleJson, [string])
    if ([string]::IsNullOrWhiteSpace($ExerciseSlug)) {
        throw "Resolved an empty YouTube title."
    }
}

if ([string]::IsNullOrWhiteSpace($ExerciseSlug) -and -not [string]::IsNullOrWhiteSpace($VideoPath)) {
    $ExerciseSlug = [System.IO.Path]::GetFileNameWithoutExtension($VideoPath)
}

if ([string]::IsNullOrWhiteSpace($ExerciseSlug)) {
    throw "Could not determine ExerciseSlug."
}

$ExerciseSlug = Convert-ToExerciseSlug $ExerciseSlug

if ([string]::IsNullOrWhiteSpace($ExerciseName)) {
    $ExerciseName = $ExerciseSlug
}

$exerciseWorkspace = Join-Path $workspaceRoot $ExerciseSlug
$inputDir = Join-Path $exerciseWorkspace "input"
$rawGvhmrDir = Join-Path $exerciseWorkspace "raw\gvhmr"
New-Item -ItemType Directory -Force -Path $inputDir | Out-Null
New-Item -ItemType Directory -Force -Path $rawGvhmrDir | Out-Null

if (-not [string]::IsNullOrWhiteSpace($VideoPath)) {
    $sourceVideo = Resolve-StrictPath $VideoPath
    $destinationVideo = Join-Path $inputDir ([System.IO.Path]::GetFileName($sourceVideo))
    if ([System.IO.Path]::GetFullPath($sourceVideo) -ne [System.IO.Path]::GetFullPath($destinationVideo)) {
        Copy-Item -LiteralPath $sourceVideo -Destination $destinationVideo -Force
    }
    $resolvedInputVideoPath = [System.IO.Path]::GetFullPath($destinationVideo)
}

if (-not [string]::IsNullOrWhiteSpace($YouTubeUrl)) {
    $downloadScript = @"
from pathlib import Path
from exercise_motion_pkg.youtube import download_youtube
video_path = download_youtube(r'''$YouTubeUrl''', Path(r'''$inputDir'''))
print(video_path.resolve())
"@
    $downloadedPath = & $pythonCommand -c $downloadScript
    if ($LASTEXITCODE -ne 0) {
        throw "YouTube download failed with exit code $LASTEXITCODE."
    }
    $resolvedInputVideoPath = ($downloadedPath | Select-Object -Last 1).Trim()
    if ([string]::IsNullOrWhiteSpace($resolvedInputVideoPath)) {
        throw "YouTube download did not return a video path."
    }
}

if ($UseSourceAsIs) {
    Write-Host "Using source video as-is. Segment detection and trimming are disabled."
}
elseif (-not $SkipSegmentDetection) {
    $segmentRunnerScript = Join-Path $PSScriptRoot "run_exercise_segment_detection.ps1"
    & pwsh $segmentRunnerScript `
        -VideoPath $resolvedInputVideoPath `
        -ExerciseName $ExerciseName `
        -OutputSlug $ExerciseSlug `
        -Workspace $Workspace `
        -LiteRtModelRepo $LiteRtModelRepo `
        -LiteRtModelFile $LiteRtModelFile `
        -VisionModel $VisionModel `
        -VisionPort $VisionPort `
        -LiteRtBackend $LiteRtBackend
    if ($LASTEXITCODE -ne 0) {
        throw "Exercise segment detection failed with exit code $LASTEXITCODE."
    }

    $segmentDetectionJson = Join-Path $exerciseWorkspace "segment_detection\segment_detection.json"
    if (-not (Test-Path -LiteralPath $segmentDetectionJson)) {
        throw "Segment detection finished but did not produce '$segmentDetectionJson'."
    }

    $segmentPayload = Get-Content -LiteralPath $segmentDetectionJson -Raw | ConvertFrom-Json
    if ($null -eq $segmentPayload.detectedSpan) {
        throw "Segment detection did not produce a usable detected span."
    }

    $trimmedInputVideoPath = Join-Path $inputDir "trimmed_source.mp4"
    $trimArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "trim-video",
        "--video-path", $resolvedInputVideoPath,
        "--out-video", $trimmedInputVideoPath,
        "--start-seconds", "$($segmentPayload.detectedSpan.start_seconds)",
        "--end-seconds", "$($segmentPayload.detectedSpan.end_seconds)"
    )
    & $pythonCommand @trimArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Video trimming failed with exit code $LASTEXITCODE."
    }
    $resolvedInputVideoPath = [System.IO.Path]::GetFullPath($trimmedInputVideoPath)
}

$gvhmrRunnerArgs = @(
    "-GvhmrRepoPath", $resolvedGvhmrRepoPath,
    "-InputVideo", $resolvedInputVideoPath,
    "-OutputRoot", $rawGvhmrDir,
    "-PythonCommand", $GvhmrPython
)
if ($UseWslForGvhmr) {
    $gvhmrRunnerArgs += @(
        "-UseWsl",
        "-WslDistro", $WslDistro,
        "-WslCondaRoot", $WslCondaRoot,
        "-WslEnvName", $WslEnvName
    )
}
if ($StaticCamera) {
    $gvhmrRunnerArgs += "-StaticCamera"
}

$gvhmrCachedOutputDir = Join-Path $rawGvhmrDir ([System.IO.Path]::GetFileNameWithoutExtension($resolvedInputVideoPath))
if (Test-Path -LiteralPath $gvhmrCachedOutputDir) {
    Remove-Item -LiteralPath $gvhmrCachedOutputDir -Recurse -Force
}

$gvhmrRunnerScript = Join-Path $PSScriptRoot "run_gvhmr_local.ps1"
& pwsh $gvhmrRunnerScript @gvhmrRunnerArgs
if ($LASTEXITCODE -ne 0) {
    throw "GVHMR stage failed with exit code $LASTEXITCODE."
}

$gvhmrResultsPt = Join-Path $rawGvhmrDir ([System.IO.Path]::GetFileNameWithoutExtension($resolvedInputVideoPath))
$gvhmrResultsPt = Join-Path $gvhmrResultsPt "hmr4d_results.pt"
if (-not (Test-Path -LiteralPath $gvhmrResultsPt)) {
    throw "GVHMR stage finished but did not produce hmr4d_results.pt at '$gvhmrResultsPt'."
}

$generateArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "generate",
    "--exercise-slug", $ExerciseSlug,
    "--workspace", $Workspace,
    "--video-path", $resolvedInputVideoPath,
    "--gvhmr-results-pt", $gvhmrResultsPt,
    "--body-model-root", $resolvedBodyModelRoot,
    "--gvhmr-coordinate-space", $GvhmrCoordinateSpace
)
if (-not [string]::IsNullOrWhiteSpace($resolvedGvhmrRepoPath)) {
    $generateArgs += @("--gvhmr-repo-path", $resolvedGvhmrRepoPath)
}
if ($StaticCamera) {
    $generateArgs += "--gvhmr-static-camera"
}
$generateInterpreter = $pythonCommand
& $generateInterpreter @generateArgs
if ($LASTEXITCODE -ne 0) {
    throw "exercise motion conversion stage failed with exit code $LASTEXITCODE."
}

$cleanedMotionJson = Join-Path $exerciseWorkspace "cleaned\motion.cleaned.json"
$groundMetadataJson = Join-Path $exerciseWorkspace "cleaned\ground.metadata.json"
$manifestPath = Join-Path $exerciseWorkspace "manifest.json"
$groundArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "ground-metadata",
    "--video-path", $resolvedInputVideoPath,
    "--motion-json", $cleanedMotionJson,
    "--out-json", $groundMetadataJson,
    "--embed-motion-json", $cleanedMotionJson,
    "--manifest-path", $manifestPath,
    "--preview-html", (Join-Path $exerciseWorkspace "preview\\motion_preview.html"),
    "--preview-title", $ExerciseSlug
)
& $pythonCommand @groundArgs
if ($LASTEXITCODE -ne 0) {
    throw "Ground metadata generation failed with exit code $LASTEXITCODE."
}
