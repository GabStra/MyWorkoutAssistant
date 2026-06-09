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
    [string]$WhamDockerImage = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "8g",
    [switch]$EstimateLocalOnly,
    [switch]$RunSmplify,
    [switch]$SkipSegmentDetection,
    [switch]$UseSourceAsIs,
    [double]$SegmentStartSeconds = -1.0,
    [double]$SegmentEndSeconds = -1.0,
    [string]$LlamaCppCommand = "C:\\Users\\gabri\\Downloads\\llama-b9555-bin-win-cuda-13.3-x64\\llama-mtmd-cli.exe",
    [string]$LlamaCppModel = "C:\\Users\\gabri\\Downloads\\Qwen3VL-8B-Instruct-Q4_K_M.gguf",
    [string]$LlamaCppMmproj = "C:\\Users\\gabri\\Downloads\\mmproj-Qwen3VL-8B-Instruct-F16.gguf",
    [ValidateSet("cpu", "gpu")]
    [string]$LlamaCppBackend = "gpu",
    [switch]$UseLlamaCppServer,
    [string]$LlamaCppServerCommand,
    [int]$LlamaCppServerPort = 8090,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [int]$LlamaCppNPredict = 768,
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
    [switch]$UseLiteRt,
    [ValidateSet("world", "camera")]
    [string]$WhamCoordinateSpace = "camera"
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
        & $venvPython -c "import encodings" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $venvPython
        }
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
        -LlamaCppCommand $LlamaCppCommand `
        -LlamaCppModel $LlamaCppModel `
        -LlamaCppMmproj $LlamaCppMmproj `
        -LlamaCppBackend $LlamaCppBackend `
        -UseLlamaCppServer:$UseLlamaCppServer.IsPresent `
        -LlamaCppServerCommand $LlamaCppServerCommand `
        -LlamaCppServerPort $LlamaCppServerPort `
        -LlamaCppBaseUrl $LlamaCppBaseUrl `
        -LlamaCppNPredict $LlamaCppNPredict `
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
if ($EstimateLocalOnly) {
    $whamRunnerArgs += "-EstimateLocalOnly"
}
if ($RunSmplify) {
    $whamRunnerArgs += "-RunSmplify"
}
if ($UseWhamDocker) {
    Write-Host "Note: -UseWhamDocker is deprecated for this script; WHAM is always executed via Docker."
}
$whamRunnerArgs += @(
    "-UseDocker",
    "-DockerImage", $WhamDockerImage,
    "-DockerGpus", $WhamDockerGpus,
    "-DockerShmSize", $WhamDockerShmSize
)
Write-Host "Running WHAM via Docker."

$whamCachedOutputDir = Join-Path $rawWhamDir ([System.IO.Path]::GetFileNameWithoutExtension($resolvedInputVideoPath))
if (Test-Path -LiteralPath $whamCachedOutputDir) {
    Remove-Item -LiteralPath $whamCachedOutputDir -Recurse -Force
}

$whamRunnerScript = Join-Path $PSScriptRoot "run_wham_local.ps1"
& pwsh $whamRunnerScript @whamRunnerArgs
if ($LASTEXITCODE -ne 0) {
    throw "WHAM stage failed with exit code $LASTEXITCODE."
}

$whamResultsPkl = Join-Path $rawWhamDir ([System.IO.Path]::GetFileNameWithoutExtension($resolvedInputVideoPath))
$whamResultsPkl = Join-Path $whamResultsPkl "wham_output.pkl"
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
    "--body-model-root", $resolvedBodyModelRoot,
    "--wham-coordinate-space", $WhamCoordinateSpace
)
if (-not [string]::IsNullOrWhiteSpace($resolvedWhamRepoPath)) {
    $generateArgs += @("--wham-repo-path", $resolvedWhamRepoPath)
}
if ($EstimateLocalOnly) {
    $generateArgs += "--wham-estimate-local-only"
}
$generateInterpreter = $WhamPython
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
& $generateInterpreter @groundArgs
if ($LASTEXITCODE -ne 0) {
    throw "Ground metadata generation failed with exit code $LASTEXITCODE."
}
