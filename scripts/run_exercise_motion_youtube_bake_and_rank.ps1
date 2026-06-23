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
    [switch]$UseLlamaCppQueryPlanner,
    [switch]$SkipLlamaCppQueryPlanner,
    [switch]$UseDeepSeekQueryPlanner,
    [string]$DeepSeekApiKey,
    [string]$DeepSeekBaseUrl = "https://api.deepseek.com",
    [string]$DeepSeekModel = "deepseek-v4-flash",
    [int]$DeepSeekMaxQueries = 4,
    [int]$VisionCandidatesPerExercise = 12,
    [int]$VisionFramesPerCandidate = 0,
    [int]$VisionMaxChunksPerCandidate = 5,
    [int]$VisionDownloadWorkers = 3,
    [int]$VisionLlmWorkers = 3,
    [switch]$SkipVisionRanking,
    [switch]$SemanticGateWithLlamaCpp,
    [switch]$SkipSemanticGate,
    [Nullable[int]]$SemanticGateCandidatesPerExercise = 24,
    [double]$SemanticGateMinScore = 0.55,
    [switch]$PosePrefilter,
    [switch]$SkipPosePrefilter,
    [string]$PosePrefilterModel = "yolo26x-pose.pt",
    [Nullable[int]]$PosePrefilterCandidatesPerExercise = 24,
    [double]$PosePrefilterSampleFps = 1.0,
    [double]$PosePrefilterMaxSeconds = 32.0,
    [ValidateSet("prefix", "spread")]
    [string]$PosePrefilterScanStrategy = "spread",
    [double]$PosePrefilterWindowSeconds = 8.0,
    [double]$PosePrefilterOverlapSeconds = 4.0,
    [double]$PosePrefilterMinScore = 0.45,
    [int]$PosePrefilterWorkers = 3,
    [switch]$AllowYoutubeCandidateFallback,
    [switch]$ThoroughYoutubeRetry,
    [switch]$SkipThoroughYoutubeRetry,
    [double]$ThoroughPosePrefilterMaxSeconds = 90.0,
    [int]$ThoroughVisionMaxChunksPerCandidate = 10,
    [double]$ThoroughVisionMotionScanMaxSeconds = 180.0,
    [int]$FallbackCandidates = 5,
    [switch]$NoWhamDocker,
    [string]$WhamDockerImage = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "16g",
    [switch]$FullWhamCameraSlam,
    [switch]$SkipSmplify,
    [switch]$NoReuseWhamCache,
    [switch]$SkipMotionTuning,
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
    [switch]$SkipPreWhamSourceValidation,
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
    [string]$LlamaCppModel = "C:\Users\gabri\Downloads\gemma-4-12B-it-heretic-QAT-UD-Q4_K_XL.gguf",
    [string]$LlamaCppCommand,
    [string]$LlamaCppServerCommand,
    [string]$LlamaCppMmproj = "C:\Users\gabri\Downloads\mmproj-BF16.gguf",
    [string]$LlamaCppBackend = "gpu",
    [int]$LlamaCppNPredict = 768,
    [double]$LlamaCppTemperature = 1.0,
    [Nullable[double]]$LlamaCppTopP = 0.95,
    [Nullable[int]]$LlamaCppTopK = 64,
    [Nullable[int]]$LlamaCppCtxSize = 65536,
    [Nullable[int]]$LlamaCppBatchSize = 256,
    [Nullable[int]]$LlamaCppUBatchSize = 512,
    [string]$LlamaCppFlashAttn = "on",
    [string]$LlamaCppCacheTypeK = "q8_0",
    [string]$LlamaCppCacheTypeV = "q8_0",
    [Nullable[int]]$LlamaCppParallel = 1,
    [Nullable[int]]$LlamaCppThreadsHttp = 6,
    [Nullable[int]]$LlamaCppCacheReuse,
    [string]$LlamaCppFit = "on",
    [Nullable[int]]$LlamaCppFitCtx = 65536,
    [Nullable[int]]$LlamaCppFitTarget = 2048,
    [bool]$LlamaCppMmap = $false,
    [bool]$LlamaCppMlock = $true,
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

function Add-LlamaCppTuningArgs {
    param([string[]]$Arguments)
    $result = @($Arguments)
    if ($null -ne $LlamaCppCtxSize) {
        $result += @("--llama-cpp-ctx-size", "$LlamaCppCtxSize")
    }
    if ($null -ne $LlamaCppBatchSize) {
        $result += @("--llama-cpp-batch-size", "$LlamaCppBatchSize")
    }
    if ($null -ne $LlamaCppUBatchSize) {
        $result += @("--llama-cpp-ubatch-size", "$LlamaCppUBatchSize")
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppFlashAttn)) {
        $result += @("--llama-cpp-flash-attn", $LlamaCppFlashAttn)
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppCacheTypeK)) {
        $result += @("--llama-cpp-cache-type-k", $LlamaCppCacheTypeK)
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppCacheTypeV)) {
        $result += @("--llama-cpp-cache-type-v", $LlamaCppCacheTypeV)
    }
    if ($null -ne $LlamaCppParallel) {
        $result += @("--llama-cpp-parallel", "$LlamaCppParallel")
    }
    if ($null -ne $LlamaCppThreadsHttp) {
        $result += @("--llama-cpp-threads-http", "$LlamaCppThreadsHttp")
    }
    if ($null -ne $LlamaCppCacheReuse) {
        $result += @("--llama-cpp-cache-reuse", "$LlamaCppCacheReuse")
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppFit)) {
        $result += @("--llama-cpp-fit", $LlamaCppFit)
    }
    if ($null -ne $LlamaCppFitCtx) {
        $result += @("--llama-cpp-fit-ctx", "$LlamaCppFitCtx")
    }
    if ($null -ne $LlamaCppFitTarget) {
        $result += @("--llama-cpp-fit-target", "$LlamaCppFitTarget")
    }
    if (-not $LlamaCppMmap) {
        $result += "--no-llama-cpp-mmap"
    }
    if ($LlamaCppMlock) {
        $result += "--llama-cpp-mlock"
    }
    return $result
}

function Get-RecommendationCounts {
    param([string]$CandidatesJson)
    if (-not (Test-Path -LiteralPath $CandidatesJson)) {
        return @{ Recommended = 0; Candidate = 0; Rejected = 0 }
    }
    $payload = Get-Content -LiteralPath $CandidatesJson -Raw | ConvertFrom-Json
    $recommended = 0
    $candidate = 0
    $rejected = 0
    foreach ($exercise in @($payload.exercises)) {
        foreach ($item in @($exercise.candidates)) {
            $status = "$($item.status)".ToLowerInvariant()
            if ($status -eq "recommended") {
                $recommended += 1
            }
            elseif ($status -eq "candidate") {
                $candidate += 1
            }
            elseif ($status -eq "rejected") {
                $rejected += 1
            }
        }
    }
    return @{ Recommended = $recommended; Candidate = $candidate; Rejected = $rejected }
}
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $YouTubeCookiesPath = Resolve-StrictPath $YouTubeCookiesPath
}
$exerciseWorkspace = Join-Path $WorkspaceRoot "$slug-e2e"
$bakeWorkspace = Join-Path $exerciseWorkspace "bake-final"
$planPath = Join-Path $exerciseWorkspace "$slug-plan.json"
$candidatesPath = Join-Path $exerciseWorkspace "youtube_candidates.json"
$previewCachePath = Join-Path $exerciseWorkspace "youtube-preview-cache"
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
    "--youtube-preview-cache-dir", $previewCachePath,
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
$youtubeArgs += @(
    "--llama-cpp-base-url", $LlamaCppBaseUrl,
    "--llama-cpp-model", $LlamaCppModel,
    "--llama-cpp-mmproj", $LlamaCppMmproj,
    "--llama-cpp-backend", $LlamaCppBackend,
    "--llama-cpp-n-predict", "$LlamaCppNPredict",
    "--llama-cpp-server-startup-timeout-seconds", "$LlamaCppServerStartupTimeoutSeconds"
)
if ($SemanticGateWithLlamaCpp -or -not $SkipSemanticGate) {
    $youtubeArgs += @(
        "--semantic-gate-with-llama-cpp",
        "--semantic-gate-min-score", "$SemanticGateMinScore"
    )
    if ($null -ne $SemanticGateCandidatesPerExercise) {
        $youtubeArgs += @("--semantic-gate-candidates-per-exercise", "$SemanticGateCandidatesPerExercise")
    }
}
if ($LlamaCppRequestTimeoutSeconds -gt 0) {
    $youtubeArgs += @("--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds")
}
$youtubeArgs += @("--llama-cpp-temperature", "$LlamaCppTemperature")
if ($null -ne $LlamaCppTopP) {
    $youtubeArgs += @("--llama-cpp-top-p", "$LlamaCppTopP")
}
if ($null -ne $LlamaCppTopK) {
    $youtubeArgs += @("--llama-cpp-top-k", "$LlamaCppTopK")
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppCommand)) {
    $youtubeArgs += @("--llama-cpp-command", $LlamaCppCommand)
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppServerCommand)) {
    $youtubeArgs += @("--llama-cpp-server-command", $LlamaCppServerCommand)
}
if ($null -ne $LlamaCppImageMinTokens) {
    $youtubeArgs += @("--llama-cpp-image-min-tokens", "$LlamaCppImageMinTokens")
}
if ($null -ne $LlamaCppImageMaxTokens) {
    $youtubeArgs += @("--llama-cpp-image-max-tokens", "$LlamaCppImageMaxTokens")
}
if ($NoLlamaCppAutoStartServer) {
    $youtubeArgs += "--no-llama-cpp-auto-start-server"
}
$youtubeArgs = Add-LlamaCppTuningArgs -Arguments $youtubeArgs
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $youtubeArgs += @("--youtube-cookies", $YouTubeCookiesPath)
}
if ($UseLlamaCppQueryPlanner -and -not $SkipLlamaCppQueryPlanner -and -not $UseDeepSeekQueryPlanner) {
    $youtubeArgs += @(
        "--use-llama-cpp-query-planner",
        "--deepseek-max-queries", "$DeepSeekMaxQueries"
    )
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
        "--pose-prefilter-scan-strategy", $PosePrefilterScanStrategy,
        "--pose-prefilter-window-seconds", "$PosePrefilterWindowSeconds",
        "--pose-prefilter-overlap-seconds", "$PosePrefilterOverlapSeconds",
        "--pose-prefilter-min-score", "$PosePrefilterMinScore",
        "--pose-prefilter-workers", "$PosePrefilterWorkers"
    )
    if ($null -ne $PosePrefilterCandidatesPerExercise) {
        $youtubeArgs += @("--pose-prefilter-candidates-per-exercise", "$PosePrefilterCandidatesPerExercise")
    }
}

Invoke-PythonModule -Arguments $youtubeArgs

$recommendationCounts = Get-RecommendationCounts -CandidatesJson $candidatesPath
if ($recommendationCounts.Recommended -le 0 -and $ThoroughYoutubeRetry -and -not $SkipThoroughYoutubeRetry) {
    Write-Host "No recommended YouTube candidates found; rerunning discovery with deeper per-video scan limits."
    $thoroughYoutubeArgs = @($youtubeArgs)
    $thoroughYoutubeArgs += @(
        "--pose-prefilter-max-seconds", "$ThoroughPosePrefilterMaxSeconds",
        "--vision-max-chunks-per-candidate", "$ThoroughVisionMaxChunksPerCandidate",
        "--vision-motion-scan-max-seconds", "$ThoroughVisionMotionScanMaxSeconds"
    )
    Invoke-PythonModule -Arguments $thoroughYoutubeArgs
    $recommendationCounts = Get-RecommendationCounts -CandidatesJson $candidatesPath
}

if ($recommendationCounts.Recommended -le 0 -and -not $AllowYoutubeCandidateFallback) {
    throw "No recommended YouTube candidate found after discovery. Refusing to bake fallback candidate(s). Inspect $candidatesPath or rerun with -AllowYoutubeCandidateFallback."
}

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
if ($AllowYoutubeCandidateFallback) {
    $bakeArgs += "--allow-youtube-candidate-fallback"
}
$bakeArgs += @("--llama-cpp-temperature", "$LlamaCppTemperature")
if ($null -ne $LlamaCppTopP) {
    $bakeArgs += @("--llama-cpp-top-p", "$LlamaCppTopP")
}
if ($null -ne $LlamaCppTopK) {
    $bakeArgs += @("--llama-cpp-top-k", "$LlamaCppTopK")
}
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
if ($null -ne $LlamaCppImageMinTokens) {
    $bakeArgs += @("--llama-cpp-image-min-tokens", "$LlamaCppImageMinTokens")
}
if ($null -ne $LlamaCppImageMaxTokens) {
    $bakeArgs += @("--llama-cpp-image-max-tokens", "$LlamaCppImageMaxTokens")
}
if ($NoLlamaCppAutoStartServer) {
    $bakeArgs += "--no-llama-cpp-auto-start-server"
}
$bakeArgs = Add-LlamaCppTuningArgs -Arguments $bakeArgs
if ($null -ne $SegmentWindowSeconds) {
    $bakeArgs += @("--segment-window-seconds", "$SegmentWindowSeconds")
}
if ($null -ne $SegmentOverlapSeconds) {
    $bakeArgs += @("--segment-overlap-seconds", "$SegmentOverlapSeconds")
}
if ($null -ne $SegmentFramesPerWindow) {
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
if ($SkipSpinePose -or -not $EnableSpinePose) {
    $bakeArgs += "--skip-spinepose"
}
else {
    $bakeArgs += @(
        "--spinepose-merge-mode", $SpinePoseMergeMode,
        "--spinepose-mode", $SpinePoseMode,
        "--spinepose-model-version", $SpinePoseModelVersion,
        "--spinepose-device", $SpinePoseDevice,
        "--spinepose-gain", "$SpinePoseGain",
        "--spinepose-max-degrees", "$SpinePoseMaxDegrees",
        "--spinepose-axis", "$SpinePoseAxis",
        "--spinepose-smoothing-window", "$SpinePoseSmoothingWindow",
        "--spinepose-arm-counter-rotation", "$SpinePoseArmCounterRotation"
    )
    $bakeArgs += "--enable-spinepose"
    if (-not [string]::IsNullOrWhiteSpace($SpinePoseJsonDir)) {
        $bakeArgs += @("--spinepose-json-dir", (Resolve-StrictPath $SpinePoseJsonDir))
    }
    if (-not [string]::IsNullOrWhiteSpace($SpinePoseCommand)) {
        $bakeArgs += @("--spinepose-command", $SpinePoseCommand)
    }
    if (-not [string]::IsNullOrWhiteSpace($SpinePoseOutputDir)) {
        $bakeArgs += @("--spinepose-output-dir", $SpinePoseOutputDir)
    }
    if ($SpinePoseInvert) {
        $bakeArgs += "--spinepose-invert"
    }
    if ($NoReuseSpinePoseCache) {
        $bakeArgs += "--no-spinepose-cache"
    }
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
if (-not $SkipPreWhamSourceValidation) {
    $bakeArgs += "--pre-wham-source-validation"
}
if ($SkipPreWhamSourceValidation) {
    $bakeArgs += "--skip-pre-wham-source-validation"
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
