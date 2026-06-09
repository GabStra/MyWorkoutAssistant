param(
    [Parameter(Mandatory = $true)]
    [string]$ExerciseName,

    [string]$ExerciseId,
    [string]$WorkspaceRoot = "build/exercise_motion",
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [string]$PythonCommand = "python",
    [double]$MaxLoopSeconds = 10.0,
    [int]$ResultsPerQuery = 8,
    [int]$MaxCandidates = 6,
    [int]$VisionCandidatesPerExercise = 5,
    [int]$VisionFramesPerCandidate = 8,
    [int]$VisionDownloadWorkers = 3,
    [int]$VisionLlmWorkers = 1,
    [string]$LiteRtCommand,
    [ValidateSet("cpu", "gpu", "npu")]
    [string]$LiteRtBackend = "gpu",
    [string]$VisionModel = "gemma-4-E4B-it",
    [string]$LiteRtServerUrl = "http://127.0.0.1:9379",
    [int]$LiteRtServerPort = 9379,
    [switch]$NoLiteRtServer,
    [switch]$KeepLiteRtServer,
    [switch]$NoWhamDocker,
    [string]$WhamDockerImage = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "8g",
    [switch]$FullWhamCameraSlam,
    [switch]$RunSmplify,
    [ValidateSet("world", "camera")]
    [string]$WhamCoordinateSpace = "camera",
    [int]$ReviewFrames = 12,
    [double]$MinSelectedScore = 0.55,
    [switch]$SkipSourceSegmentDetection,
    [string]$SegmentBaseUrl,
    [string]$SegmentModel,
    [double]$SegmentWindowSeconds = 5.0,
    [double]$SegmentOverlapSeconds = 2.5,
    [int]$SegmentFramesPerWindow = 20,
    [double]$SegmentConfidenceThreshold = 0.45,
    [double]$SegmentPaddingSeconds = 0.35,
    [double]$SegmentEndPaddingSeconds = 0.35,
    [double]$SegmentMinSeconds = 2.0,
    [double]$SegmentMaxSeconds = 20.0
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function ConvertTo-Slug {
    param([string]$Value)
    $slug = $Value.ToLowerInvariant() -replace "[^a-z0-9]+", "-"
    $slug = $slug.Trim("-")
    if ([string]::IsNullOrWhiteSpace($slug)) {
        return "exercise"
    }
    return $slug
}

function Invoke-PythonModule {
    param([string[]]$Arguments)
    & $PythonCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "python command failed with exit code $LASTEXITCODE."
    }
}

$repoRoot = Get-RepoRoot
$slug = ConvertTo-Slug $ExerciseName
if ([string]::IsNullOrWhiteSpace($ExerciseId)) {
    $ExerciseId = $slug
}

if ([string]::IsNullOrWhiteSpace($WhamRepoPath)) {
    $WhamRepoPath = "C:\Users\gabri\Downloads\WHAM"
    if (-not (Test-Path -LiteralPath $WhamRepoPath)) {
        $WhamRepoPath = Join-Path $repoRoot "third_party\WHAM"
    }
}
if ([string]::IsNullOrWhiteSpace($BodyModelRoot)) {
    $BodyModelRoot = Join-Path $WhamRepoPath "dataset\body_models"
}
if ([string]::IsNullOrWhiteSpace($LiteRtCommand)) {
    $defaultLiteRt = "C:\Users\gabri\miniconda3\Scripts\litert-lm.exe"
    if (Test-Path -LiteralPath $defaultLiteRt) {
        $LiteRtCommand = $defaultLiteRt
    }
}

$exerciseWorkspace = Join-Path $WorkspaceRoot "$slug-e2e"
$bakeWorkspace = Join-Path $exerciseWorkspace "bake-final"
$planPath = Join-Path $exerciseWorkspace "$slug-plan.json"
$candidatesPath = Join-Path $exerciseWorkspace "youtube_candidates.json"
New-Item -ItemType Directory -Force -Path $exerciseWorkspace | Out-Null

$planPayload = @{
    exercises = @(
        @{
            id = $ExerciseId
            name = $ExerciseName
        }
    )
}
$planPayload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $planPath -Encoding UTF8

$youtubeArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "find-youtube-videos",
    "--workout-plan-json", $planPath,
    "--out-json", $candidatesPath,
    "--results-per-query", "$ResultsPerQuery",
    "--max-candidates", "$MaxCandidates",
    "--rank-with-litert",
    "--vision-candidates-per-exercise", "$VisionCandidatesPerExercise",
    "--vision-frames-per-candidate", "$VisionFramesPerCandidate",
    "--vision-download-workers", "$VisionDownloadWorkers",
    "--vision-llm-workers", "$VisionLlmWorkers",
    "--litert-backend", $LiteRtBackend,
    "--vision-model", $VisionModel,
    "--litert-server-url", $LiteRtServerUrl,
    "--litert-server-port", "$LiteRtServerPort"
)
if (-not [string]::IsNullOrWhiteSpace($LiteRtCommand)) {
    $youtubeArgs += @("--litert-command", $LiteRtCommand)
}
if ($NoLiteRtServer) {
    $youtubeArgs += "--no-litert-server"
}
if ($KeepLiteRtServer) {
    $youtubeArgs += "--keep-litert-server"
}

Invoke-PythonModule -Arguments $youtubeArgs

$resolvedWhamRepoPath = Resolve-StrictPath $WhamRepoPath
$resolvedBodyModelRoot = Resolve-StrictPath $BodyModelRoot
$bakeArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "bake-and-rank",
    "--candidates-json", $candidatesPath,
    "--workspace", $bakeWorkspace,
    "--wham-repo-path", $resolvedWhamRepoPath,
    "--body-model-root", $resolvedBodyModelRoot,
    "--max-loop-seconds", "$MaxLoopSeconds",
    "--wham-python", "python",
    "--wham-coordinate-space", $WhamCoordinateSpace,
    "--litert-backend", $LiteRtBackend,
    "--vision-model", $VisionModel,
    "--litert-server-url", $LiteRtServerUrl,
    "--litert-server-port", "$LiteRtServerPort",
    "--review-frames", "$ReviewFrames",
    "--min-selected-score", "$MinSelectedScore",
    "--segment-window-seconds", "$SegmentWindowSeconds",
    "--segment-overlap-seconds", "$SegmentOverlapSeconds",
    "--segment-frames-per-window", "$SegmentFramesPerWindow",
    "--segment-confidence-threshold", "$SegmentConfidenceThreshold",
    "--segment-padding-seconds", "$SegmentPaddingSeconds",
    "--segment-end-padding-seconds", "$SegmentEndPaddingSeconds",
    "--segment-min-seconds", "$SegmentMinSeconds",
    "--segment-max-seconds", "$SegmentMaxSeconds"
)
if (-not $NoWhamDocker) {
    $bakeArgs += @(
        "--use-wham-docker",
        "--wham-docker-image", $WhamDockerImage,
        "--wham-docker-gpus", $WhamDockerGpus,
        "--wham-docker-shm-size", $WhamDockerShmSize
    )
}
if (-not $FullWhamCameraSlam) {
    $bakeArgs += "--estimate-local-only"
}
if ($RunSmplify) {
    $bakeArgs += "--run-smplify"
}
if (-not [string]::IsNullOrWhiteSpace($LiteRtCommand)) {
    $bakeArgs += @("--litert-command", $LiteRtCommand)
}
if (-not [string]::IsNullOrWhiteSpace($SegmentBaseUrl)) {
    $bakeArgs += @("--segment-base-url", $SegmentBaseUrl)
}
if (-not [string]::IsNullOrWhiteSpace($SegmentModel)) {
    $bakeArgs += @("--segment-model", $SegmentModel)
}
if ($NoLiteRtServer) {
    $bakeArgs += "--no-litert-server"
}
if ($KeepLiteRtServer) {
    $bakeArgs += "--keep-litert-server"
}
if ($SkipSourceSegmentDetection) {
    $bakeArgs += "--skip-source-segment-detection"
}

Invoke-PythonModule -Arguments $bakeArgs

$selectionPath = Join-Path $bakeWorkspace "selection_manifest.json"
$selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-Json
Write-Host "Plan JSON: $((Resolve-Path -LiteralPath $planPath).Path)"
Write-Host "YouTube candidates JSON: $((Resolve-Path -LiteralPath $candidatesPath).Path)"
Write-Host "Selection manifest: $((Resolve-Path -LiteralPath $selectionPath).Path)"
if ($selection.selected) {
    Write-Host "Selected review video: $($selection.selected.selectedReviewVideoPath)"
    Write-Host "Selected Wear skeleton: $($selection.selected.selectedWearSkeletonPath)"
    if ($selection.selectedLoopPreviewHtmlPath) {
        Write-Host "Selected loop preview: $((Resolve-Path -LiteralPath $selection.selectedLoopPreviewHtmlPath).Path)"
    }
} else {
    Write-Host "Selected Wear skeleton: none"
}
