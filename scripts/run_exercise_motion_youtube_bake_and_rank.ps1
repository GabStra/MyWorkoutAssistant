param(
    [Parameter(Mandatory = $true)]
    [string]$ExerciseName,

    [string]$ExerciseId,
    [string]$WorkspaceRoot = "build/exercise_motion",
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [string]$YouTubeCookiesPath,
    [string]$YouTubePreviewCacheDir,
    [string]$PythonCommand = "",
    [int]$ResultsPerQuery = 100,
    [int]$YoutubeSearchEmptyRetries = 5,
    [int]$MaxCandidates = 12,
    [int]$MetadataCandidatePoolSize = 36,
    [int]$CandidateReviewBatchSize = 12,
    [int]$CandidateReviewTargetSuitableCount = 3,
    [Nullable[int]]$MaxCandidateReviewTargetSuitableCount = 5,
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
    [int]$VisionDownloadWorkers = 8,
    [int]$VisionLlmWorkers = 4,
    [switch]$SkipVisionRanking,
    [switch]$SemanticGateWithLlamaCpp,
    [switch]$SkipSemanticGate,
    [Nullable[int]]$SemanticGateCandidatesPerExercise = 24,
    [Nullable[int]]$SemanticGateMaxCandidatesPerExercise = 200,
    [double]$SemanticGateMinScore = 0.55,
    [switch]$PosePrefilter,
    [switch]$SkipPosePrefilter,
    [string]$PosePrefilterModel = "yolo26x-pose.pt",
    [Nullable[int]]$PosePrefilterCandidatesPerExercise = 24,
    [double]$PosePrefilterSampleFps = 0.0,
    [double]$PosePrefilterMaxSeconds = 0.0,
    [ValidateSet("prefix", "spread", "full")]
    [string]$PosePrefilterScanStrategy = "full",
    [double]$PosePrefilterWindowSeconds = 8.0,
    [double]$PosePrefilterOverlapSeconds = 4.0,
    [double]$PosePrefilterMinScore = 0.45,
    [int]$PosePrefilterWorkers = 3,
    [string]$PosePrefilterDevice = "cuda",
    [int]$PosePrefilterBatchSize = 16,
    [switch]$ThoroughYoutubeRetry,
    [switch]$SkipThoroughYoutubeRetry,
    [double]$ThoroughPosePrefilterMaxSeconds = 0.0,
    [int]$ThoroughVisionMaxChunksPerCandidate = 0,
    [double]$ThoroughVisionMotionScanMaxSeconds = 180.0,
    [int]$FallbackCandidates = 12,
    [int]$MaxSourceWindowAttempts = 1,
    [int]$MaxSelectedResults = 1,
    [int]$CandidateWorkers = 1,
    [switch]$NoWhamDocker,
    [string]$WhamDockerImage = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "16g",
    [switch]$FullWhamCameraSlam,
    [switch]$SkipSmplify,
    [switch]$NoReuseWhamCache,
    [switch]$SkipMotionTuning,
    [switch]$ExportWhamSmplPreview,
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
    [switch]$NoPreWhamSourceContract,
    [switch]$RankPreviewVariants,
    [switch]$AdaptivePreviewSettings,
    [switch]$SkipAdaptivePreviewSettings,
    [int]$MaxAdaptivePreviewSettings = 1,
    [switch]$SkipPreviewVariantRanking,
    [switch]$ClassifySupportDominance,
    [switch]$SkipSupportDominanceClassification,
    [int]$ReviewFrames = 6,
    [int]$ReviewLlmWorkers = 4,
    [int]$MaxReviewWindows = 3,
    [double]$MinSelectedScore = 0.55,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [string]$LlamaCppModel = "C:\Users\gabri\Downloads\gemma-4-12B-it-heretic-QAT-UD-Q4_K_XL.gguf",
    [string]$LlamaCppServerCommand = "C:\Users\gabri\Downloads\llama-c1a1c8ee-cuda13.3-sm89-win-x64\llama-server.exe",
    [string]$LlamaCppMmproj = "C:\Users\gabri\Downloads\mmproj-BF16.gguf",
    [string]$LlamaCppBackend = "gpu",
    [int]$LlamaCppNPredict = 768,
    [double]$LlamaCppTemperature = 1.0,
    [Nullable[double]]$LlamaCppTopP = 0.95,
    [Nullable[int]]$LlamaCppTopK = 64,
    [bool]$LlamaCppDisableReasoning = $false,
    [Nullable[int]]$LlamaCppReasoningBudget = 64,
    [string]$LlamaCppReasoningBudgetMessage = "Now stop thinking and return the JSON object.",
    [Nullable[int]]$LlamaCppCtxSize = 24576,
    [Nullable[int]]$LlamaCppBatchSize = 256,
    [Nullable[int]]$LlamaCppUBatchSize = 512,
    [string]$LlamaCppFlashAttn = "on",
    [string]$LlamaCppCacheTypeK = "q8_0",
    [string]$LlamaCppCacheTypeV = "q8_0",
    [Nullable[int]]$LlamaCppParallel = 4,
    [Nullable[int]]$LlamaCppThreadsHttp = 6,
    [Nullable[int]]$LlamaCppCacheReuse,
    [string]$LlamaCppFit = "on",
    [Nullable[int]]$LlamaCppFitCtx = 24576,
    [Nullable[int]]$LlamaCppFitTarget = 2048,
    [bool]$LlamaCppMmap = $false,
    [bool]$LlamaCppMlock = $true,
    [Nullable[int]]$LlamaCppImageMinTokens,
    [Nullable[int]]$LlamaCppImageMaxTokens,
    [switch]$NoLlamaCppAutoStartServer,
    [bool]$KeepLlamaCppServer = $true,
    [double]$LlamaCppServerStartupTimeoutSeconds = 180.0,
    [double]$LlamaCppRequestTimeoutSeconds = 90.0,
    [ValidateSet("debug", "full")]
    [string]$ArtifactRetention = "debug"
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

function Resolve-MotionPythonCommand {
    param([string]$ConfiguredCommand)
    if (-not [string]::IsNullOrWhiteSpace($ConfiguredCommand)) {
        return $ConfiguredCommand
    }
    if (-not [string]::IsNullOrWhiteSpace($env:EXERCISE_MOTION_PYTHON)) {
        return $env:EXERCISE_MOTION_PYTHON
    }
    $cudaPython = "C:\Users\gabri\miniconda3\envs\mwa-motion-cuda\python.exe"
    if (Test-Path -LiteralPath $cudaPython) {
        return $cudaPython
    }
    return "python"
}

function Invoke-PythonModule {
    param([string[]]$Arguments)
    & $PythonCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "python command failed with exit code $LASTEXITCODE."
    }
}

function Set-ArgumentValue {
    param(
        [string[]]$Arguments,
        [string]$Name,
        [string]$Value
    )
    $result = @()
    $found = $false
    for ($index = 0; $index -lt $Arguments.Count; $index += 1) {
        $argument = $Arguments[$index]
        if ($argument -eq $Name) {
            $result += @($Name, $Value)
            $found = $true
            $index += 1
            continue
        }
        $result += $argument
    }
    if (-not $found) {
        $result += @($Name, $Value)
    }
    return [string[]]$result
}

function Get-SelectionManifest {
    param([string]$SelectionPath)
    if (-not (Test-Path -LiteralPath $SelectionPath)) {
        return $null
    }
    return Get-Content -LiteralPath $SelectionPath -Raw | ConvertFrom-Json
}

function Get-SelectedResultCount {
    param([object]$Selection)
    if (-not $Selection) {
        return 0
    }
    if ($Selection.PSObject.Properties.Name -contains "selectedResults" -and $Selection.selectedResults) {
        return @($Selection.selectedResults).Count
    }
    if ($Selection.selected) {
        return 1
    }
    return 0
}

function Assert-SelectedWearSkeletonContract {
    param([object]$Selection)
    $selectedOptions = if ($Selection.PSObject.Properties.Name -contains "selectedResults" -and $Selection.selectedResults) {
        @($Selection.selectedResults)
    } else {
        @($Selection.selected)
    }
    $optionIndex = 1
    foreach ($option in $selectedOptions) {
        if ($option.wearSkeletonSettingsBaked -ne $true) {
            $contractJson = $option.wearSkeletonPreviewSettingsContract | ConvertTo-Json -Depth 8
            throw "Selected Wear skeleton option $optionIndex does not contain the baked preview settings required by Wear. Contract: $contractJson"
        }
        $optionIndex += 1
    }
}

$repoRoot = Get-RepoRoot
$PythonCommand = Resolve-MotionPythonCommand $PythonCommand
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
if ($MaxSelectedResults -lt 1) {
    throw "MaxSelectedResults must be at least 1."
}
$resolvedMaxCandidateReviewTargetSuitableCount = if ($null -ne $MaxCandidateReviewTargetSuitableCount) {
    [Math]::Max([int]$MaxCandidateReviewTargetSuitableCount, $MaxSelectedResults)
} else {
    [Math]::Max($FallbackCandidates, $CandidateReviewTargetSuitableCount, $MaxSelectedResults)
}
if ($CandidateReviewTargetSuitableCount -lt 1) {
    throw "CandidateReviewTargetSuitableCount must be at least 1."
}
$initialTargetSuitableCount = [Math]::Max($CandidateReviewTargetSuitableCount, $MaxSelectedResults)
if ($resolvedMaxCandidateReviewTargetSuitableCount -lt $initialTargetSuitableCount) {
    throw "MaxCandidateReviewTargetSuitableCount must be greater than or equal to CandidateReviewTargetSuitableCount and MaxSelectedResults."
}
$exerciseWorkspace = Join-Path $WorkspaceRoot "$slug-e2e"
$bakeWorkspace = Join-Path $exerciseWorkspace "bake-final"
$planPath = Join-Path $exerciseWorkspace "$slug-plan.json"
$candidatesPath = Join-Path $exerciseWorkspace "youtube_candidates.json"
$previewCachePath = if ([string]::IsNullOrWhiteSpace($YouTubePreviewCacheDir)) {
    Join-Path (Join-Path $repoRoot "build\exercise_motion") "youtube-preview-cache"
} else {
    $YouTubePreviewCacheDir
}
New-Item -ItemType Directory -Force -Path $exerciseWorkspace | Out-Null
New-Item -ItemType Directory -Force -Path $previewCachePath | Out-Null

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
    "--candidate-review-batch-size", "$CandidateReviewBatchSize",
    "--candidate-review-target-suitable-count", "$CandidateReviewTargetSuitableCount",
    "--vision-candidates-per-exercise", "$VisionCandidatesPerExercise",
    "--vision-download-workers", "$VisionDownloadWorkers",
    "--vision-llm-workers", "$VisionLlmWorkers"
)
if ($VisionMaxChunksPerCandidate -gt 0) {
    $youtubeArgs += @("--vision-max-chunks-per-candidate", "$VisionMaxChunksPerCandidate")
}
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
    if ($null -ne $SemanticGateMaxCandidatesPerExercise) {
        $youtubeArgs += @("--semantic-gate-max-candidates-per-exercise", "$SemanticGateMaxCandidatesPerExercise")
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
if (-not [string]::IsNullOrWhiteSpace($LlamaCppServerCommand)) {
    $youtubeArgs += @("--llama-cpp-server-command", $LlamaCppServerCommand)
}
if ($LlamaCppDisableReasoning) {
    $youtubeArgs += "--llama-cpp-disable-reasoning"
}
if ($null -ne $LlamaCppReasoningBudget) {
    $youtubeArgs += @("--llama-cpp-reasoning-budget", "$LlamaCppReasoningBudget")
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppReasoningBudgetMessage)) {
    $youtubeArgs += @("--llama-cpp-reasoning-budget-message", $LlamaCppReasoningBudgetMessage)
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
if ($KeepLlamaCppServer) {
    $youtubeArgs += "--keep-llama-cpp-server"
}
$youtubeArgs = Add-LlamaCppTuningArgs -Arguments $youtubeArgs
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $youtubeArgs += @("--youtube-cookies", $YouTubeCookiesPath)
}
if (($UseLlamaCppQueryPlanner -or -not $SkipLlamaCppQueryPlanner) -and -not $UseDeepSeekQueryPlanner) {
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
        "--pose-prefilter-workers", "$PosePrefilterWorkers",
        "--pose-prefilter-device", $PosePrefilterDevice,
        "--pose-prefilter-batch-size", "$PosePrefilterBatchSize"
    )
    if ($null -ne $PosePrefilterCandidatesPerExercise) {
        $youtubeArgs += @("--pose-prefilter-candidates-per-exercise", "$PosePrefilterCandidatesPerExercise")
    }
}

$youtubeBaseArgs = [string[]]$youtubeArgs

$resolvedWhamRepoPath = Resolve-StrictPath $WhamRepoPath
$resolvedBodyModelRoot = Resolve-StrictPath $BodyModelRoot
$bakeArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "bake-and-rank",
    "--candidates-json", $candidatesPath,
    "--fallback-candidates", "$FallbackCandidates",
    "--max-source-window-attempts", "$MaxSourceWindowAttempts",
    "--max-selected-results", "$MaxSelectedResults",
    "--candidate-workers", "$CandidateWorkers",
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
    "--review-llm-workers", "$ReviewLlmWorkers",
    "--max-review-windows", "$MaxReviewWindows",
    "--min-selected-score", "$MinSelectedScore",
    "--llama-cpp-base-url", $LlamaCppBaseUrl,
    "--llama-cpp-model", $LlamaCppModel,
    "--llama-cpp-mmproj", $LlamaCppMmproj,
    "--llama-cpp-backend", $LlamaCppBackend,
    "--llama-cpp-n-predict", "$LlamaCppNPredict",
    "--llama-cpp-server-startup-timeout-seconds", "$LlamaCppServerStartupTimeoutSeconds",
    "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds",
    "--artifact-retention", $ArtifactRetention
)
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
if (-not [string]::IsNullOrWhiteSpace($LlamaCppServerCommand)) {
    $bakeArgs += @("--llama-cpp-server-command", $LlamaCppServerCommand)
}
if ($LlamaCppDisableReasoning) {
    $bakeArgs += "--llama-cpp-disable-reasoning"
}
if ($null -ne $LlamaCppReasoningBudget) {
    $bakeArgs += @("--llama-cpp-reasoning-budget", "$LlamaCppReasoningBudget")
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppReasoningBudgetMessage)) {
    $bakeArgs += @("--llama-cpp-reasoning-budget-message", $LlamaCppReasoningBudgetMessage)
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
if ($KeepLlamaCppServer) {
    $bakeArgs += "--keep-llama-cpp-server"
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
if ($ExportWhamSmplPreview) {
    $bakeArgs += "--export-wham-smpl-preview"
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
if ($NoPreWhamSourceContract) {
    $bakeArgs += "--no-pre-wham-source-contract"
}

$selectionPath = Join-Path $bakeWorkspace "selection_manifest.json"
$bakeBaseArgs = [string[]]$bakeArgs
$currentTargetSuitableCount = [Math]::Max(1, $initialTargetSuitableCount)
$attemptIndex = 1
$selection = $null

while ($true) {
    $attemptMaxCandidates = [Math]::Max($MaxCandidates, $currentTargetSuitableCount)
    $attemptVisionCandidates = [Math]::Max($VisionCandidatesPerExercise, $currentTargetSuitableCount)
    $attemptYoutubeArgs = Set-ArgumentValue -Arguments $youtubeBaseArgs -Name "--candidate-review-target-suitable-count" -Value "$currentTargetSuitableCount"
    $attemptYoutubeArgs = Set-ArgumentValue -Arguments $attemptYoutubeArgs -Name "--max-candidates" -Value "$attemptMaxCandidates"
    $attemptYoutubeArgs = Set-ArgumentValue -Arguments $attemptYoutubeArgs -Name "--vision-candidates-per-exercise" -Value "$attemptVisionCandidates"

    Write-Host "YouTube discovery attempt ${attemptIndex}: target suitable candidates $currentTargetSuitableCount (max $resolvedMaxCandidateReviewTargetSuitableCount)."
    Invoke-PythonModule -Arguments $attemptYoutubeArgs

    $recommendationCounts = Get-RecommendationCounts -CandidatesJson $candidatesPath
    if ($recommendationCounts.Recommended -le 0 -and $ThoroughYoutubeRetry -and -not $SkipThoroughYoutubeRetry) {
        Write-Host "No recommended YouTube candidates found; rerunning discovery with deeper per-video scan limits."
        $thoroughYoutubeArgs = @($attemptYoutubeArgs)
        $thoroughYoutubeArgs += @(
            "--pose-prefilter-max-seconds", "$ThoroughPosePrefilterMaxSeconds",
            "--vision-motion-scan-max-seconds", "$ThoroughVisionMotionScanMaxSeconds"
        )
        if ($ThoroughVisionMaxChunksPerCandidate -gt 0) {
            $thoroughYoutubeArgs += @("--vision-max-chunks-per-candidate", "$ThoroughVisionMaxChunksPerCandidate")
        }
        Invoke-PythonModule -Arguments $thoroughYoutubeArgs
        $recommendationCounts = Get-RecommendationCounts -CandidatesJson $candidatesPath
    }

    if ($recommendationCounts.Recommended -le 0) {
        if ($currentTargetSuitableCount -ge $resolvedMaxCandidateReviewTargetSuitableCount) {
            throw "No recommended YouTube candidate found after discovery. Refusing to bake non-recommended candidates. Inspect $candidatesPath and fix discovery/ranking."
        }
        $currentTargetSuitableCount = [Math]::Min($resolvedMaxCandidateReviewTargetSuitableCount, $currentTargetSuitableCount + 1)
        $attemptIndex += 1
        Write-Host "No recommended candidates yet; expanding YouTube review target to $currentTargetSuitableCount."
        continue
    }

    Write-Host "Bake attempt ${attemptIndex}: baking $($recommendationCounts.Recommended) recommended candidate(s)."
    & $PythonCommand @bakeBaseArgs
    $bakeExitCode = $LASTEXITCODE

    $selection = Get-SelectionManifest -SelectionPath $selectionPath
    $selectedResultCount = Get-SelectedResultCount -Selection $selection
    if ($selection -and $selection.selected -and $selectedResultCount -gt 0) {
        Assert-SelectedWearSkeletonContract -Selection $selection
        if ($selectedResultCount -ge $MaxSelectedResults) {
            break
        }
        if ($currentTargetSuitableCount -ge $resolvedMaxCandidateReviewTargetSuitableCount) {
            Write-Host "Bake-and-rank selected $selectedResultCount/$MaxSelectedResults requested result(s); max YouTube review target reached, keeping valid partial output."
            break
        }
        $currentTargetSuitableCount = [Math]::Min($resolvedMaxCandidateReviewTargetSuitableCount, $currentTargetSuitableCount + 1)
        $attemptIndex += 1
        Write-Host "Bake-and-rank selected $selectedResultCount/$MaxSelectedResults requested result(s); expanding YouTube review target to $currentTargetSuitableCount."
        continue
    }
    if ($bakeExitCode -ne 0 -and -not $selection) {
        throw "python bake-and-rank command failed with exit code $bakeExitCode and did not write $selectionPath."
    }
    if ($bakeExitCode -ne 0) {
        Write-Host "Bake-and-rank returned exit code $bakeExitCode after writing a no-selection manifest; continuing with the next YouTube review target."
    }

    Write-Host "Bake-and-rank completed without selecting a Wear skeleton at target $currentTargetSuitableCount."
    if ($currentTargetSuitableCount -ge $resolvedMaxCandidateReviewTargetSuitableCount) {
        throw "Bake-and-rank completed without selecting a Wear skeleton after reviewing up to $resolvedMaxCandidateReviewTargetSuitableCount suitable YouTube candidate(s). Inspect $selectionPath."
    }
    $currentTargetSuitableCount = [Math]::Min($resolvedMaxCandidateReviewTargetSuitableCount, $currentTargetSuitableCount + 1)
    $attemptIndex += 1
    Write-Host "No final selected motion; expanding YouTube review target to $currentTargetSuitableCount."
}

Write-Host "Plan JSON: $((Resolve-Path -LiteralPath $planPath).Path)"
Write-Host "YouTube candidates JSON: $((Resolve-Path -LiteralPath $candidatesPath).Path)"
Write-Host "Selection manifest: $((Resolve-Path -LiteralPath $selectionPath).Path)"
if ($selection.selected) {
    Write-Host "Wear skeleton JSON: $($selection.selected.selectedWearSkeletonPath)"
    if ($selection.PSObject.Properties.Name -contains "selectedResults" -and @($selection.selectedResults).Count -gt 1) {
        Write-Host "Selected result options: $(@($selection.selectedResults).Count)"
        $optionIndex = 1
        foreach ($option in @($selection.selectedResults)) {
            Write-Host "  Option ${optionIndex}: $($option.selectedWearSkeletonPath)"
            if ($option.PSObject.Properties.Name -contains "selectedReviewVideoPath" -and $option.selectedReviewVideoPath) {
                Write-Host "    Preview video: $($option.selectedReviewVideoPath)"
            }
            if ($option.PSObject.Properties.Name -contains "selectedPreviewHtmlPath" -and $option.selectedPreviewHtmlPath) {
                Write-Host "    Preview HTML: $($option.selectedPreviewHtmlPath)"
            }
            $optionIndex += 1
        }
    }
    if ($selection.selected.PSObject.Properties.Name -contains "wearSkeletonSettingsBaked") {
        Write-Host "Wear skeleton settings baked: $($selection.selected.wearSkeletonSettingsBaked)"
    }
    if ($selection.selectedPreviewHtmlPath) {
        Write-Host "Preview HTML: $($selection.selectedPreviewHtmlPath)"
    }
} else {
    Write-Host "Selected Wear skeleton: none"
    throw "Bake-and-rank completed without selecting a Wear skeleton. Inspect $selectionPath."
}
