param(
    [Parameter(Mandatory = $true)]
    [string]$ExerciseName,

    [string]$ExerciseId,
    [string]$WorkspaceRoot = "build/exercise_motion",
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [string]$YouTubeCookiesPath,
    [string]$PythonCommand = "python",
    [int]$ResultsPerQuery = 25,
    [int]$YoutubeSearchEmptyRetries = 5,
    [int]$MaxCandidates = 12,
    [int]$MetadataCandidatePoolSize = 36,
    [switch]$UseDeepSeekQueryPlanner,
    [string]$DeepSeekApiKey,
    [string]$DeepSeekBaseUrl = "https://api.deepseek.com",
    [string]$DeepSeekModel = "deepseek-v4-flash",
    [int]$DeepSeekMaxQueries = 4,
    [int]$VisionCandidatesPerExercise = 12,
    [int]$VisionFramesPerCandidate = 6,
    [int]$VisionMaxChunksPerCandidate = 5,
    [int]$VisionDownloadWorkers = 3,
    [int]$VisionLlmWorkers = 3,
    [switch]$SkipVisionRanking,
    [switch]$SemanticGateWithLiteRt,
    [switch]$SkipSemanticGate,
    [Nullable[int]]$SemanticGateCandidatesPerExercise = 12,
    [double]$SemanticGateMinScore = 0.55,
    [double]$SemanticGateTimeoutSeconds = 0.0,
    [switch]$PosePrefilter,
    [switch]$SkipPosePrefilter,
    [string]$PosePrefilterModel = "yolo26x-pose.pt",
    [Nullable[int]]$PosePrefilterCandidatesPerExercise = 12,
    [double]$PosePrefilterSampleFps = 1.0,
    [double]$PosePrefilterMaxSeconds = 32.0,
    [double]$PosePrefilterWindowSeconds = 8.0,
    [double]$PosePrefilterOverlapSeconds = 4.0,
    [double]$PosePrefilterMinScore = 0.45,
    [int]$PosePrefilterWorkers = 3,
    [int]$FallbackCandidates = 5,
    [switch]$NoWhamDocker,
    [string]$WhamDockerImage = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "16g",
    [switch]$FullWhamCameraSlam,
    [switch]$SkipSmplify,
    [switch]$NoReuseWhamCache,
    [switch]$SkipMotionTuning,
    [switch]$SkipSourceSegmentDetection,
    [string]$SegmentBaseUrl,
    [string]$SegmentModel,
    [Nullable[double]]$SegmentWindowSeconds,
    [Nullable[double]]$SegmentOverlapSeconds,
    [Nullable[int]]$SegmentFramesPerWindow,
    [double]$SegmentConfidenceThreshold = 0.45,
    [double]$SegmentPaddingSeconds = 0.35,
    [double]$SegmentEndPaddingSeconds = 0.35,
    [double]$SegmentMinSeconds = 2.0,
    [double]$SegmentMaxSeconds = 20.0,
    [switch]$RankPreviewVariants,
    [switch]$AdaptivePreviewSettings,
    [switch]$SkipAdaptivePreviewSettings,
    [int]$MaxAdaptivePreviewSettings = 1,
    [switch]$SkipPreviewVariantRanking,
    [switch]$ClassifySupportDominance,
    [switch]$SkipSupportDominanceClassification,
    [int]$ReviewFrames = 6,
    [int]$MaxReviewWindows = 3,
    [double]$MinSelectedScore = 0.55,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [string]$LlamaCppModel = "C:\Users\gabri\Downloads\Qwen3VL-8B-Instruct-Q4_K_M.gguf",
    [string]$LlamaCppCommand,
    [string]$LlamaCppServerCommand,
    [string]$LlamaCppMmproj = "C:\Users\gabri\Downloads\mmproj-Qwen3VL-8B-Instruct-F16.gguf",
    [string]$LlamaCppBackend = "gpu",
    [int]$LlamaCppNPredict = 768,
    [Nullable[int]]$LlamaCppImageMinTokens,
    [Nullable[int]]$LlamaCppImageMaxTokens,
    [switch]$NoLlamaCppAutoStartServer,
    [double]$LlamaCppServerStartupTimeoutSeconds = 180.0,
    [double]$LlamaCppRequestTimeoutSeconds = 90.0
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
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $YouTubeCookiesPath = Resolve-StrictPath $YouTubeCookiesPath
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
    "--youtube-search-empty-retries", "$YoutubeSearchEmptyRetries",
    "--max-candidates", "$MaxCandidates",
    "--metadata-candidate-pool-size", "$MetadataCandidatePoolSize",
    "--vision-candidates-per-exercise", "$VisionCandidatesPerExercise",
    "--vision-max-chunks-per-candidate", "$VisionMaxChunksPerCandidate",
    "--vision-download-workers", "$VisionDownloadWorkers",
    "--vision-llm-workers", "$VisionLlmWorkers"
)
if (-not $SkipVisionRanking) {
    $youtubeArgs += "--rank-with-vision"
}
if ($SemanticGateWithLiteRt -or -not $SkipSemanticGate) {
    $youtubeArgs += @(
        "--semantic-gate-with-litert",
        "--semantic-gate-min-score", "$SemanticGateMinScore",
        "--semantic-gate-timeout-seconds", "$SemanticGateTimeoutSeconds"
    )
    if ($SemanticGateCandidatesPerExercise.HasValue) {
        $youtubeArgs += @("--semantic-gate-candidates-per-exercise", "$($SemanticGateCandidatesPerExercise.Value)")
    }
}
if ($LlamaCppRequestTimeoutSeconds -gt 0) {
    $youtubeArgs += @("--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds")
}
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $youtubeArgs += @("--youtube-cookies", $YouTubeCookiesPath)
}
if ($UseDeepSeekQueryPlanner) {
    $youtubeArgs += @(
        "--use-deepseek-query-planner",
        "--deepseek-base-url", $DeepSeekBaseUrl,
        "--deepseek-model", $DeepSeekModel,
        "--deepseek-max-queries", "$DeepSeekMaxQueries"
    )
    if (-not [string]::IsNullOrWhiteSpace($DeepSeekApiKey)) {
        $youtubeArgs += @("--deepseek-api-key", $DeepSeekApiKey)
    }
}
if ($VisionFramesPerCandidate -gt 0) {
    $youtubeArgs += @("--vision-frames-per-candidate", "$VisionFramesPerCandidate")
}
if ($PosePrefilter -or -not $SkipPosePrefilter) {
    $youtubeArgs += @(
        "--pose-prefilter",
        "--pose-prefilter-model", $PosePrefilterModel,
        "--pose-prefilter-sample-fps", "$PosePrefilterSampleFps",
        "--pose-prefilter-max-seconds", "$PosePrefilterMaxSeconds",
        "--pose-prefilter-window-seconds", "$PosePrefilterWindowSeconds",
        "--pose-prefilter-overlap-seconds", "$PosePrefilterOverlapSeconds",
        "--pose-prefilter-min-score", "$PosePrefilterMinScore",
        "--pose-prefilter-workers", "$PosePrefilterWorkers"
    )
    if ($PosePrefilterCandidatesPerExercise.HasValue) {
        $youtubeArgs += @("--pose-prefilter-candidates-per-exercise", "$($PosePrefilterCandidatesPerExercise.Value)")
    }
}

Invoke-PythonModule -Arguments $youtubeArgs

$resolvedWhamRepoPath = Resolve-StrictPath $WhamRepoPath
$resolvedBodyModelRoot = Resolve-StrictPath $BodyModelRoot
$bakeArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "bake-and-rank",
    "--candidates-json", $candidatesPath,
    "--fallback-candidates", "$FallbackCandidates",
    "--workspace", $bakeWorkspace,
    "--wham-repo-path", $resolvedWhamRepoPath,
    "--body-model-root", $resolvedBodyModelRoot,
    "--wham-python", "python",
    "--segment-confidence-threshold", "$SegmentConfidenceThreshold",
    "--segment-padding-seconds", "$SegmentPaddingSeconds",
    "--segment-end-padding-seconds", "$SegmentEndPaddingSeconds",
    "--segment-min-seconds", "$SegmentMinSeconds",
    "--segment-max-seconds", "$SegmentMaxSeconds",
    "--review-frames", "$ReviewFrames",
    "--max-review-windows", "$MaxReviewWindows",
    "--min-selected-score", "$MinSelectedScore",
    "--llama-cpp-base-url", $LlamaCppBaseUrl,
    "--llama-cpp-model", $LlamaCppModel,
    "--llama-cpp-mmproj", $LlamaCppMmproj,
    "--llama-cpp-backend", $LlamaCppBackend,
    "--llama-cpp-n-predict", "$LlamaCppNPredict",
    "--llama-cpp-server-startup-timeout-seconds", "$LlamaCppServerStartupTimeoutSeconds",
    "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds"
)
if ($RankPreviewVariants -and -not $SkipPreviewVariantRanking) {
    $bakeArgs += "--rank-preview-variants"
}
if ($AdaptivePreviewSettings -or (-not $SkipAdaptivePreviewSettings -and -not $RankPreviewVariants)) {
    $bakeArgs += @(
        "--adaptive-preview-settings",
        "--max-adaptive-preview-settings", "$MaxAdaptivePreviewSettings"
    )
}
if (-not $ClassifySupportDominance -or $SkipSupportDominanceClassification) {
    $bakeArgs += "--no-classify-support-dominance"
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppCommand)) {
    $bakeArgs += @("--llama-cpp-command", $LlamaCppCommand)
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppServerCommand)) {
    $bakeArgs += @("--llama-cpp-server-command", $LlamaCppServerCommand)
}
if ($LlamaCppImageMinTokens.HasValue) {
    $bakeArgs += @("--llama-cpp-image-min-tokens", "$LlamaCppImageMinTokens")
}
if ($LlamaCppImageMaxTokens.HasValue) {
    $bakeArgs += @("--llama-cpp-image-max-tokens", "$LlamaCppImageMaxTokens")
}
if ($NoLlamaCppAutoStartServer) {
    $bakeArgs += "--no-llama-cpp-auto-start-server"
}
if ($SegmentWindowSeconds.HasValue) {
    $bakeArgs += @("--segment-window-seconds", "$SegmentWindowSeconds")
}
if ($SegmentOverlapSeconds.HasValue) {
    $bakeArgs += @("--segment-overlap-seconds", "$SegmentOverlapSeconds")
}
if ($SegmentFramesPerWindow.HasValue) {
    $bakeArgs += @("--segment-frames-per-window", "$SegmentFramesPerWindow")
}
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
if ($SkipSmplify) {
    $bakeArgs += "--skip-smplify"
}
if ($NoReuseWhamCache) {
    $bakeArgs += "--no-reuse-wham-cache"
}
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $bakeArgs += @("--youtube-cookies", $YouTubeCookiesPath)
}
if ($SkipMotionTuning) {
    $bakeArgs += "--skip-motion-tuning"
}
if (-not [string]::IsNullOrWhiteSpace($SegmentBaseUrl)) {
    $bakeArgs += @("--segment-base-url", $SegmentBaseUrl)
}
if (-not [string]::IsNullOrWhiteSpace($SegmentModel)) {
    $bakeArgs += @("--segment-model", $SegmentModel)
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
    Write-Host "Wear skeleton JSON: $($selection.selected.selectedWearSkeletonPath)"
    if ($selection.selectedPreviewHtmlPath) {
        Write-Host "Preview HTML: $($selection.selectedPreviewHtmlPath)"
    }
} else {
    Write-Host "Selected Wear skeleton: none"
}
