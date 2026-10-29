param(
    [string]$ExerciseSlug,
    [string]$ExerciseName,

    [string]$VideoPath,
    [string]$YouTubeUrl,

    [string]$Workspace = "build/exercise_motion",
    [string]$BodyModelRoot,
    [switch]$FastProfile,
    [bool]$UseReconstructionDocker = $true,
    [string]$ReconstructionDockerImage = "myworkoutassistant/gvhmr:torch2.3-cu121",
    [string]$ReconstructionDockerGpus = "all",
    [string]$ReconstructionDockerShmSize = "16g",
    [double]$ReconstructionTimeoutSeconds = 0.0,
    [switch]$SkipSpinePose,
    [string]$SpinePoseJsonDir,
    [string]$SpinePoseCommand,
    [string]$SpinePoseOutputDir,
    [string]$SpinePoseMode = "large",
    [string]$SpinePoseModelVersion = "v2",
    [string]$SpinePoseDevice = "cuda",
    [switch]$NoReuseSpinePoseCache,
    [double]$SpinePoseGain = 1.0,
    [double]$SpinePoseMaxDegrees = 35.0,
    [switch]$SpinePoseInvert,
    [int]$SpinePoseSmoothingWindow = 9,
    [ValidateSet("motion")]
    [string]$SpinePoseMergeMode = "motion",
    [switch]$EnableSpinePose,
    [switch]$NoReuseReconstructionCache,
    [switch]$SkipMotionTuning,
    [switch]$SkipSegmentDetection,
    [switch]$UseSourceAsIs,
    [double]$SegmentStartSeconds = -1.0,
    [double]$SegmentEndSeconds = -1.0,
    [string]$LlamaCppModel = (Join-Path (Split-Path -Parent $PSScriptRoot) "models/Qwen3.5-9B-Q6_K/Qwen3.5-9B-Q6_K.gguf"),
    [string]$LlamaCppMmproj = (Join-Path (Split-Path -Parent $PSScriptRoot) "models/Qwen3.5-9B-Q6_K/mmproj-BF16.gguf"),
    [AllowEmptyString()]
    [string]$LlamaCppMtpModel = "",
    [int]$LlamaCppSpecDraftNMax = 3,
    [ValidateSet("cpu", "gpu")]
    [string]$LlamaCppBackend = "gpu",
    [Alias("YouTubeCookies")]
    [string]$YouTubeCookiesPath,
    [string]$LlamaCppServerCommand = "C:\\llama.cpp\\build-master\\bin\\Release\\llama-server.exe",
    [int]$LlamaCppServerPort = 8090,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [int]$LlamaCppNPredict = 512,
    [double]$LlamaCppTemperature = 0.0,
    [Nullable[double]]$LlamaCppTopP = 1.0,
    [Nullable[int]]$LlamaCppTopK = 0,
    [bool]$LlamaCppDisableReasoning = $false,
    [Nullable[int]]$LlamaCppReasoningBudget = 64,
    [string]$LlamaCppReasoningBudgetMessage = "Now stop thinking and return the JSON object.",
    [int]$LlamaCppImageMinTokens = 1024,
    [int]$LlamaCppImageMaxTokens = 2048,
    [double]$SegmentWindowSeconds = 5.0,
    [double]$SegmentOverlapSeconds = 2.5,
    [int]$SegmentFramesPerWindow = 20,
    [int]$SegmentMaxFrameWidth = 960,
    [double]$SegmentMergeGapSeconds = 2.0,
    [double]$SegmentConfidenceThreshold = 0.45,
    [double]$SegmentMinSegmentSeconds = 2.0,
    [double]$SegmentMaxSegmentSeconds = 20.0
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

function Test-PythonRuntime {
    param([string]$PythonCommand)
    try {
        & $PythonCommand -c "import encodings, sys; import torch, smplx, joblib; print(sys.executable)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Get-PythonCommand {
    if (-not [string]::IsNullOrWhiteSpace($env:EXERCISE_MOTION_PYTHON)) {
        if (-not (Test-PythonRuntime $env:EXERCISE_MOTION_PYTHON)) {
            throw "EXERCISE_MOTION_PYTHON does not point to a Python runtime with torch, smplx, and joblib."
        }
        return $env:EXERCISE_MOTION_PYTHON
    }
    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = if ($pythonCommand.Source) { $pythonCommand.Source } else { $pythonCommand.Path }
    if (-not (Test-PythonRuntime $pythonPath)) {
        throw "Could not find a Python runtime with torch, smplx, and joblib."
    }
    return $pythonPath
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

$manualSegmentRequested = ($SegmentStartSeconds -ge 0.0) -or ($SegmentEndSeconds -ge 0.0)
if ($manualSegmentRequested) {
    if ($UseSourceAsIs -or $SkipSegmentDetection) {
        throw "Manual segment seconds cannot be combined with -UseSourceAsIs or -SkipSegmentDetection."
    }
    if ($SegmentStartSeconds -lt 0.0 -or $SegmentEndSeconds -lt 0.0) {
        throw "Provide both -SegmentStartSeconds and -SegmentEndSeconds when manually trimming."
    }
    if ($SegmentEndSeconds -le $SegmentStartSeconds) {
        throw "-SegmentEndSeconds must be greater than -SegmentStartSeconds."
    }
}

$repoRoot = Get-RepoRoot
if (-not $UseReconstructionDocker) {
    throw "GVHMR generation requires Docker; UseReconstructionDocker is enabled by default."
}
if ([string]::IsNullOrWhiteSpace($BodyModelRoot)) {
    $BodyModelRoot = Join-Path $repoRoot "third_party\GVHMR\inputs\checkpoints\body_models"
}
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
$rawReconstructionDir = Join-Path $exerciseWorkspace "raw\reconstruction"
New-Item -ItemType Directory -Force -Path $inputDir | Out-Null
New-Item -ItemType Directory -Force -Path $rawReconstructionDir | Out-Null

if (-not [string]::IsNullOrWhiteSpace($VideoPath)) {
    $sourceVideo = Resolve-StrictPath $VideoPath
    $destinationVideo = Join-Path $inputDir ([System.IO.Path]::GetFileName($sourceVideo))
    if ([System.IO.Path]::GetFullPath($sourceVideo) -ne [System.IO.Path]::GetFullPath($destinationVideo)) {
        Copy-Item -LiteralPath $sourceVideo -Destination $destinationVideo -Force
    }
    $resolvedInputVideoPath = [System.IO.Path]::GetFullPath($destinationVideo)
}

if (-not [string]::IsNullOrWhiteSpace($YouTubeUrl)) {
    if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
        $resolvedYouTubeCookiesPath = Resolve-StrictPath $YouTubeCookiesPath
        if (-not (Test-Path -LiteralPath $resolvedYouTubeCookiesPath)) {
            throw "YouTube cookies file not found: $resolvedYouTubeCookiesPath"
        }
    } else {
        $resolvedYouTubeCookiesPath = ""
    }
    if ([string]::IsNullOrWhiteSpace($resolvedYouTubeCookiesPath)) {
        $downloadCookiesArg = "None"
    }
    else {
        $downloadCookiesArg = "Path(r'''$resolvedYouTubeCookiesPath''')"
    }

    $downloadScript = @"
from pathlib import Path
from exercise_motion_pkg.youtube import download_youtube
video_path = download_youtube(
    r'''$YouTubeUrl''',
    Path(r'''$inputDir'''),
    $downloadCookiesArg
)
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
elseif ($manualSegmentRequested) {
    Write-Host "Using manual video segment $SegmentStartSeconds-$SegmentEndSeconds seconds. Segment detection is disabled."
    $trimmedInputVideoPath = Join-Path $inputDir "trimmed_source.mp4"
    $trimArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "trim-video",
        "--video-path", $resolvedInputVideoPath,
        "--out-video", $trimmedInputVideoPath,
        "--start-seconds", "$SegmentStartSeconds",
        "--end-seconds", "$SegmentEndSeconds"
    )
    & $pythonCommand @trimArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Video trimming failed with exit code $LASTEXITCODE."
    }
    $resolvedInputVideoPath = [System.IO.Path]::GetFullPath($trimmedInputVideoPath)
}
elseif (-not $SkipSegmentDetection) {
    $segmentRunnerScript = Join-Path $PSScriptRoot "run_exercise_segment_detection.ps1"
  & pwsh $segmentRunnerScript `
        -VideoPath $resolvedInputVideoPath `
        -ExerciseName $ExerciseName `
        -OutputSlug $ExerciseSlug `
        -Workspace $Workspace `
        -LlamaCppModel $LlamaCppModel `
        -LlamaCppMmproj $LlamaCppMmproj `
        -LlamaCppMtpModel $LlamaCppMtpModel `
        -LlamaCppSpecDraftNMax $LlamaCppSpecDraftNMax `
        -LlamaCppBackend $LlamaCppBackend `
        -LlamaCppServerCommand $LlamaCppServerCommand `
        -LlamaCppServerPort $LlamaCppServerPort `
        -LlamaCppBaseUrl $LlamaCppBaseUrl `
        -LlamaCppNPredict $LlamaCppNPredict `
        -LlamaCppTemperature $LlamaCppTemperature `
        -LlamaCppTopP $LlamaCppTopP `
        -LlamaCppTopK $LlamaCppTopK `
        -LlamaCppDisableReasoning $LlamaCppDisableReasoning `
        -LlamaCppReasoningBudget $LlamaCppReasoningBudget `
        -LlamaCppReasoningBudgetMessage $LlamaCppReasoningBudgetMessage `
        -LlamaCppImageMinTokens $LlamaCppImageMinTokens `
        -LlamaCppImageMaxTokens $LlamaCppImageMaxTokens `
        -WindowSeconds $SegmentWindowSeconds `
        -OverlapSeconds $SegmentOverlapSeconds `
        -FramesPerWindow $SegmentFramesPerWindow `
        -MaxFrameWidth $SegmentMaxFrameWidth `
        -MergeGapSeconds $SegmentMergeGapSeconds `
        -ConfidenceThreshold $SegmentConfidenceThreshold `
        -MinSegmentSeconds $SegmentMinSegmentSeconds `
        -MaxSegmentSeconds $SegmentMaxSegmentSeconds
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

$reconstructionResultsPkl = Join-Path $rawReconstructionDir ([System.IO.Path]::GetFileNameWithoutExtension($resolvedInputVideoPath))
$reconstructionResultsPkl = Join-Path $reconstructionResultsPkl "reconstruction_output.pkl"
$reconstructionCachedOutputDir = Split-Path -Parent $reconstructionResultsPkl
if ((Test-Path -LiteralPath $reconstructionResultsPkl) -and -not $NoReuseReconstructionCache) {
    Write-Host "Reusing cached GVHMR output: $reconstructionResultsPkl"
}
else {
    if ($NoReuseReconstructionCache -and (Test-Path -LiteralPath $reconstructionCachedOutputDir)) {
        Remove-Item -LiteralPath $reconstructionCachedOutputDir -Recurse -Force
    }
    Write-Host "Running GVHMR reconstruction via Docker."
    $gvhmrArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "gvhmr-run",
        "--input-video", $resolvedInputVideoPath,
        "--output-root", $rawReconstructionDir,
        "--logs-dir", (Join-Path $Workspace "logs"),
        "--reconstruction-docker-image", $ReconstructionDockerImage,
        "--reconstruction-docker-gpus", $ReconstructionDockerGpus,
        "--reconstruction-docker-shm-size", $ReconstructionDockerShmSize,
        "--timeout-seconds", "$ReconstructionTimeoutSeconds"
    )
    & $pythonCommand @gvhmrArgs
    if ($LASTEXITCODE -ne 0) {
        throw "GVHMR stage failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $reconstructionResultsPkl)) {
    throw "Motion reconstruction finished but did not produce the expected output at '$reconstructionResultsPkl'."
}

$generateArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "generate",
    "--exercise-slug", $ExerciseSlug,
    "--workspace", $Workspace,
    "--video-path", $resolvedInputVideoPath,
    "--reconstruction-results-pkl", $reconstructionResultsPkl,
    "--body-model-root", $resolvedBodyModelRoot,
    "--motion-reconstructor", "gvhmr"
)
if ($FastProfile) {
    # GVHMR + refinement reduced to the source-guided vertical trajectory
    # repair (moon-gravity fix); the deterministic gates still run.
    $generateArgs += "--structural-refinement-vertical-only"
}
if ($SkipMotionTuning) {
    $generateArgs += "--skip-motion-tuning"
}
if ($SkipSpinePose -or -not $EnableSpinePose) {
    $generateArgs += "--skip-spinepose"
}
else {
    $generateArgs += @(
        "--spinepose-merge-mode", $SpinePoseMergeMode,
        "--spinepose-mode", $SpinePoseMode,
        "--spinepose-model-version", $SpinePoseModelVersion,
        "--spinepose-device", $SpinePoseDevice,
        "--spinepose-gain", ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0}", $SpinePoseGain)),
        "--spinepose-max-degrees", ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0}", $SpinePoseMaxDegrees)),
        "--spinepose-smoothing-window", $SpinePoseSmoothingWindow
    )
    $generateArgs += "--enable-spinepose"
    if (-not [string]::IsNullOrWhiteSpace($SpinePoseJsonDir)) {
        $resolvedSpinePoseJsonDir = Resolve-StrictPath $SpinePoseJsonDir
        $generateArgs += @("--spinepose-json-dir", $resolvedSpinePoseJsonDir)
    }
    if (-not [string]::IsNullOrWhiteSpace($SpinePoseCommand)) {
        $generateArgs += @("--spinepose-command", $SpinePoseCommand)
    }
    if (-not [string]::IsNullOrWhiteSpace($SpinePoseOutputDir)) {
        $generateArgs += @("--spinepose-output-dir", $SpinePoseOutputDir)
    }
    if ($SpinePoseInvert) {
        $generateArgs += "--spinepose-invert"
    }
    if ($NoReuseSpinePoseCache) {
        $generateArgs += "--no-spinepose-cache"
    }
}
& $pythonCommand @generateArgs
if ($LASTEXITCODE -ne 0) {
    throw "exercise motion conversion stage failed with exit code $LASTEXITCODE."
}
