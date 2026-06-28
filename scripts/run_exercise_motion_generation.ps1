param(
    [string]$ExerciseSlug,
    [string]$ExerciseName,

    [string]$VideoPath,
    [string]$YouTubeUrl,

    [string]$Workspace = "build/exercise_motion",
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [string]$WhamPython = "python",
    [switch]$UseWhamDocker,
    [string]$WhamDockerImage = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "16g",
    [switch]$EstimateLocalOnly,
    [switch]$FullWhamCameraSlam,
    [switch]$SkipSmplify,
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
    [ValidateSet(0, 1, 2)]
    [int]$SpinePoseAxis = 0,
    [switch]$SpinePoseInvert,
    [int]$SpinePoseSmoothingWindow = 9,
    [double]$SpinePoseArmCounterRotation = 1.0,
    [ValidateSet("motion", "legacy-pkl")]
    [string]$SpinePoseMergeMode = "motion",
    [switch]$EnableSpinePose,
    [switch]$NoReuseWhamCache,
    [switch]$SkipMotionTuning,
    [switch]$SkipSegmentDetection,
    [switch]$UseSourceAsIs,
    [double]$SegmentStartSeconds = -1.0,
    [double]$SegmentEndSeconds = -1.0,
    [string]$LlamaCppModel = "C:\\Users\\gabri\\Downloads\\gemma-4-12B-it-heretic-QAT-UD-Q4_K_XL.gguf",
    [string]$LlamaCppMmproj = "C:\\Users\\gabri\\Downloads\\mmproj-BF16.gguf",
    [ValidateSet("cpu", "gpu")]
    [string]$LlamaCppBackend = "gpu",
    [string]$YouTubeCookies,
    [string]$YouTubeCookiesPath,
    [string]$LlamaCppServerCommand = "C:\\Users\\gabri\\Downloads\\llama-c1a1c8ee-cuda13.3-sm89-win-x64\\llama-server.exe",
    [int]$LlamaCppServerPort = 8090,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [int]$LlamaCppNPredict = 768,
    [double]$LlamaCppTemperature = 1.0,
    [Nullable[double]]$LlamaCppTopP = 0.95,
    [Nullable[int]]$LlamaCppTopK = 64,
    [bool]$LlamaCppDisableReasoning = $false,
    [Nullable[int]]$LlamaCppReasoningBudget = 64,
    [string]$LlamaCppReasoningBudgetMessage = "Now stop thinking and return the JSON object.",
    [int]$LlamaCppImageMinTokens = 0,
    [int]$LlamaCppImageMaxTokens = 0,
    [double]$SegmentWindowSeconds = 5.0,
    [double]$SegmentOverlapSeconds = 2.5,
    [int]$SegmentFramesPerWindow = 20,
    [int]$SegmentMaxFrameWidth = 960,
    [double]$SegmentMergeGapSeconds = 2.0,
    [double]$SegmentConfidenceThreshold = 0.45,
    [double]$SegmentMinSegmentSeconds = 2.0,
    [double]$SegmentMaxSegmentSeconds = 20.0,
    [string]$LiteRtModelRepo = "litert-community/gemma-4-E4B-it-litert-lm",
    [string]$LiteRtModelFile = "gemma-4-E4B-it.litertlm",
    [string]$VisionModel = "gemma-4-E4B-it",
    [int]$VisionPort = 8090,
    [ValidateSet("cpu", "gpu", "npu")]
    [string]$LiteRtBackend = "gpu",
    [switch]$UseLiteRt
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
$defaultWhamRepoPath = "C:\Users\gabri\Downloads\WHAM"
if (-not (Test-Path -LiteralPath $defaultWhamRepoPath)) {
    $defaultWhamRepoPath = Join-Path $repoRoot "third_party\WHAM"
}
if ([string]::IsNullOrWhiteSpace($WhamRepoPath)) {
    $WhamRepoPath = $defaultWhamRepoPath
}
if ([string]::IsNullOrWhiteSpace($BodyModelRoot)) {
    $BodyModelRoot = Join-Path $WhamRepoPath "dataset\body_models"
}
$resolvedWhamRepoPath = Resolve-StrictPath $WhamRepoPath
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
$rawWhamDir = Join-Path $exerciseWorkspace "raw\wham"
New-Item -ItemType Directory -Force -Path $inputDir | Out-Null
New-Item -ItemType Directory -Force -Path $rawWhamDir | Out-Null

if (-not [string]::IsNullOrWhiteSpace($VideoPath)) {
    $sourceVideo = Resolve-StrictPath $VideoPath
    $destinationVideo = Join-Path $inputDir ([System.IO.Path]::GetFileName($sourceVideo))
    if ([System.IO.Path]::GetFullPath($sourceVideo) -ne [System.IO.Path]::GetFullPath($destinationVideo)) {
        Copy-Item -LiteralPath $sourceVideo -Destination $destinationVideo -Force
    }
    $resolvedInputVideoPath = [System.IO.Path]::GetFullPath($destinationVideo)
}

if (-not [string]::IsNullOrWhiteSpace($YouTubeUrl)) {
    $youtubeCookiesPath = $YouTubeCookiesPath
    if ([string]::IsNullOrWhiteSpace($youtubeCookiesPath)) {
        $youtubeCookiesPath = $YouTubeCookies
    }
    if (-not [string]::IsNullOrWhiteSpace($youtubeCookiesPath)) {
        $resolvedYouTubeCookiesPath = Resolve-StrictPath $youtubeCookiesPath
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
        -UseLiteRt:$UseLiteRt.IsPresent `
        -LlamaCppModel $LlamaCppModel `
        -LlamaCppMmproj $LlamaCppMmproj `
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
        -MaxSegmentSeconds $SegmentMaxSegmentSeconds `
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

$whamRunnerArgs = @(
    "-WhamRepoPath", $resolvedWhamRepoPath,
    "-InputVideo", $resolvedInputVideoPath,
    "-OutputRoot", $rawWhamDir,
    "-PythonCommand", $WhamPython
)
if ($EstimateLocalOnly -or -not $FullWhamCameraSlam) {
    $whamRunnerArgs += "-EstimateLocalOnly"
}
if (-not $SkipSmplify) {
    $whamRunnerArgs += "-RunSmplify"
}
if ($UseWhamDocker) {
    $whamRunnerArgs += @(
        "-UseDocker",
        "-DockerImage", $WhamDockerImage,
        "-DockerGpus", $WhamDockerGpus,
        "-DockerShmSize", $WhamDockerShmSize
    )
    Write-Host "Running WHAM via Docker."
}
else {
    Write-Host "Running WHAM with local Python: $WhamPython"
}

$whamResultsPkl = Join-Path $rawWhamDir ([System.IO.Path]::GetFileNameWithoutExtension($resolvedInputVideoPath))
$whamResultsPkl = Join-Path $whamResultsPkl "wham_output.pkl"
$whamCachedOutputDir = Split-Path -Parent $whamResultsPkl
if ((Test-Path -LiteralPath $whamResultsPkl) -and -not $NoReuseWhamCache) {
    Write-Host "Reusing cached WHAM output: $whamResultsPkl"
}
else {
    if ($NoReuseWhamCache -and (Test-Path -LiteralPath $whamCachedOutputDir)) {
        Remove-Item -LiteralPath $whamCachedOutputDir -Recurse -Force
    }
    $whamRunnerScript = Join-Path $PSScriptRoot "run_wham_local.ps1"
    & pwsh $whamRunnerScript @whamRunnerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "WHAM stage failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $whamResultsPkl)) {
    throw "WHAM stage finished but did not produce wham_output.pkl at '$whamResultsPkl'."
}

$generateArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "generate",
    "--exercise-slug", $ExerciseSlug,
    "--workspace", $Workspace,
    "--video-path", $resolvedInputVideoPath,
    "--wham-results-pkl", $whamResultsPkl,
    "--body-model-root", $resolvedBodyModelRoot
)
if (-not [string]::IsNullOrWhiteSpace($resolvedWhamRepoPath)) {
    $generateArgs += @("--wham-repo-path", $resolvedWhamRepoPath)
}
if ($EstimateLocalOnly -or -not $FullWhamCameraSlam) {
    $generateArgs += "--wham-estimate-local-only"
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
        "--spinepose-axis", $SpinePoseAxis,
        "--spinepose-smoothing-window", $SpinePoseSmoothingWindow,
        "--spinepose-arm-counter-rotation", ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0}", $SpinePoseArmCounterRotation))
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
$generateInterpreter = $WhamPython
& $generateInterpreter @generateArgs
if ($LASTEXITCODE -ne 0) {
    throw "exercise motion conversion stage failed with exit code $LASTEXITCODE."
}
