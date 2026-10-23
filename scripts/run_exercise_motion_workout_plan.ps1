[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkoutPlanJson,

    [string]$EquipmentJson,
    [string]$WorkspaceRoot = "build/exercise_motion/workout-plan",
    [string]$ApprovedExerciseDefinitionsJson,
    [string]$InvocationRunId = "",
    [string]$LibraryRunId = "",
    [string]$InputIdentitySha256 = "",
    [string]$MobilePackageOutputJson = "",
    [string]$IncrementalMobilePackageOutputJson = "",
    [ValidateSet("quality", "fast", "max")]
    [string]$SpeedProfile = "fast",
    [string[]]$OnlyExerciseSlug = @(),
    [string[]]$OnlyExerciseId = @(),
    [string[]]$OnlyExerciseName = @(),
    [string[]]$ExcludeCandidatesFromWorkspaceRoot = @(),
    [string[]]$ExcludeYoutubeCandidatesJson = @(),
    [string[]]$ExcludeYoutubeVideoId = @(),
    [string[]]$ExcludeYoutubeUrl = @(),
    # Fixed-source mode: a manifest of per-exercise prepared candidates JSON
    # (schemaVersion 1, kind "prepared_exercise_candidates") that bypasses
    # discovery and source-download stages entirely.
    [string]$PreparedCandidatesManifest,
    [string]$BodyModelRoot,
    [string]$YouTubePreviewCacheDir,
    [string]$YouTubeSourceCacheDir,
    [string]$SourceOutcomeIndexJson = "build/exercise_motion/source_outcome_index.json",
    [string]$PythonCommand = "",
    [int]$ResultsPerQuery = 100,
    [double]$YouTubeSearchTimeoutSeconds = 60.0,
    [int]$MaxCandidates = 12,
    [int]$CandidateReviewBatchSize = 12,
    [int]$CandidateReviewTargetSuitableCount = 2,
    [Nullable[int]]$MaxCandidateReviewTargetSuitableCount = $null,
    [switch]$UseLlamaCppQueryPlanner,
    [switch]$SkipLlamaCppQueryPlanner,
    [switch]$UseDeepSeekQueryPlanner,
    [string]$DeepSeekApiKey,
    [string]$DeepSeekBaseUrl = $(if ($env:LLM_BASE_URL) { $env:LLM_BASE_URL } else { "https://api.deepseek.com" }),
    [string]$DeepSeekModel = $(if ($env:LLM_MODEL) { $env:LLM_MODEL } else { "deepseek-v4-flash" }),
    [int]$DeepSeekMaxQueries = 4,
    [int]$VisionCandidatesPerExercise = 12,
    [int]$VisionFramesPerCandidate = 0,
    [int]$VisionMaxChunksPerCandidate = 0,
    [int]$VisionDownloadWorkers = 8,
    [int]$VisionLlmWorkers = 4,
    [switch]$NoExerciseNameRewrite,
    [switch]$NoExerciseMotionContract,
    [switch]$SkipExerciseMotionContractPrefetch,
    [switch]$SkipVisionRanking,
    [switch]$SemanticGateWithLlamaCpp,
    [switch]$SkipSemanticGate,
    [Nullable[int]]$SemanticGateCandidatesPerExercise = 24,
    [Nullable[int]]$SemanticGateMaxCandidatesPerExercise = 24,
    [double]$SemanticGateMinScore = 0.55,
    [Nullable[int]]$SemanticGateLlmWorkers = 4,
    [switch]$PosePrefilter,
    [switch]$SkipPosePrefilter,
    [string]$PosePrefilterModel = "yolo26x-pose.pt",
    [Nullable[int]]$PosePrefilterCandidatesPerExercise = 12,
    [double]$PosePrefilterSampleFps = 8.0,
    [double]$PosePrefilterMaxSeconds = 32.0,
    [ValidateSet("prefix", "spread", "full")]
    [string]$PosePrefilterScanStrategy = "spread",
    [double]$PosePrefilterWindowSeconds = 8.0,
    [double]$PosePrefilterOverlapSeconds = 4.0,
    [double]$PosePrefilterMinScore = 0.45,
    [int]$PosePrefilterWorkers = 1,
    [string]$PosePrefilterDevice = "cuda",
    [int]$PosePrefilterBatchSize = 16,
    [int]$ExerciseWorkers = 1,
    [Nullable[int]]$DiscoveryWorkers,
    [Nullable[int]]$BakeWorkers,
    [int]$StagedWaveSize = 0,
    [ValidateRange(1, 86400)]
    # Retained for wrapper compatibility; ready work is dispatched as soon as it arrives.
    [int]$StagedWaveMaxWaitSeconds = 300,
    # Wave-overlap pipelining: how many staged waves may run at once. 1 is
    # exactly the serialized behavior (one wave at a time, nothing else in
    # the bake lane). Values > 1 only admit a new wave while every running
    # wave is in its CPU-only cpu_preparation phase, and require
    # -SharedLlamaServer: without it each wave's VLM phases spawn a dedicated
    # ~8 GiB llama-server that cannot co-reside on the GPU (the run clamps
    # the cap back to 1 in that case). The service shares the bounded CPU
    # preparation executor across at most two active waves.
    [ValidateRange(1, 8)]
    [int]$MaxConcurrentStagedWaves = 1,
    [ValidateRange(0, 100000)]
    [int]$DiscoveryCandidateBudget = 0,
    [ValidateRange(0, 86400)]
    [int]$DiscoveryTimeBudgetSeconds = 0,
    [switch]$CpuPrefetchDuringBake,
    [int]$PrefetchWorkers = 4,
    [int]$PrefetchQueueDepth = 40,
    [int]$SourceDownloadWorkers = 2,
    [int]$SourceDownloadCandidates = 3,
    [ValidateSet("auto", "allow", "avoid")]
    [string]$GpuDiscoveryBakeOverlap = "auto",
    [int]$FallbackCandidates = 12,
    [int]$MaxSourceWindowAttempts = 0,
    [int]$MaxFinalOutputRejections = 0,
    [int]$MaxReconstructionCandidateAttempts = 2,
    [double]$SourceReviewTimeoutSeconds = 180.0,
    [double]$FinalReviewTimeoutSeconds = 120.0,
    [double]$CandidateTimeoutSeconds = 0.0,
    [double]$ExerciseTimeoutSeconds = 0.0,
    [int]$MaxSelectedResults = 1,
    [int]$CandidateWorkers = 1,
    [Alias("Resume")]
    [switch]$ReuseExistingSelected,
    [switch]$DisableStageResume,
    [switch]$DisableMotionProcessingResume,
    [switch]$AllowDirtyWorktree,
    [switch]$DeferAfterFirstAttempt,
    [switch]$IncludeDisabled,
    [switch]$RequireReconstructionCache,
    [string]$ReconstructionDockerImage = "myworkoutassistant/gvhmr:torch2.3-cu121",
    [switch]$FastProfile,
    [string]$ReconstructionDockerGpus = "all",
    [string]$ReconstructionDockerShmSize = "16g",
    [bool]$WarmGvhmrWorker = $false,
    [switch]$SkipWarmGvhmrWorker,
    [string]$GvhmrWorkerSessionDir,
    [double]$GvhmrWorkerStartupTimeoutSeconds = 600.0,
    [double]$GvhmrWorkerJobTimeoutSeconds = 1200.0,
    [double]$ReconstructionTimeoutSeconds = 1200.0,
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
    [double]$SegmentMaxSeconds = 0.0,
    [switch]$SkipPreReconstructionSourceValidation,
    [int]$SegmentClassificationWorkers = 4,
    [switch]$RankPreviewVariants,
    [switch]$AdaptivePreviewSettings,
    [switch]$SkipAdaptivePreviewSettings,
    [int]$MaxAdaptivePreviewSettings = 2,
    [switch]$SkipPreviewVariantRanking,
    [switch]$ClassifySupportDominance,
    [switch]$SkipSupportDominanceClassification,
    [int]$ReviewFrames = 6,
    [int]$ReviewLlmWorkers = 4,
    [int]$MaxReviewWindows = 0,
    [double]$MinSelectedScore = 0.55,
    [bool]$FinalOutputValidation = $true,
    [switch]$SkipFinalOutputValidation,
    [switch]$TwoScaleSourceValidation,
    [switch]$SkipTwoScaleSourceValidation,
    [double]$FinalOutputValidationMinScore = 0.90,
    [switch]$ComparativeSegmentSelection,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [string]$LlamaCppModel = (Join-Path (Split-Path -Parent $PSScriptRoot) "models/Qwen3.5-9B-Q6_K/Qwen3.5-9B-Q6_K.gguf"),
    [string]$LlamaCppServerCommand = "C:\Users\gabri\Documents\llama.cpp\build-master\bin\Release\llama-server.exe",
    [string]$LlamaCppMmproj = (Join-Path (Split-Path -Parent $PSScriptRoot) "models/Qwen3.5-9B-Q6_K/mmproj-BF16.gguf"),
    [AllowEmptyString()]
    [string]$LlamaCppMtpModel = "",
    [int]$LlamaCppSpecDraftNMax = 3,
    [string]$TextLlamaCppModel = (Join-Path (Split-Path -Parent $PSScriptRoot) "models/Qwen3.5-9B-Q6_K/Qwen3.5-9B-Q6_K.gguf"),
    [AllowEmptyString()]
    [string]$TextLlamaCppMmproj = "",
    [string]$LlamaCppBackend = "gpu",
    [double]$LlamaCppTemperature = 0.0,
    [Nullable[double]]$LlamaCppTopP = 1.0,
    [Nullable[int]]$LlamaCppTopK = 0,
    [Nullable[int]]$LlamaCppCtxSize = 49152,
    [Nullable[int]]$LlamaCppBatchSize = 1024,
    [Nullable[int]]$LlamaCppUBatchSize = 512,
    [string]$LlamaCppFlashAttn = "on",
    [string]$LlamaCppCacheTypeK = "q8_0",
    [string]$LlamaCppCacheTypeV = "q8_0",
    # Three 16K slots retain the existing 48K cache budget and fit longer source reviews.
    [Nullable[int]]$LlamaCppParallel = 3,
    [Nullable[int]]$LlamaCppThreadsHttp = 8,
    [Nullable[int]]$LlamaCppCacheReuse,
    [string]$LlamaCppFit = "on",
    [Nullable[int]]$LlamaCppFitCtx = 49152,
    [Nullable[int]]$LlamaCppFitTarget = 2048,
    [Nullable[int]]$LlamaCppImageMinTokens = 1024,
    [Nullable[int]]$LlamaCppImageMaxTokens = 2048,
    [Nullable[int]]$LlamaCppMtmdBatchMaxTokens = 768,
    [bool]$LlamaCppMmap = $true,
    [bool]$LlamaCppMlock = $false,
    [Nullable[int]]$LlamaCppReasoningBudget = 64,
    [string]$LlamaCppReasoningBudgetMessage = "Now stop thinking and return the JSON object.",
    [bool]$KeepLlamaCppServer = $false,
    [double]$LlamaCppServerStartupTimeoutSeconds = 180.0,
    [double]$LlamaCppRequestTimeoutSeconds = 180.0,
    # Shared llama.cpp server (SHARED_LLAMA_SERVER.md). The run loop starts it
    # before contract prefetch and passes its session to each wave.
    [switch]$SharedLlamaServer,
    [string]$SharedLlamaServerSessionDir,
    [double]$SharedLlamaServerStopDrainTimeoutSeconds = 120.0,
    [ValidateSet("debug", "full")]
    [string]$ArtifactRetention = "debug",
    [int]$ProgressIntervalSeconds = 90,
    [switch]$DetailedProgressLogs,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArguments = @()
)

. (Join-Path $PSScriptRoot "motion_validation_policy.ps1")
$SelectionValidationPolicyVersion = Get-MotionSelectionValidationPolicyVersion
$SourceSelectionPolicyVersion = Get-MotionPythonValidationPolicyConstant -Name 'SOURCE_SELECTION_POLICY_VERSION'
$SourceSelectionClearancePolicyVersion = Get-MotionPythonValidationPolicyConstant -Name 'SOURCE_SELECTION_CLEARANCE_POLICY_VERSION'
$RetainedSelectedRevalidationVersion = Get-MotionRetainedSelectedRevalidationVersion
$StagedWaveAmbiguousRecoveryExitCode = 76
$StagedWaveAmbiguousRecoveryStatus = "ambiguous_recovery"

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "reconstruction_compat.ps1")
$reconstructionCompatPath = (Join-Path $PSScriptRoot "reconstruction_compat.ps1").Replace("'", "''")
$script:ReconstructionJobInitialization = [scriptblock]::Create(". '$reconstructionCompatPath'")
Import-Module (Join-Path $PSScriptRoot "motion_source_identity.psm1") -Force
. (Join-Path $PSScriptRoot "motion_run_interrupt.ps1")
trap {
    if (
        $_.Exception -is [System.Management.Automation.PipelineStoppedException] -or
        (Test-MotionRunCancelRequested)
    ) {
        Write-MotionInterruptReceived
        exit 130
    }
    throw $_
}

$script:LastProgressDetailByLogPath = @{}
$script:LiveLogStateByPath = @{}
$script:LastStagedWaveCheckpointVersionByPath = @{}
$script:StagedWaveCheckpointStageCacheByPath = @{}
$script:AnnouncedIndividualGeneration = $false
$script:GvhmrWorkerStartedOnce = $false
$discoveryStagePolicyVersion = 5
$sourceDownloadStagePolicyVersion = 2
# Scheduler timeline telemetry (<WorkspaceRoot>/scheduler_timeline.json). This
# run's state starts empty; the file is written lazily on the first event and
# never appended to a pre-existing timeline.
$script:SchedulerTimelineRunStartedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
$script:SchedulerTimelinePath = $null
$script:SchedulerTimelineItemsBySlug = @{}
$script:SchedulerTimelineWaves = @()

function Get-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Resolve-CudaPosePrefilterDevice {
    param([string]$Device)
    $value = if ([string]::IsNullOrWhiteSpace($Device)) { "cuda" } else { $Device.Trim() }
    $lower = $value.ToLowerInvariant()
    if ($lower -eq "cuda" -or $lower -eq "0" -or $lower -match "^cuda:\d+$") {
        return $lower
    }
    if ($lower -eq "gpu") {
        return "cuda"
    }
    throw "YOLO pose prefilter must use CUDA. Set -PosePrefilterDevice cuda or cuda:0, or pass -SkipPosePrefilter to disable it."
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

function ConvertTo-StringSet {
    param([string[]]$Values)
    $set = @{}
    foreach ($value in @($Values)) {
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $set[$value.Trim().ToLowerInvariant()] = $true
        }
    }
    return $set
}

function Get-ArgumentArraySha256 {
    param([string[]]$Arguments)

    $signatureText = [string]::Join("`u{001f}", @($Arguments))
    $signatureBytes = [System.Text.Encoding]::UTF8.GetBytes($signatureText)
    return [Convert]::ToHexString(
        [System.Security.Cryptography.SHA256]::HashData($signatureBytes)
    ).ToLowerInvariant()
}

function Add-LlamaCppTextArgs {
    param([string[]]$Arguments)
    $result = @($Arguments)
    if (-not [string]::IsNullOrWhiteSpace($TextLlamaCppModel)) {
        $result += @("--text-llama-cpp-model", $TextLlamaCppModel)
    }
    if (-not [string]::IsNullOrWhiteSpace($TextLlamaCppMmproj)) {
        $result += @("--text-llama-cpp-mmproj", $TextLlamaCppMmproj)
    }
    # Contracts must use the SAME model as the vision server: a mismatched
    # contract model forced a server model swap around every uncached contract
    # generation (~2x40s), and it structurally cannot be served by the shared
    # llama server (attach-time validation refuses serving two models). Qwen
    # 3.5 9B is the audited best local model for this task anyway.
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppModel)) {
        $result += @("--exercise-contract-llama-cpp-model", $LlamaCppModel)
    }
    return $result
}

function Add-LlamaCppTuningArgs {
    param([string[]]$Arguments)
    $result = @($Arguments)
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppMtpModel)) {
        $result += @("--llama-cpp-mtp-model", $LlamaCppMtpModel, "--llama-cpp-spec-draft-n-max", "$LlamaCppSpecDraftNMax")
    } else {
        $result += "--no-llama-cpp-mtp"
    }
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
    if ($null -ne $LlamaCppImageMinTokens) {
        $result += @("--llama-cpp-image-min-tokens", "$LlamaCppImageMinTokens")
    }
    if ($null -ne $LlamaCppImageMaxTokens) {
        $result += @("--llama-cpp-image-max-tokens", "$LlamaCppImageMaxTokens")
    }
    if ($null -ne $LlamaCppMtmdBatchMaxTokens) {
        $result += @("--llama-cpp-mtmd-batch-max-tokens", "$LlamaCppMtmdBatchMaxTokens")
    }
    if (-not $LlamaCppMmap) {
        $result += "--no-llama-cpp-mmap"
    }
    if ($LlamaCppMlock) {
        $result += "--llama-cpp-mlock"
    }
    return $result
}

function Ensure-LlamaCppParallelContext {
    $minContextPerSlot = 16384
    $parallelSlots = if ($null -ne $LlamaCppParallel) { [Math]::Max(1, [int]$LlamaCppParallel) } else { 1 }
    $minTotalContext = $parallelSlots * $minContextPerSlot
    if ($null -ne $LlamaCppCtxSize -and $LlamaCppCtxSize -lt $minTotalContext) {
        Write-Host ("Raising llama.cpp ctx-size from {0} to {1} so {2} parallel slot(s) keep at least {3} context tokens each." -f $LlamaCppCtxSize, $minTotalContext, $parallelSlots, $minContextPerSlot)
        $script:LlamaCppCtxSize = $minTotalContext
    }
    if ($null -ne $LlamaCppFitCtx -and $null -ne $LlamaCppCtxSize -and $LlamaCppFitCtx -lt $LlamaCppCtxSize) {
        Write-Host ("Raising llama.cpp fit-ctx from {0} to {1} to match ctx-size." -f $LlamaCppFitCtx, $LlamaCppCtxSize)
        $script:LlamaCppFitCtx = $LlamaCppCtxSize
    }
}

function ConvertTo-SlugSet {
    param([string[]]$Values)
    $set = @{}
    foreach ($value in @($Values)) {
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $set[(ConvertTo-Slug $value)] = $true
        }
    }
    return $set
}

function Resolve-StrictPathList {
    param([string[]]$PathValues)
    $resolved = @()
    foreach ($pathValue in @($PathValues)) {
        if (-not [string]::IsNullOrWhiteSpace($pathValue)) {
            $resolved += (Resolve-StrictPath $pathValue)
        }
    }
    return [string[]]$resolved
}

function Add-UnboundExclusionArguments {
    param(
        [string[]]$WorkspaceRoots,
        [string[]]$CandidateJsonPaths,
        [string[]]$VideoIds,
        [string[]]$Urls,
        [object[]]$UnboundArguments
    )

    $nextWorkspaceRoots = @($WorkspaceRoots)
    $nextCandidateJsonPaths = @($CandidateJsonPaths)
    $nextVideoIds = @($VideoIds)
    $nextUrls = @($Urls)

    foreach ($rawValue in @($UnboundArguments)) {
        $value = [string]$rawValue
        if ([string]::IsNullOrWhiteSpace($value) -or $value.StartsWith("-")) {
            continue
        }
        if (Test-Path -LiteralPath $value -PathType Container) {
            $nextWorkspaceRoots += $value
            continue
        }
        if (Test-Path -LiteralPath $value -PathType Leaf) {
            $nextCandidateJsonPaths += $value
            continue
        }
        if ($value -match "^https?://") {
            $nextUrls += $value
            continue
        }
        if ($value -match "^[A-Za-z0-9_-]{11}$") {
            $nextVideoIds += $value
            continue
        }
        Write-Warning "Ignoring unbound argument '$value'. If this was intended as an exclusion, pass an existing workspace directory, candidate JSON path, YouTube URL, or video id."
    }

    return [pscustomobject]@{
        workspaceRoots = [string[]]($nextWorkspaceRoots | Select-Object -Unique)
        candidateJsonPaths = [string[]]($nextCandidateJsonPaths | Select-Object -Unique)
        videoIds = [string[]]($nextVideoIds | Select-Object -Unique)
        urls = [string[]]($nextUrls | Select-Object -Unique)
    }
}

function Add-ExistingPath {
    param(
        [string[]]$Paths,
        [string]$CandidatePath
    )
    if (-not [string]::IsNullOrWhiteSpace($CandidatePath) -and (Test-Path -LiteralPath $CandidatePath)) {
        return [string[]]@($Paths + (Resolve-StrictPath $CandidatePath))
    }
    return [string[]]$Paths
}

function Get-PreviousCandidateJsonPaths {
    param(
        [string[]]$WorkspaceRoots,
        [string]$ExerciseSlug,
        # A prepared-candidates run installs its fixed source list at the same
        # path this scan collects; never exclude that file from this run.
        [string]$PreservePath
    )
    $paths = @()
    foreach ($workspaceRoot in @($WorkspaceRoots)) {
        if ([string]::IsNullOrWhiteSpace($workspaceRoot)) {
            continue
        }
        $exerciseWorkspace = Join-Path $workspaceRoot $ExerciseSlug
        $paths = Add-ExistingPath -Paths $paths -CandidatePath (Join-Path $exerciseWorkspace "youtube_candidates.json")
        $paths = Add-ExistingPath -Paths $paths -CandidatePath (Join-Path $exerciseWorkspace "selected\debug\youtube_candidates.full.json")
        $paths = Add-ExistingPath -Paths $paths -CandidatePath (Join-Path $exerciseWorkspace "bake\selection_manifest.json")
        $paths = Add-ExistingPath -Paths $paths -CandidatePath (Join-Path $exerciseWorkspace "selected\selection_manifest.json")
    }
    if (-not [string]::IsNullOrWhiteSpace($PreservePath)) {
        $paths = @($paths | Where-Object { [string]::Compare($_, $PreservePath, $true) -ne 0 })
    }
    return [string[]]($paths | Select-Object -Unique)
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
    $pythonExitCode = $LASTEXITCODE
    if ((Test-MotionRunCancelRequested) -or $pythonExitCode -eq 130) {
        Write-MotionInterruptReceived
        exit 130
    }
    if ($pythonExitCode -ne 0) {
        throw "python command failed with exit code $pythonExitCode."
    }
}

function Get-ObjectProperty {
    param(
        [object]$Object,
        [string]$Name
    )
    if ($null -eq $Object) {
        return $null
    }
    if ($Object -is [System.Collections.IDictionary] -and $Object.Contains($Name)) {
        return $Object[$Name]
    }
    if ($Object.PSObject.Properties.Name -contains $Name) {
        return $Object.$Name
    }
    return $null
}

function Resolve-WaveSourceSelectionPolicyVersion {
    param([object]$Source)

    $reportedVersion = Get-ObjectProperty -Object $Source -Name 'sourceSelectionPolicyVersion'
    if ($null -ne $reportedVersion -and [int]$reportedVersion -gt 0) {
        return [int]$reportedVersion
    }
    if ([int]$SourceSelectionPolicyVersion -gt 0) {
        return [int]$SourceSelectionPolicyVersion
    }
    throw 'Cannot persist a source-turn cursor without a valid source-selection policy version.'
}

function Get-OptionalDouble {
    param([object]$Value)
    if ($null -eq $Value) {
        return $null
    }
    try {
        return [double]$Value
    } catch {
        return $null
    }
}

function Add-OptionalSeconds {
    param(
        [object]$Current,
        [object]$Value
    )
    $currentValue = Get-OptionalDouble -Value $Current
    if ($null -eq $currentValue) {
        $currentValue = 0.0
    }
    $nextValue = Get-OptionalDouble -Value $Value
    if ($null -eq $nextValue) {
        return [Math]::Round($currentValue, 3)
    }
    return [Math]::Round(($currentValue + $nextValue), 3)
}

function Get-CandidateManifestCounts {
    param([string]$Path, [object]$Payload)
    $counts = [ordered]@{
        candidateCount = 0
        recommendedCount = 0
    }
    if ($null -eq $Payload -and ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path))) {
        return $counts
    }
    try {
        if ($null -eq $Payload) {
            $Payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-ReconstructionJson
        }
        foreach ($exercise in @($payload.exercises)) {
            foreach ($item in @($exercise.candidates)) {
                $counts.candidateCount += 1
                if ("$($item.status)".ToLowerInvariant() -eq "recommended") {
                    $counts.recommendedCount += 1
                }
            }
        }
    } catch {
        return $counts
    }
    return $counts
}

function Get-DefinitionReviewReason {
    param([object]$Payload)
    $entry = @($Payload.exercises | Where-Object { $_.status -eq "needs_definition_review" } | Select-Object -First 1)
    if ($entry.Count -eq 0 -and $Payload.status -eq "needs_definition_review") {
        $entry = @($Payload)
    }
    if ($entry.Count -eq 0) { return $null }
    $reason = [string]$entry[0].reason
    if ([string]::IsNullOrWhiteSpace($reason)) { return "Target action definition is unresolved." }
    return $reason
}

function Get-SchedulerTimelineTimestamp {
    return (Get-Date).ToUniversalTime().ToString("o")
}

function Write-SchedulerTimeline {
    # Scheduler telemetry must never break a run: any write failure is swallowed.
    try {
        if ([string]::IsNullOrWhiteSpace($script:SchedulerTimelinePath)) {
            return
        }
        $timeline = [ordered]@{
            schemaVersion = 1
            runStartedAtUtc = $script:SchedulerTimelineRunStartedAtUtc
            items = @($script:SchedulerTimelineItemsBySlug.Values)
            waves = @($script:SchedulerTimelineWaves)
        }
        $timeline | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $script:SchedulerTimelinePath -Encoding UTF8
    } catch {
        Write-Verbose "Scheduler timeline write failed: $($_.Exception.Message)"
    }
}

function Add-SchedulerTimelineItemEvent {
    param(
        [Parameter(Mandatory = $true)]
        [object]$WorkItem,
        [string]$ReadyReason,
        [switch]$MarkEnqueued,
        [string]$WaveId,
        [switch]$MarkAdmitted,
        [switch]$MarkAccepted,
        [string]$FinalStatus,
        [string]$Timestamp
    )

    try {
        $slug = "$($WorkItem.exerciseSlug)"
        if ([string]::IsNullOrWhiteSpace($slug) -or [string]::IsNullOrWhiteSpace($script:SchedulerTimelinePath)) {
            return
        }
        $item = $script:SchedulerTimelineItemsBySlug[$slug]
        if ($null -eq $item) {
            $item = [ordered]@{
                exerciseId = "$($WorkItem.exerciseId)"
                exerciseSlug = $slug
                readyAtUtc = $null
                readyReason = $null
                enqueuedAtUtc = $null
                waveId = $null
                admittedAtUtc = $null
                firstAcceptedAtUtc = $null
                materializedAtUtc = $null
                finalStatus = $null
            }
            $script:SchedulerTimelineItemsBySlug[$slug] = $item
        }
        $now = if ([string]::IsNullOrWhiteSpace($Timestamp)) { Get-SchedulerTimelineTimestamp } else { $Timestamp }
        # readyAtUtc/readyReason record when the item first became ready.
        if (-not [string]::IsNullOrWhiteSpace($ReadyReason) -and [string]::IsNullOrWhiteSpace("$($item['readyReason'])")) {
            $item["readyAtUtc"] = $now
            $item["readyReason"] = $ReadyReason
        }
        if ($MarkEnqueued -and [string]::IsNullOrWhiteSpace("$($item['enqueuedAtUtc'])")) {
            $item["enqueuedAtUtc"] = $now
        }
        if ($MarkAdmitted) {
            $item["waveId"] = $WaveId
            $item["admittedAtUtc"] = $now
        }
        if ($MarkAccepted -and [string]::IsNullOrWhiteSpace("$($item['firstAcceptedAtUtc'])")) {
            $item["firstAcceptedAtUtc"] = $now
        }
        if (-not [string]::IsNullOrWhiteSpace($FinalStatus)) {
            $item["finalStatus"] = $FinalStatus
            if ($FinalStatus -eq "materialized" -and [string]::IsNullOrWhiteSpace("$($item['materializedAtUtc'])")) {
                $item["materializedAtUtc"] = $now
            }
        }
        Write-SchedulerTimeline
    } catch {
        Write-Verbose "Scheduler timeline item event failed: $($_.Exception.Message)"
    }
}

function Add-SchedulerTimelineWaveEvent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WaveId,
        [Parameter(Mandatory = $true)]
        [string]$AdmissionReason,
        [Parameter(Mandatory = $true)]
        [int]$ItemCount,
        [Parameter(Mandatory = $true)]
        [int]$ConcurrentWaveCountAtAdmission,
        [string]$Timestamp
    )

    try {
        if ([string]::IsNullOrWhiteSpace($script:SchedulerTimelinePath)) {
            return
        }
        $script:SchedulerTimelineWaves += [ordered]@{
            waveId = $WaveId
            admittedAtUtc = if ([string]::IsNullOrWhiteSpace($Timestamp)) { Get-SchedulerTimelineTimestamp } else { $Timestamp }
            admissionReason = $AdmissionReason
            itemCount = $ItemCount
            concurrentWaveCountAtAdmission = $ConcurrentWaveCountAtAdmission
        }
        Write-SchedulerTimeline
    } catch {
        Write-Verbose "Scheduler timeline wave event failed: $($_.Exception.Message)"
    }
}

function Get-SelectionTimingSummary {
    param([object]$Selection)
    $summary = [ordered]@{
        totalSeconds = $null
        candidateProcessingSeconds = $null
        processedCandidateCount = $null
        readyCandidateCount = $null
        reviewRankingSeconds = $null
        selectionMaterializationSeconds = $null
        sourcePreparationSeconds = 0.0
        reconstructionRunSeconds = 0.0
        reconstructionDockerLockWaitSeconds = 0.0
        previewBakeSeconds = 0.0
        reconstructionGeneratedCount = 0
        reconstructionReusedCount = 0
        reconstructionExplicitCount = 0
        reconstructionNotUsedCount = 0
        warmReconstructionWorkerJobCount = 0
    }
    if ($null -eq $Selection) {
        return $summary
    }
    $pipelineTimings = Get-ObjectProperty -Object $Selection -Name "timings"
    foreach ($name in @("totalSeconds", "candidateProcessingSeconds", "processedCandidateCount", "readyCandidateCount", "reviewRankingSeconds", "selectionMaterializationSeconds")) {
        $summary[$name] = Get-ObjectProperty -Object $pipelineTimings -Name $name
    }
    foreach ($candidate in @(Get-ObjectProperty -Object $Selection -Name "candidateResults")) {
        $candidateTimings = Get-ObjectProperty -Object $candidate -Name "timings"
        $generationTimings = Get-ObjectProperty -Object $candidate -Name "generationTimings"
        $summary.sourcePreparationSeconds = Add-OptionalSeconds -Current $summary.sourcePreparationSeconds -Value (Get-ObjectProperty -Object $generationTimings -Name "sourcePreparationSeconds")
        $summary.previewBakeSeconds = Add-OptionalSeconds -Current $summary.previewBakeSeconds -Value (Get-ObjectProperty -Object $candidateTimings -Name "previewBakeSeconds")
        $reconstructionTiming = Get-ObjectProperty -Object $generationTimings -Name "reconstruction"
        if ((Get-ObjectProperty -Object $reconstructionTiming -Name "warmWorker") -eq $true) {
            $summary.warmReconstructionWorkerJobCount += 1
        }
        $summary.reconstructionRunSeconds = Add-OptionalSeconds -Current $summary.reconstructionRunSeconds -Value (Get-ObjectProperty -Object $reconstructionTiming -Name "elapsedSeconds")
        $summary.reconstructionDockerLockWaitSeconds = Add-OptionalSeconds -Current $summary.reconstructionDockerLockWaitSeconds -Value (Get-ObjectProperty -Object $reconstructionTiming -Name "dockerLockWaitSeconds")
        $reconstructionCacheStatus = [string](Get-ObjectProperty -Object $candidate -Name "reconstructionCacheStatus")
        if ([string]::IsNullOrWhiteSpace($reconstructionCacheStatus)) {
            $reconstructionCacheStatus = [string](Get-ObjectProperty -Object $reconstructionTiming -Name "cacheStatus")
        }
        switch -Regex ($reconstructionCacheStatus) {
            "^generated" { $summary.reconstructionGeneratedCount += 1; break }
            "^reused" { $summary.reconstructionReusedCount += 1; break }
            "^explicit" { $summary.reconstructionExplicitCount += 1; break }
            "^not_used" { $summary.reconstructionNotUsedCount += 1; break }
        }
    }
    return $summary
}

function New-TerminalExerciseSummary {
    param(
        [object]$WorkItem,
        [string]$Status,
        [string]$ErrorMessage,
        [string]$Stage,
        [object]$ExitCode
    )
    $counts = Get-CandidateManifestCounts -Path $WorkItem.exerciseCandidatesPath
    return [ordered]@{
        exerciseId = $WorkItem.exerciseId
        exerciseName = $WorkItem.exerciseName
        status = $Status
        error = $ErrorMessage
        stage = $Stage
        exitCode = $ExitCode
        candidateCount = $counts.candidateCount
        recommendedCandidateCount = $counts.recommendedCount
        excludeCandidateJsonPaths = $WorkItem.excludeCandidateJsonPaths
        candidatesJsonPath = $WorkItem.exerciseCandidatesPath
        selectionManifestPath = Join-Path $WorkItem.bakeWorkspace "selection_manifest.json"
        logPath = $WorkItem.logPath
        selectedWearSkeletonPath = $null
        selectedPreviewVideoPath = $null
        selectedSourceVideoPath = $null
        selectedSourceVideoWebmPath = $null
        selectedSourceVideoOriginalPath = $null
        selectedSourceVideoMissing = $false
        selectedResults = @()
        selectedCandidateDebugPath = $null
        selectedCandidateDecisionsPath = $null
        attempts = @($WorkItem.attempts)
        timings = [ordered]@{
            prefetchSeconds = [Math]::Round([double]$WorkItem.prefetchSeconds, 3)
            prefetchReused = [bool]$WorkItem.prefetchReused
            discoverySeconds = [Math]::Round([double]$WorkItem.discoverySeconds, 3)
            discoveryReused = [bool]$WorkItem.discoveryReused
            sourceDownloadSeconds = [Math]::Round([double]$WorkItem.sourceDownloadSeconds, 3)
            primarySourceDownloadReused = [bool]$WorkItem.primarySourceDownloadReused
            fallbackSourceDownloadReused = [bool]$WorkItem.fallbackSourceDownloadReused
            bakeCommandSeconds = [Math]::Round([double]$WorkItem.bakeCommandSeconds, 3)
            bakeReused = [bool]$WorkItem.bakeReused
            discoveryAttempts = [int]$WorkItem.discoveryAttemptCount
            bakeAttempts = [int]$WorkItem.bakeAttemptCount
        }
    }
}

function New-ExerciseCandidateManifest {
    param(
        [object]$Exercise,
        [string]$OutPath
    )
    $manifest = [ordered]@{
        schemaVersion = 1
        sourcePlanPath = $resolvedWorkoutPlanJson
        generatedAt = (Get-Date).ToUniversalTime().ToString("o")
        ranking = $candidateManifest.ranking
        exercises = @($Exercise)
    }
    $manifest | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $OutPath -Encoding UTF8
}

function New-OneExercisePlanJson {
    param(
        [object]$Exercise,
        [string]$OutPath
    )
    $exerciseRecord = [ordered]@{
        id = [string]($Exercise.exerciseId ?? $Exercise.id ?? $Exercise.slug ?? $Exercise.exerciseName ?? "exercise")
        name = [string]($Exercise.exerciseName ?? $Exercise.name ?? $Exercise.id ?? "exercise")
    }
    foreach ($propertyName in @("sourceExerciseName", "equipmentQualifiedExerciseName", "exerciseNameRewrite", "motionContext", "definitionReadiness")) {
        if ($Exercise.PSObject.Properties.Name -contains $propertyName) {
            $exerciseRecord[$propertyName] = $Exercise.$propertyName
        }
    }
    $plan = [ordered]@{
        schemaVersion = 1
        sourcePlanPath = $resolvedWorkoutPlanJson
        exercises = @($exerciseRecord)
    }
    $plan | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutPath -Encoding UTF8
}

function Copy-SelectedFile {
    param(
        [string]$SourcePath,
        [string]$DestinationDirectory,
        [string]$DestinationFileName
    )
    if ([string]::IsNullOrWhiteSpace($SourcePath) -or -not (Test-Path -LiteralPath $SourcePath)) {
        return $null
    }
    New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    $destinationPath = Join-Path $DestinationDirectory $DestinationFileName
    Copy-Item -LiteralPath $SourcePath -Destination $destinationPath -Force
    return $destinationPath
}

function Copy-SelectedFinalRenderContactSheets {
    param(
        [object]$SelectionEntry,
        [string]$DestinationDirectory,
        [int]$OptionIndex
    )

    $ranking = Get-ObjectProperty -Object $SelectionEntry -Name "ranking"
    $rankingPayload = Get-ObjectProperty -Object $ranking -Name "payload"
    $finalValidation = Get-ObjectProperty -Object $rankingPayload -Name "finalOutputValidation"
    $renderEvidence = Get-ObjectProperty -Object $finalValidation -Name "renderEvidence"
    $sourcePaths = @(Get-ObjectProperty -Object $renderEvidence -Name "contactSheetPaths") |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
    if ($sourcePaths.Count -eq 0) {
        throw "Selected option $OptionIndex has no final render contact sheets to retain."
    }

    $optionDirectory = Join-Path $DestinationDirectory ("final_render_evidence\option_{0:D2}" -f $OptionIndex)
    $copiedPaths = @()
    $sheetIndex = 1
    foreach ($sourcePath in $sourcePaths) {
        $sourcePath = [string]$sourcePath
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Final render contact sheet is missing before artifact promotion: $sourcePath"
        }
        $extension = [System.IO.Path]::GetExtension($sourcePath)
        if ([string]::IsNullOrWhiteSpace($extension)) {
            $extension = ".jpg"
        }
        $fileName = "contact_sheet_{0:D2}{1}" -f $sheetIndex, $extension
        $destinationPath = Copy-SelectedFile `
            -SourcePath $sourcePath `
            -DestinationDirectory $optionDirectory `
            -DestinationFileName $fileName
        if ([string]::IsNullOrWhiteSpace($destinationPath) -or
            -not (Test-Path -LiteralPath $destinationPath -PathType Leaf)) {
            throw "Could not retain final render contact sheet: $sourcePath"
        }
        $copiedPaths += $destinationPath
        $sheetIndex += 1
    }
    return ,$copiedPaths
}

function Update-PackagedSelectionArtifactReferences {
    param(
        [string]$SelectionManifestPath,
        [int]$OptionIndex,
        [string]$SelectedOutputDirectory,
        [string]$AuditOutputDirectory,
        [string]$PackagedSkeletonPath,
        [string]$ReviewVideoPath,
        [string]$InputVideoPath,
        [string]$InputSourceVideoPath,
        [string]$PreviewHtmlPath,
        [string]$InteractivePreviewHtmlPath,
        [string[]]$ContactSheetPaths
    )

    if (-not (Test-Path -LiteralPath $SelectionManifestPath -PathType Leaf)) {
        throw "Selected output manifest disappeared before its artifact paths were updated."
    }
    $selection = Get-Content -LiteralPath $SelectionManifestPath -Raw | ConvertFrom-ReconstructionJson
    $selectedIndex = $OptionIndex - 1
    $selectedResults = @(Get-ObjectProperty -Object $selection -Name "selectedResults")
    $record = @($selectedResults | Where-Object {
        [int](Get-ObjectProperty -Object $_ -Name "selectedResultIndex") -eq $selectedIndex
    } | Select-Object -First 1)
    if ($record.Count -eq 0) {
        throw "Selected option $OptionIndex is missing from the copied selection manifest."
    }
    $record = $record[0]

    $sourceCandidateWorkspace = [string](Get-ObjectProperty -Object $record -Name "candidateWorkspace")
    if (-not [string]::IsNullOrWhiteSpace($sourceCandidateWorkspace)) {
        $record | Add-Member -NotePropertyName "sourceCandidateWorkspace" `
            -NotePropertyValue $sourceCandidateWorkspace -Force
        $record | Add-Member -NotePropertyName "candidateWorkspace" `
            -NotePropertyValue $SelectedOutputDirectory -Force
    }
    foreach ($propertyName in @("skeletonPath", "selectedWearSkeletonPath", "packagedWearSkeletonPath")) {
        $record | Add-Member -NotePropertyName $propertyName -NotePropertyValue $PackagedSkeletonPath -Force
    }
    foreach ($propertyName in @("reviewVideoPath", "selectedReviewVideoPath", "selectedPreviewVideoPath")) {
        if (-not [string]::IsNullOrWhiteSpace($ReviewVideoPath)) {
            $record | Add-Member -NotePropertyName $propertyName -NotePropertyValue $ReviewVideoPath -Force
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($InputVideoPath)) {
        $record | Add-Member -NotePropertyName "selectedInputVideoPath" -NotePropertyValue $InputVideoPath -Force
        $record | Add-Member -NotePropertyName "inputVideoPath" -NotePropertyValue $InputVideoPath -Force
    }
    if (-not [string]::IsNullOrWhiteSpace($InputSourceVideoPath)) {
        $record | Add-Member -NotePropertyName "selectedInputSourceVideoPath" `
            -NotePropertyValue $InputSourceVideoPath -Force
    }
    foreach ($propertyName in @("previewHtmlPath", "selectedPreviewHtmlPath")) {
        if (-not [string]::IsNullOrWhiteSpace($PreviewHtmlPath)) {
            $record | Add-Member -NotePropertyName $propertyName -NotePropertyValue $PreviewHtmlPath -Force
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($InteractivePreviewHtmlPath)) {
        $record | Add-Member -NotePropertyName "sourcePreviewHtmlPath" `
            -NotePropertyValue $InteractivePreviewHtmlPath -Force
    }
    $manifestCopy = Join-Path $AuditOutputDirectory "processing_evidence\manifest.json"
    if (Test-Path -LiteralPath $manifestCopy -PathType Leaf) {
        $record | Add-Member -NotePropertyName "manifestPath" -NotePropertyValue $manifestCopy -Force
    }

    $ranking = Get-ObjectProperty -Object $record -Name "ranking"
    $rankingPayload = Get-ObjectProperty -Object $ranking -Name "payload"
    $finalValidation = Get-ObjectProperty -Object $rankingPayload -Name "finalOutputValidation"
    $renderEvidence = Get-ObjectProperty -Object $finalValidation -Name "renderEvidence"
    if ($null -eq $renderEvidence) {
        throw "Selected option $OptionIndex has no final render evidence to retain."
    }
    $renderEvidence | Add-Member -NotePropertyName "contactSheetPaths" `
        -NotePropertyValue @($ContactSheetPaths) -Force

    if ($selectedIndex -eq 0) {
        if ($null -eq $selection.selected) {
            throw "The copied selection manifest has no primary selected artifact."
        }
        $selection.selected = $record
        if (-not [string]::IsNullOrWhiteSpace($PreviewHtmlPath)) {
            $selection.selectedPreviewHtmlPath = $PreviewHtmlPath
        }
    }
    Write-AtomicJsonDocument -Path $SelectionManifestPath -InputObject $selection -Depth 100
}

function Get-WearSkeletonIdentity {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Cannot identify missing Wear skeleton: $Path"
    }
    $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-ReconstructionJson
    $frames = Get-ObjectProperty -Object $payload -Name "frames"
    return [ordered]@{
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        frameCount = @($frames).Count
    }
}

function Add-StagedWaveTimelineOutcome {
    param(
        [Parameter(Mandatory = $true)]
        [object]$WorkItem,
        [Parameter(Mandatory = $true)]
        [object]$WaveState
    )

    $artifactLifecycle = Get-ObjectProperty -Object $WaveState -Name 'artifactLifecycle'
    $artifactState = "$(Get-ObjectProperty -Object $artifactLifecycle -Name 'state')"
    if ($artifactState -eq "accepted") {
        Add-SchedulerTimelineItemEvent -WorkItem $WorkItem -MarkAccepted -FinalStatus "accepted"
    } elseif ($artifactState -eq "manual_review") {
        Add-SchedulerTimelineItemEvent -WorkItem $WorkItem -FinalStatus "needs_manual_review"
    } else {
        Add-SchedulerTimelineItemEvent -WorkItem $WorkItem -FinalStatus "unverified_completion"
    }
}

function ConvertTo-CanonicalArtifactStateJson {
    param([object]$Value)

    if ($null -eq $Value) {
        return "null"
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $properties = @()
        foreach ($key in @($Value.Keys | Sort-Object -CaseSensitive)) {
            $keyJson = ConvertTo-Json -InputObject ([string]$key) -Compress
            $valueJson = ConvertTo-CanonicalArtifactStateJson -Value $Value[$key]
            $properties += "${keyJson}:$valueJson"
        }
        return "{$($properties -join ',')}"
    }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $properties = @()
        foreach ($property in @($Value.PSObject.Properties | Sort-Object -Property Name -CaseSensitive)) {
            $keyJson = ConvertTo-Json -InputObject ([string]$property.Name) -Compress
            $valueJson = ConvertTo-CanonicalArtifactStateJson -Value $property.Value
            $properties += "${keyJson}:$valueJson"
        }
        return "{$($properties -join ',')}"
    }
    if ($Value -is [array]) {
        $items = @()
        foreach ($item in $Value) {
            $items += (ConvertTo-CanonicalArtifactStateJson -Value $item)
        }
        return "[$($items -join ',')]"
    }
    return [string](ConvertTo-Json -InputObject $Value -Compress -Depth 100)
}

function Assert-PersistedMovementArtifactState {
    param(
        [object]$SelectionEntry,
        [switch]$ManualReviewFallback
    )

    $artifactState = Get-ObjectProperty -Object $SelectionEntry -Name "artifactState"
    if ($null -eq $artifactState) {
        throw "Selected movement is missing its persisted artifact state."
    }
    $stateJson = ConvertTo-Json -InputObject $artifactState -Compress -Depth 100
    $validationCode = "import json,sys; from exercise_motion_pkg.artifact_state import validate_artifact_state; state=validate_artifact_state(json.loads(sys.argv[1])); print(json.dumps({key:state.get(key) for key in ('artifactClass','terminal','lineageComplete','requiredClass','history','selectionEvidence')},separators=(',',':')))"
    $validationOutput = @(Invoke-PythonModule -Arguments @(
        "-c",
        $validationCode,
        $stateJson
    ))
    $validationJson = ($validationOutput -join [Environment]::NewLine).Trim()
    if ([string]::IsNullOrWhiteSpace($validationJson)) {
        throw "Python artifact state validator returned no movement state."
    }
    $validatedState = $validationJson | ConvertFrom-ReconstructionJson -ErrorAction Stop
    $entryArtifactClass = [string](Get-ObjectProperty -Object $SelectionEntry -Name "artifactClass")
    if ([string]$validatedState.artifactClass -ne $entryArtifactClass) {
        throw "Selected movement artifact class differs from its persisted state."
    }
    if (-not $ManualReviewFallback -and -not [bool]$validatedState.terminal) {
        throw "Selected artifact class '$($validatedState.artifactClass)' is not terminal for its movement contract."
    }
    return [ordered]@{
        artifactClass = [string]$validatedState.artifactClass
        terminal = [bool]$validatedState.terminal
        lineageComplete = $validatedState.lineageComplete
        requiredClass = $validatedState.requiredClass
        history = @($validatedState.history)
        selectionEvidence = $validatedState.selectionEvidence
    }
}

function New-PackagedArtifactState {
    param(
        [object]$MovementState,
        [string]$PackageClass
    )

    $builderMovementState = [ordered]@{
        schemaVersion = 1
        artifactClass = $MovementState.artifactClass
        requiredClass = $MovementState.requiredClass
        terminal = $MovementState.terminal
        lineageComplete = $MovementState.lineageComplete
        history = @($MovementState.history)
        selectionEvidence = $MovementState.selectionEvidence
    }
    $movementStateJson = ConvertTo-Json -InputObject $builderMovementState -Compress -Depth 100
    $builderCode = "import json,sys; from exercise_motion_pkg.artifact_state import build_packaged_artifact_state; print(json.dumps(build_packaged_artifact_state(json.loads(sys.argv[1]),package_class=sys.argv[2]),separators=(',',':')))"
    $builderOutput = @(Invoke-PythonModule -Arguments @(
        "-c",
        $builderCode,
        $movementStateJson,
        $PackageClass
    ))
    $builderJson = ($builderOutput -join [Environment]::NewLine).Trim()
    if ([string]::IsNullOrWhiteSpace($builderJson)) {
        throw "Python artifact state builder returned no packaged state."
    }
    return ($builderJson | ConvertFrom-ReconstructionJson -ErrorAction Stop)
}

function Assert-SelectedSkeletonReviewParity {
    param(
        [object]$SelectionEntry,
        [string]$SourcePath,
        [string]$PackagedPath,
        [switch]$ManualReviewFallback
    )

    $movementState = Assert-PersistedMovementArtifactState -SelectionEntry $SelectionEntry -ManualReviewFallback:$ManualReviewFallback
    $artifactClass = $movementState.artifactClass
    $artifactHistory = $movementState.history

    $sourcePayload = Get-Content -LiteralPath $SourcePath -Raw | ConvertFrom-ReconstructionJson
    $embeddedArtifactState = Get-ObjectProperty -Object $sourcePayload -Name "artifactState"
    if ($null -eq $embeddedArtifactState) {
        throw "Selected skeleton is missing its persisted artifact state."
    }
    $artifactStateValidationCode = "import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from exercise_motion_pkg.artifact_state import validate_artifact_state; payload=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')); validate_artifact_state(payload.get('artifactState'),movement_payload=payload)"
    Invoke-PythonModule -Arguments @(
        "-c",
        $artifactStateValidationCode,
        $repoRoot,
        $SourcePath
    )
    $manifestStateJson = ConvertTo-CanonicalArtifactStateJson -Value (Get-ObjectProperty -Object $SelectionEntry -Name "artifactState")
    $embeddedStateJson = ConvertTo-CanonicalArtifactStateJson -Value $embeddedArtifactState
    if ($manifestStateJson -cne $embeddedStateJson) {
        throw "Selected skeleton artifact state differs from the validated selection manifest state."
    }

    $ranking = Get-ObjectProperty -Object $SelectionEntry -Name "ranking"
    $rankingPayload = Get-ObjectProperty -Object $ranking -Name "payload"
    $finalValidation = Get-ObjectProperty -Object $rankingPayload -Name "finalOutputValidation"
    $renderEvidence = Get-ObjectProperty -Object $finalValidation -Name "renderEvidence"
    $renderedIdentity = Get-ObjectProperty -Object $renderEvidence -Name "skeletonIdentity"
    $reviewWindow = Get-ObjectProperty -Object $renderEvidence -Name "reviewWindow"
    $expectedHash = Get-ObjectProperty -Object $renderedIdentity -Name "sha256"
    if ([string]::IsNullOrWhiteSpace([string]$expectedHash)) {
        if ($ManualReviewFallback) {
            return [ordered]@{
                verified = $false
                reason = "review_identity_unavailable"
                artifactClass = $artifactClass
                artifactHistory = $artifactHistory
                requiredClass = $movementState.requiredClass
                parentTerminal = $movementState.terminal
                selectionEvidence = $movementState.selectionEvidence
            }
        }
        throw "Selected movement has no final-validation skeleton identity."
    }
    if (-not $ManualReviewFallback) {
        $classGate = Get-ObjectProperty -Object $finalValidation -Name "artifactClassGate"
        if ($null -eq $classGate -or (
            (Get-ObjectProperty -Object $classGate -Name "passed") -ne $true -or
            [string](Get-ObjectProperty -Object $classGate -Name "artifactClass") -ne $artifactClass
        )) {
            throw "Final validation did not approve the selected artifact class."
        }
        if ($null -eq $reviewWindow) {
            throw "Final validation has no persisted review window for the selected movement."
        }
    }
    if ($null -ne $reviewWindow) {
        $reviewFrameCount = Get-ObjectProperty -Object $reviewWindow -Name "frameCount"
        $reviewFrameIndices = Get-ObjectProperty -Object $reviewWindow -Name "frameIndices"
        $reviewSelection = Get-ObjectProperty -Object $reviewWindow -Name "selection"
        if ($null -eq $reviewFrameCount -or
            $null -eq $reviewFrameIndices -or @($reviewFrameIndices).Count -eq 0 -or
            [string](Get-ObjectProperty -Object $reviewSelection -Name "artifactClass") -ne $artifactClass) {
            throw "Final render review window is incomplete or names a different artifact class."
        }
        foreach ($frameIndex in @($reviewFrameIndices)) {
            if ([long]$frameIndex -lt 0 -or [long]$frameIndex -ge [long]$reviewFrameCount) {
                throw "Final render review window contains a frame outside the selected skeleton."
            }
        }
        if ($artifactClass -eq "cyclic_rebake" -or $artifactClass -eq "bounded_movement_rebake") {
            $selectionEvidence = $movementState.selectionEvidence
            $selectedLineage = if ($artifactClass -eq "cyclic_rebake") {
                Get-ObjectProperty -Object $selectionEvidence -Name "cycleSelection"
            } else {
                Get-ObjectProperty -Object $selectionEvidence -Name "boundedMovementSelection"
            }
            $expectedSelectionId = [string](Get-ObjectProperty -Object $selectedLineage -Name "selectionId")
            $expectedInterval = Get-ObjectProperty -Object $selectedLineage -Name "interval"
            $reviewedSelectionId = [string](Get-ObjectProperty -Object $reviewSelection -Name "selectionId")
            $reviewedInterval = Get-ObjectProperty -Object $reviewSelection -Name "interval"
            if ($expectedSelectionId -ne $reviewedSelectionId -or $null -eq $reviewedInterval) {
                throw "Final render review window does not identify the selected source interval."
            }
            foreach ($field in @("type", "startFrame", "endFrame", "startTimeSec", "endTimeSec", "durationSec")) {
                $expectedValue = Get-ObjectProperty -Object $expectedInterval -Name $field
                $reviewedValue = Get-ObjectProperty -Object $reviewedInterval -Name $field
                $mismatch = $null -eq $expectedValue -or $null -eq $reviewedValue
                if (-not $mismatch -and $field -eq "type") {
                    $mismatch = [string]$expectedValue -ne [string]$reviewedValue
                } elseif (-not $mismatch -and $field -match "Frame$") {
                    $mismatch = [long]$expectedValue -ne [long]$reviewedValue
                } elseif (-not $mismatch) {
                    $mismatch = [math]::Abs([double]$expectedValue - [double]$reviewedValue) -gt 0.000001
                }
                if ($mismatch) {
                    throw "Final render review interval differs from the artifact selection evidence."
                }
            }
        }
    }

    $sourceIdentity = Get-WearSkeletonIdentity -Path $SourcePath
    $packagedIdentity = Get-WearSkeletonIdentity -Path $PackagedPath
    $expectedFrameCount = Get-ObjectProperty -Object $renderedIdentity -Name "frameCount"
    if (
        $sourceIdentity.sha256 -ne [string]$expectedHash -or
        $packagedIdentity.sha256 -ne $sourceIdentity.sha256 -or
        ($null -ne $expectedFrameCount -and [int]$expectedFrameCount -ne [int]$packagedIdentity.frameCount)
    ) {
        throw "Packaged Wear skeleton does not match the skeleton reviewed by final validation."
    }
    if ($null -ne $reviewWindow -and [int]$reviewWindow.frameCount -ne [int]$packagedIdentity.frameCount) {
        throw "Final render review window frame count differs from the packaged skeleton."
    }
    return [ordered]@{
        verified = $true
        artifactClass = $artifactClass
        artifactHistory = $artifactHistory
        requiredClass = $movementState.requiredClass
        parentTerminal = $movementState.terminal
        selectionEvidence = $movementState.selectionEvidence
        sha256 = $packagedIdentity.sha256
        frameCount = $packagedIdentity.frameCount
    }
}

function Write-AtomicJsonDocument {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$InputObject,
        [int]$Depth = 100
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $parentPath = Split-Path -Parent $fullPath
    [System.IO.Directory]::CreateDirectory($parentPath) | Out-Null
    $temporaryPath = Join-Path $parentPath (".{0}.{1}.{2}.tmp" -f `
        [System.IO.Path]::GetFileName($fullPath), $PID, [guid]::NewGuid().ToString("N"))
    try {
        $json = ConvertTo-Json -InputObject $InputObject -Depth $Depth
        [System.IO.File]::WriteAllText(
            $temporaryPath,
            $json + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )
        [System.IO.File]::Move($temporaryPath, $fullPath, $true)
    } finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Record-PackagedSkeletonReviewParity {
    param(
        [string]$SelectionManifestPath,
        [int]$OptionIndex,
        [string]$PackagedPath,
        [object]$Parity,
        [switch]$ManualReviewFallback
    )

    if ([string]::IsNullOrWhiteSpace($SelectionManifestPath) -or
        -not (Test-Path -LiteralPath $SelectionManifestPath -PathType Leaf)) {
        throw "Copied selection manifest is missing; cannot persist packaged skeleton identity."
    }
    $selection = Get-Content -LiteralPath $SelectionManifestPath -Raw | ConvertFrom-ReconstructionJson
    if ($ManualReviewFallback) {
        $record = Get-ObjectProperty -Object $selection -Name "manualReviewFallback"
        if ($null -eq $record) {
            throw "Manual-review fallback is missing from the copied selection manifest."
        }
        if ((Get-ObjectProperty -Object $selection -Name "selectionStatus") -ne "needs_manual_review" -or
            (Get-ObjectProperty -Object $record -Name "selectionStatus") -ne "needs_manual_review") {
            throw "Manual-review package must retain the needs_manual_review status."
        }
        $movementState = Assert-PersistedMovementArtifactState -SelectionEntry $record -ManualReviewFallback
        if ($movementState.artifactClass -ne $Parity.artifactClass -or
            [string]::Join("|", @($movementState.history)) -ne [string]::Join("|", @($Parity.artifactHistory))) {
            throw "Manual-review package parent state differs from its validated artifact state."
        }
        $packageState = New-PackagedArtifactState -MovementState $movementState -PackageClass "manual_review_package"
        $record | Add-Member -NotePropertyName "packagedWearSkeletonPath" -NotePropertyValue $PackagedPath -Force
        $record | Add-Member -NotePropertyName "packagedSkeletonReviewParity" -NotePropertyValue $Parity -Force
        $record | Add-Member -NotePropertyName "packagedArtifactClass" -NotePropertyValue "manual_review_package" -Force
        $record | Add-Member -NotePropertyName "packagedArtifactState" -NotePropertyValue $packageState -Force
        Write-AtomicJsonDocument -Path $SelectionManifestPath -InputObject $selection -Depth 100
        return
    }
    $selectedIndex = $OptionIndex - 1
    $selectedResult = @($selection.selectedResults | Where-Object {
        [int](Get-ObjectProperty -Object $_ -Name "selectedResultIndex") -eq $selectedIndex
    } | Select-Object -First 1)
    if ($selectedResult.Count -eq 0) {
        throw "Selected option $OptionIndex is missing from the copied selection manifest."
    }
    $record = $selectedResult[0]
    if ((Get-ObjectProperty -Object $selection -Name "selectionStatus") -ne "selected") {
        throw "Accepted package does not have selected manifest status."
    }
    $movementState = Assert-PersistedMovementArtifactState -SelectionEntry $record
    if ($movementState.artifactClass -ne $Parity.artifactClass -or
        [string]::Join("|", @($movementState.history)) -ne [string]::Join("|", @($Parity.artifactHistory))) {
        throw "Accepted package parent state differs from its validated artifact state."
    }
    $packageState = New-PackagedArtifactState -MovementState $movementState -PackageClass "packaged_movement"
    $record | Add-Member -NotePropertyName "packagedWearSkeletonPath" -NotePropertyValue $PackagedPath -Force
    $record | Add-Member -NotePropertyName "packagedSkeletonReviewParity" -NotePropertyValue $Parity -Force
    $record | Add-Member -NotePropertyName "packagedArtifactClass" -NotePropertyValue "packaged_movement" -Force
    $record | Add-Member -NotePropertyName "packagedArtifactState" -NotePropertyValue $packageState -Force
    if ($selectedIndex -eq 0 -and $null -ne $selection.selected) {
        $selection.selected | Add-Member -NotePropertyName "packagedWearSkeletonPath" -NotePropertyValue $PackagedPath -Force
        $selection.selected | Add-Member -NotePropertyName "packagedSkeletonReviewParity" -NotePropertyValue $Parity -Force
        $selection.selected | Add-Member -NotePropertyName "packagedArtifactClass" -NotePropertyValue "packaged_movement" -Force
        $selection.selected | Add-Member -NotePropertyName "packagedArtifactState" -NotePropertyValue $record.packagedArtifactState -Force
    }
    Write-AtomicJsonDocument -Path $SelectionManifestPath -InputObject $selection -Depth 100
}

function Write-PublishedSelectionAcceptanceMarker {
    param(
        [object]$WorkItem,
        [string]$SelectedOutputDir,
        [string]$SelectionManifestPath
    )

    # Newly accepted keeps already passed current pipeline gates. Replace any
    # stale library-revalidation marker so resume reuse matches the published
    # selection instead of an older invalid verdict.
    if (
        [string]::IsNullOrWhiteSpace($SelectedOutputDir) -or
        [string]::IsNullOrWhiteSpace($SelectionManifestPath) -or
        -not (Test-Path -LiteralPath $SelectionManifestPath)
    ) {
        return
    }
    New-Item -ItemType Directory -Force -Path $SelectedOutputDir | Out-Null
    $markerPath = Join-Path $SelectedOutputDir "revalidation.json"
    $marker = [ordered]@{
        schemaVersion = 1
        selectionValidationPolicyVersion = [int]$SelectionValidationPolicyVersion
        sourceSelectionPolicyVersion = [int]$SourceSelectionPolicyVersion
        retainedSelectedArtifactFallbackVersion = [int]$RetainedSelectedRevalidationVersion
        validatedAt = (Get-Date).ToUniversalTime().ToString("o")
        exerciseId = "$($WorkItem.exerciseId)"
        exerciseName = "$($WorkItem.exerciseName)"
        status = "valid"
        reasons = @()
        retryable = $false
        selectedManifestSha256 = (Get-FileHash -LiteralPath $SelectionManifestPath -Algorithm SHA256).Hash
        publishedBy = "workout_plan_selected_output"
    }
    Write-AtomicJsonDocument -Path $markerPath -InputObject $marker -Depth 6
}

function Copy-SelectedPreviewRuntimeAssets {
    param(
        [string]$SourcePreviewHtmlPath,
        [string]$DestinationDirectory
    )
    if ([string]::IsNullOrWhiteSpace($SourcePreviewHtmlPath)) {
        return
    }
    $sourceDirectory = Split-Path -Parent $SourcePreviewHtmlPath
    if ([string]::IsNullOrWhiteSpace($sourceDirectory) -or -not (Test-Path -LiteralPath $sourceDirectory)) {
        return
    }
    foreach ($asset in @(Get-ChildItem -LiteralPath $sourceDirectory -Filter "three.module.*.js" -File -ErrorAction SilentlyContinue)) {
        Copy-SelectedFile `
            -SourcePath $asset.FullName `
            -DestinationDirectory $DestinationDirectory `
            -DestinationFileName $asset.Name | Out-Null
    }
}

function Copy-SelectedSourceAuditEvidence {
    param(
        [string]$CandidateWorkspace,
        [string]$DestinationDirectory
    )
    if ([string]::IsNullOrWhiteSpace($CandidateWorkspace)) {
        return $null
    }

    # Keep the small joint stages and timing provenance even when no source
    # phase cache exists. Final approval can be overturned by later audits.
    $processingEvidenceDirectory = Join-Path $DestinationDirectory "processing_evidence"
    foreach ($relativePath in @("raw/motion.raw.json", "cleaned/motion.cleaned.json", "manifest.json", "generation_checkpoint.json")) {
        $processingSourcePath = Join-Path $CandidateWorkspace $relativePath
        if (Test-Path -LiteralPath $processingSourcePath -PathType Leaf) {
            New-Item -ItemType Directory -Force -Path $processingEvidenceDirectory | Out-Null
            Copy-SelectedFile -SourcePath $processingSourcePath -DestinationDirectory $processingEvidenceDirectory -DestinationFileName (Split-Path -Leaf $relativePath) | Out-Null
        }
    }

    $sourceDirectory = Join-Path $CandidateWorkspace "segment_detection"
    $sourceValidationPath = Join-Path $sourceDirectory "exact_source_phase_validation.json"
    $sourceSelectionPath = Join-Path $sourceDirectory "segment_selection.json"
    $sourcePosePath = Join-Path $sourceDirectory "exact_source_pose_reference.json"
    $sourceSelection = $null
    if (Test-Path -LiteralPath $sourceSelectionPath -PathType Leaf) {
        try {
            $sourceSelection = Get-Content -LiteralPath $sourceSelectionPath -Raw | ConvertFrom-ReconstructionJson
        } catch {
            $sourceSelection = $null
        }
    }
    $embeddedValidation = Get-ObjectProperty -Object $sourceSelection -Name "exactSourcePhaseValidation"
    $sourcePosePathValue = [string](Get-ObjectProperty -Object $embeddedValidation -Name "sourcePoseReferencePath")
    if (-not (Test-Path -LiteralPath $sourcePosePath -PathType Leaf) -and
        -not [string]::IsNullOrWhiteSpace($sourcePosePathValue) -and
        (Test-Path -LiteralPath $sourcePosePathValue -PathType Leaf)) {
        $sourcePosePath = $sourcePosePathValue
    }
    $hasValidationFile = Test-Path -LiteralPath $sourceValidationPath -PathType Leaf
    if (-not $hasValidationFile -and $null -eq $embeddedValidation) {
        return $null
    }
    if (-not (Test-Path -LiteralPath $sourcePosePath -PathType Leaf)) {
        return $null
    }

    $destinationAuditDirectory = Join-Path $DestinationDirectory "segment_detection"
    New-Item -ItemType Directory -Force -Path $destinationAuditDirectory | Out-Null
    $destinationPosePath = Copy-SelectedFile `
        -SourcePath (Join-Path $sourceDirectory "exact_source_pose_reference.json") `
        -DestinationDirectory $destinationAuditDirectory `
        -DestinationFileName "exact_source_pose_reference.json"
    $destinationValidationPath = $null
    if ($hasValidationFile) {
        $destinationValidationPath = Copy-SelectedFile `
            -SourcePath $sourceValidationPath `
            -DestinationDirectory $destinationAuditDirectory `
            -DestinationFileName "exact_source_phase_validation.json"
    } else {
        $destinationValidationPath = Join-Path $destinationAuditDirectory "exact_source_phase_validation.json"
        $cacheKey = Get-ObjectProperty -Object $embeddedValidation -Name "cacheKey"
        $validationRecord = [ordered]@{
            cacheKey = $cacheKey
            metrics = $embeddedValidation
            retainedFromSegmentSelection = $true
        }
        Write-AtomicJsonDocument -Path $destinationValidationPath -InputObject $validationRecord -Depth 100
    }
    $destinationSelectionPath = $null
    if (Test-Path -LiteralPath $sourceSelectionPath -PathType Leaf) {
        $destinationSelectionPath = Copy-SelectedFile `
            -SourcePath $sourceSelectionPath `
            -DestinationDirectory $destinationAuditDirectory `
            -DestinationFileName "segment_selection.json"
    }

    if ($destinationPosePath -and $destinationValidationPath) {
        try {
            $validation = Get-Content -LiteralPath $destinationValidationPath -Raw | ConvertFrom-ReconstructionJson
            if ($validation.metrics) {
                $validation.metrics.sourcePoseReferencePath = [System.IO.Path]::GetFullPath($destinationPosePath)
                Write-AtomicJsonDocument -Path $destinationValidationPath -InputObject $validation -Depth 100
            }
            if ($destinationSelectionPath) {
                $selection = Get-Content -LiteralPath $destinationSelectionPath -Raw | ConvertFrom-ReconstructionJson
                if ($selection.exactSourcePhaseValidation -and $selection.exactSourcePhaseValidation.metrics) {
                    $selection.exactSourcePhaseValidation.metrics.sourcePoseReferencePath = [System.IO.Path]::GetFullPath($destinationPosePath)
                    Write-AtomicJsonDocument -Path $destinationSelectionPath -InputObject $selection -Depth 100
                } elseif ($selection.exactSourcePhaseValidation) {
                    $selection.exactSourcePhaseValidation.sourcePoseReferencePath = [System.IO.Path]::GetFullPath($destinationPosePath)
                    Write-AtomicJsonDocument -Path $destinationSelectionPath -InputObject $selection -Depth 100
                }
            }
        } catch {
            Write-Warning "Could not rewrite retained source-audit paths for '$CandidateWorkspace': $($_.Exception.Message)"
        }
    }
    return $destinationAuditDirectory
}

function Convert-SelectedSourceVideoToWebm {
    param(
        [string]$SourcePath,
        [string]$DestinationDirectory,
        [string]$DestinationFileName
    )
    if ([string]::IsNullOrWhiteSpace($SourcePath) -or -not (Test-Path -LiteralPath $SourcePath)) {
        return $null
    }
    New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    $destinationPath = Join-Path $DestinationDirectory $DestinationFileName
    $pythonArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "convert-video-webm",
        "--video-path", $SourcePath,
        "--out-video", $destinationPath
    )
    & $PythonCommand @pythonArgs *> $null
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $destinationPath)) {
        return $destinationPath
    }
    if (Test-Path -LiteralPath $destinationPath) {
        Remove-Item -LiteralPath $destinationPath -Force
    }
    return $null
}

function ConvertTo-HtmlAttribute {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    return [System.Net.WebUtility]::HtmlEncode($Value)
}

function ConvertTo-UrlComponent {
    param([string]$Value)
    if ($null -eq $Value) {
        return ""
    }
    return [System.Uri]::EscapeDataString($Value)
}

function ConvertTo-SelectedPreviewOptionsJson {
    param(
        [object]$Options,
        [string]$WearSkeletonPath
    )

    $previewOptions = [ordered]@{}
    if ($Options -is [System.Collections.IDictionary]) {
        foreach ($key in $Options.Keys) {
            $previewOptions[[string]$key] = $Options[$key]
        }
    } elseif ($null -ne $Options) {
        foreach ($property in @($Options.PSObject.Properties)) {
            if ($property.MemberType -in @("NoteProperty", "Property", "AliasProperty")) {
                $previewOptions[$property.Name] = $property.Value
            }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($WearSkeletonPath) -and (Test-Path -LiteralPath $WearSkeletonPath)) {
        try {
            $skeletonPayload = Get-Content -Raw -LiteralPath $WearSkeletonPath | ConvertFrom-ReconstructionJson
            $selectedPreviewSettings = Get-ObjectProperty -Object $skeletonPayload -Name "selectedPreviewSettings"
            $wearDisplay = Get-ObjectProperty -Object $skeletonPayload -Name "wearDisplay"
            $cameraYawDegrees = Get-OptionalDouble -Value (
                Get-ObjectProperty -Object $selectedPreviewSettings -Name "cameraYawDegrees"
            )
            if ($null -eq $cameraYawDegrees) {
                $cameraYawDegrees = Get-OptionalDouble -Value (
                    Get-ObjectProperty -Object $wearDisplay -Name "viewYawDegrees"
                )
            }
            $cameraPitchDegrees = Get-OptionalDouble -Value (
                Get-ObjectProperty -Object $selectedPreviewSettings -Name "cameraPitchDegrees"
            )
            if ($null -eq $cameraPitchDegrees) {
                $cameraPitchDegrees = Get-OptionalDouble -Value (
                    Get-ObjectProperty -Object $wearDisplay -Name "viewPitchDegrees"
                )
            }
            if ($null -ne $cameraYawDegrees) {
                $previewOptions["cameraYawDegrees"] = $cameraYawDegrees
            }
            if ($null -ne $cameraPitchDegrees) {
                $previewOptions["cameraPitchDegrees"] = $cameraPitchDegrees
            }
        } catch {
            Write-Warning "Could not read selected preview camera settings from $WearSkeletonPath; preserving the recorded option values."
        }
    }
    return ($previewOptions | ConvertTo-Json -Depth 32 -Compress)
}

function Write-SelectedPreviewHtml {
    param(
        [string]$DestinationPath,
        [string]$ExerciseName,
        [int]$OptionIndex,
        [string]$PreviewVideoPath,
        [string]$InputVideoPath,
        [string]$InputVideoWebmPath,
        [string]$WearSkeletonPath,
        [string]$InteractivePreviewPath,
        [double]$StartSeconds = 0.0,
        [double]$EndSeconds = 0.0,
        [string]$SettingsOptionsJson = "{}"
    )

    if ([string]::IsNullOrWhiteSpace($DestinationPath)) {
        return $null
    }

    $destinationDirectory = Split-Path -Parent $DestinationPath
    New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
    $titleText = if ($OptionIndex -gt 1) { "$ExerciseName - Option $OptionIndex" } else { $ExerciseName }
    $title = ConvertTo-HtmlAttribute $titleText
    $previewFile = if (-not [string]::IsNullOrWhiteSpace($PreviewVideoPath)) { ConvertTo-HtmlAttribute ([System.IO.Path]::GetFileName($PreviewVideoPath)) } else { "" }
    $inputFile = if (-not [string]::IsNullOrWhiteSpace($InputVideoPath)) { ConvertTo-HtmlAttribute ([System.IO.Path]::GetFileName($InputVideoPath)) } else { "" }
    $inputWebmFile = if (-not [string]::IsNullOrWhiteSpace($InputVideoWebmPath)) { ConvertTo-HtmlAttribute ([System.IO.Path]::GetFileName($InputVideoWebmPath)) } else { "" }
    $skeletonFile = if (-not [string]::IsNullOrWhiteSpace($WearSkeletonPath)) { ConvertTo-HtmlAttribute ([System.IO.Path]::GetFileName($WearSkeletonPath)) } else { "" }
    $interactiveFile = if (-not [string]::IsNullOrWhiteSpace($InteractivePreviewPath)) { [System.IO.Path]::GetFileName($InteractivePreviewPath) } else { "" }
    $culture = [System.Globalization.CultureInfo]::InvariantCulture
    $optionsJson = if (-not [string]::IsNullOrWhiteSpace($SettingsOptionsJson)) { $SettingsOptionsJson } else { "{}" }
    $interactiveHref = ""
    if (-not [string]::IsNullOrWhiteSpace($interactiveFile)) {
        $queryParts = @(
            "startSeconds=$([System.Uri]::EscapeDataString(([double]$StartSeconds).ToString("0.000000", $culture)))",
            "endSeconds=$([System.Uri]::EscapeDataString(([double]$EndSeconds).ToString("0.000000", $culture)))",
            "options=$(ConvertTo-UrlComponent $optionsJson)"
        )
        $interactiveHref = "{0}?{1}" -f (ConvertTo-HtmlAttribute $interactiveFile), ($queryParts -join "&amp;")
    }

    $interactiveSection = if ($interactiveHref) {
@"
        <section>
            <h2>Interactive selected preview</h2>
            <iframe src="$interactiveHref" title="$title"></iframe>
            <p><a href="$interactiveHref">Open interactive preview</a></p>
        </section>
"@
    } else {
@"
        <section>
            <h2>Interactive selected preview</h2>
            <p>No interactive selected preview was copied.</p>
        </section>
"@
    }

    $previewSection = if ($previewFile) {
@"
        <section>
            <h2>Selected preview</h2>
            <video controls preload="metadata" src="$previewFile"></video>
            <p><a href="$previewFile">Open preview video</a></p>
        </section>
"@
    } else {
@"
        <section>
            <h2>Selected preview</h2>
            <p>No selected preview video was copied.</p>
        </section>
"@
    }
    $inputVideoSources = ""
    if ($inputWebmFile) {
        $inputVideoSources += "                <source src=""$inputWebmFile"" type=""video/webm"">`n"
    }
    if ($inputFile) {
        $inputVideoSources += "                <source src=""$inputFile"" type=""video/mp4"">`n"
    }
    $inputLinkFile = if ($inputWebmFile) { $inputWebmFile } else { $inputFile }
    $inputFallbackLink = if ($inputWebmFile -and $inputFile) {
@"
            <p><a href="$inputFile">Open selected source mp4</a></p>
"@
    } else {
        ""
    }
    $inputSection = if ($inputVideoSources) {
@"
        <section>
            <h2>Selected source</h2>
            <video controls preload="metadata">
$inputVideoSources            </video>
            <p><a href="$inputLinkFile">Open selected source video</a></p>
$inputFallbackLink
        </section>
"@
    } else {
@"
        <section>
            <h2>Selected source</h2>
            <p>No selected source video was copied.</p>
        </section>
"@
    }
    $skeletonSection = if ($skeletonFile) {
@"
        <section>
            <h2>Wear skeleton</h2>
            <p><a href="$skeletonFile">Open Wear skeleton JSON</a></p>
        </section>
"@
    } else {
        ""
    }

    $html = @"
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>$title</title>
    <style>
        body { margin: 0; padding: 24px; font-family: system-ui, sans-serif; background: #f7f7f7; color: #161616; }
        main { max-width: 1100px; margin: 0 auto; display: grid; gap: 18px; }
        h1, h2 { margin: 0 0 10px; }
        h1 { font-size: 24px; }
        h2 { font-size: 16px; }
        section { background: #fff; border: 1px solid #d9d9d9; border-radius: 8px; padding: 16px; }
        video { width: 100%; max-height: 70vh; background: #000; display: block; }
        iframe { width: 100%; height: min(72vh, 760px); min-height: 520px; background: #000; border: 1px solid #d9d9d9; display: block; }
        a { color: #0a5bd3; }
    </style>
</head>
<body>
    <main>
        <h1>$title</h1>
$interactiveSection
$previewSection
$inputSection
$skeletonSection
    </main>
</body>
</html>
"@
    Set-Content -LiteralPath $DestinationPath -Value $html -Encoding UTF8
    return $DestinationPath
}

function Get-SharedLlamaSessionDir {
    # Mirrors the Python default (exercise_motion_pkg/shared_llama_server.py):
    # explicit -SharedLlamaServerSessionDir, then a temp dir keyed on the
    # base-url port, so the supervisor and every attached process agree.
    if (-not [string]::IsNullOrWhiteSpace($SharedLlamaServerSessionDir)) {
        return $SharedLlamaServerSessionDir
    }
    $port = "default"
    try {
        $parsed = [uri]$LlamaCppBaseUrl
        if ($parsed.Port -gt 0) { $port = [string]$parsed.Port }
    } catch {
    }
    return (Join-Path ([System.IO.Path]::GetTempPath()) "myworkoutassistant-shared-llama-$port")
}

function Get-MotionProcessIdentityState {
    param(
        [int]$ProcessId,
        [object]$ExpectedProcessIdentity
    )

    if ($ProcessId -le 0) {
        return "unknown"
    }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return "stopped"
    }
    try {
        $identity = [long]$process.StartTime.ToUniversalTime().ToFileTimeUtc()
        if ($null -ne $ExpectedProcessIdentity -and
            $identity -ne [long]$ExpectedProcessIdentity) {
            return "stopped"
        }
        if ($process.HasExited) {
            return "stopped"
        }
        return "running"
    } catch {
        return "unknown"
    }
}

function Get-SharedLlamaLiveInflightCounters {
    param([string]$SessionDir)

    $inflightDir = Join-Path $SessionDir "in-flight"
    if (-not (Test-Path -LiteralPath $inflightDir)) {
        return @()
    }
    $live = @()
    foreach ($counterFile in @(Get-ChildItem -LiteralPath $inflightDir -Filter "*.json" -File -ErrorAction SilentlyContinue)) {
        try {
            $payload = Get-Content -LiteralPath $counterFile.FullName -Raw | ConvertFrom-ReconstructionJson
        } catch {
            continue
        }
        $ownerPid = 0
        $active = 0
        try { $ownerPid = [int]$payload.pid } catch { continue }
        try { $active = [int]$payload.activeRequests } catch { continue }
        if ($ownerPid -le 0) { continue }
        $ownerIdentity = $payload.processIdentity
        $ownerState = Get-MotionProcessIdentityState `
            -ProcessId $ownerPid `
            -ExpectedProcessIdentity $ownerIdentity
        if ($ownerState -ne "stopped" -and $active -gt 0) {
            $live += [pscustomobject]@{
                pid = $ownerPid
                processIdentity = $ownerIdentity
                identityState = $ownerState
                activeRequests = $active
            }
        }
    }
    return $live
}

function Stop-MotionProcessWithIdentity {
    param(
        [int]$ProcessId,
        [object]$ExpectedProcessIdentity,
        [int]$WaitTimeoutSeconds = 10
    )

    if ($ProcessId -le 0 -or $null -eq $ExpectedProcessIdentity) {
        return "unknown"
    }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return "stopped"
    }
    try {
        # Reading StartTime opens this exact process handle. Kill through the
        # same Process object after verifying identity, never by PID alone.
        $identity = [long]$process.StartTime.ToUniversalTime().ToFileTimeUtc()
        if ($identity -ne [long]$ExpectedProcessIdentity) {
            return "stopped"
        }
        if ($process.HasExited) {
            return "stopped"
        }
        $process.Kill()
        $null = $process.WaitForExit([Math]::Max(0, $WaitTimeoutSeconds) * 1000)
        if ($process.HasExited) {
            return "stopped"
        }
        return "running"
    } catch {
        try {
            if ($process.HasExited) {
                return "stopped"
            }
        } catch {
        }
        return "unknown"
    }
}

function Get-MotionServiceRuntimeState {
    param([object]$RuntimeOwner)

    if ($null -eq $RuntimeOwner) {
        return "stopped"
    }
    switch ([string]$RuntimeOwner.kind) {
        "process" {
            $processId = 0
            try { $processId = [int]$RuntimeOwner.pid } catch { return "unknown" }
            return Get-MotionProcessIdentityState `
                -ProcessId $processId `
                -ExpectedProcessIdentity $RuntimeOwner.processIdentity
        }
        "docker" {
            $identifier = [string]$RuntimeOwner.containerId
            if ([string]::IsNullOrWhiteSpace($identifier)) {
                $identifier = [string]$RuntimeOwner.containerName
            }
            if ([string]::IsNullOrWhiteSpace($identifier)) { return "unknown" }
            $selector = if ($RuntimeOwner.containerId) {
                "id=$($RuntimeOwner.containerId)"
            } else {
                "name=$($RuntimeOwner.containerName)"
            }
            for ($attempt = 0; $attempt -lt 3; $attempt += 1) {
                $running = $null
                $inspectExitCode = -1
                try {
                    $running = (& docker inspect -f "{{.State.Running}}" $identifier 2>$null)
                    $inspectExitCode = $LASTEXITCODE
                } catch {
                    # Some hosts promote native nonzero exits to terminating
                    # errors. Preserve the inspect result and still run the
                    # independent list probe for auto-removed containers.
                    if ($null -ne $LASTEXITCODE) {
                        $inspectExitCode = [int]$LASTEXITCODE
                    }
                }
                if ($inspectExitCode -eq 0) {
                    $value = ([string]$running).Trim().ToLowerInvariant()
                    if ($value -eq "true") { return "running" }
                    if ($value -eq "false") { return "stopped" }
                }

                $listed = $null
                $listExitCode = -1
                try {
                    $listed = (& docker ps --all --filter $selector --format "{{.ID}}" 2>$null)
                    $listExitCode = $LASTEXITCODE
                } catch {
                    if ($null -ne $LASTEXITCODE) {
                        $listExitCode = [int]$LASTEXITCODE
                    }
                }
                # RECONSTRUCTION containers use --rm. During removal, inspect and list
                # can briefly disagree; retry that transient state before
                # retaining a stale owner record as unconfirmed.
                if ($listExitCode -eq 0 -and
                    [string]::IsNullOrWhiteSpace([string]$listed)) {
                    return "stopped"
                }
                if ($attempt -lt 2) {
                    Start-Sleep -Milliseconds 150
                }
            }
            return "unknown"
        }
        default {
            return "unknown"
        }
    }
}

function Write-MotionWorkspaceLeaseOwner {
    param(
        [object]$Lease,
        [object]$RuntimeOwner,
        [string]$ServiceState,
        [switch]$ClearRuntimeOwner
    )

    if ($null -eq $Lease -or [string]::IsNullOrWhiteSpace($Lease.ownerPath)) {
        return
    }
    $owner = Get-Content -LiteralPath $Lease.ownerPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    if ([string]$owner.ownerToken -ne [string]$Lease.ownerToken) {
        throw "Motion workspace lease ownership changed before its runtime state could be updated: $($Lease.ownerPath)"
    }
    if ($ClearRuntimeOwner) {
        $owner.PSObject.Properties.Remove("runtimeOwner")
        $owner.PSObject.Properties.Remove("serviceState")
    } else {
        $owner | Add-Member -NotePropertyName "runtimeOwner" -NotePropertyValue $RuntimeOwner -Force
        $owner | Add-Member -NotePropertyName "serviceState" -NotePropertyValue $ServiceState -Force
    }
    $temporaryPath = "$($Lease.ownerPath).$($Lease.ownerToken).tmp"
    try {
        $owner | ConvertTo-Json -Depth 12 -Compress |
            Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        Move-Item -LiteralPath $temporaryPath -Destination $Lease.ownerPath -Force | Out-Null
    } finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function Set-MotionServiceSessionRuntimeOwner {
    param(
        [string]$SessionDirectory,
        [object]$RuntimeOwner,
        [string]$ServiceState
    )

    $lease = $null
    if ([string]::IsNullOrWhiteSpace($SessionDirectory)) {
        $lease = $script:MotionWorkspaceLease
    } elseif ($script:MotionServiceSessionLeases.ContainsKey($SessionDirectory)) {
        $lease = $script:MotionServiceSessionLeases[$SessionDirectory]
    }
    if ($null -eq $lease) {
        return
    }
    $lease | Add-Member -NotePropertyName "runtimeOwner" -NotePropertyValue $RuntimeOwner -Force
    Write-MotionWorkspaceLeaseOwner `
        -Lease $lease `
        -RuntimeOwner $RuntimeOwner `
        -ServiceState $ServiceState
}

function Set-MotionServiceSessionState {
    param(
        [string]$SessionDirectory,
        [object]$RuntimeOwner,
        [string]$ServiceState
    )

    Set-MotionServiceSessionRuntimeOwner `
        -SessionDirectory $SessionDirectory `
        -RuntimeOwner $RuntimeOwner `
        -ServiceState $ServiceState
}

function Enter-SharedLlamaTransitionLock {
    param(
        [string]$SessionDir,
        [double]$TimeoutSeconds = 240.0
    )

    $lockPath = Join-Path $SessionDir "shared-llama-transition.lock"
    New-Item -ItemType Directory -Force -Path $SessionDir | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max(0.1, $TimeoutSeconds))
    while ($true) {
        try {
            # Python's InterProcessFileLock opens this same persistent file
            # with no sharing on Windows, so both runtimes hold one OS lease.
            return [System.IO.File]::Open(
                $lockPath,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
        } catch [System.IO.IOException] {
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "Timed out waiting for shared llama transition lock: $lockPath"
            }
            Start-Sleep -Milliseconds 50
        }
    }
}

function Remove-StaleSharedLlamaInflightCounters {
    param([string]$SessionDir)

    $inflightDir = Join-Path $SessionDir "in-flight"
    Get-ChildItem -LiteralPath $inflightDir -Filter "*.json" -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            try {
                $counter = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
                $counterPid = [int]$counter.pid
                $counterIdentity = [long]$counter.processIdentity
                if ($counterPid -gt 0 -and
                    (Get-MotionProcessIdentityState -ProcessId $counterPid -ExpectedProcessIdentity $counterIdentity) -eq "stopped") {
                    Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
                }
            } catch {
                # Malformed or unverifiable counters are retained. Startup
                # cannot prove that their owners have released the GPU.
            }
        }
}

function Start-SharedLlamaServer {
    param([string]$SessionDir, [int]$StartupAttempt = 1)

    $sessionLeaseKey = Acquire-MotionServiceSessionLease `
        -SessionDirectory $SessionDir `
        -Stage "shared_llama_server"
    $transitionLock = $null
    try {
        $transitionLock = Enter-SharedLlamaTransitionLock -SessionDir $SessionDir
        if (Test-SharedLlamaExclusiveHandoffActive -SessionDir $SessionDir) {
            $null = Release-MotionServiceSessionLease -SessionDirectory $sessionLeaseKey
            Write-Host "Shared llama.cpp restart deferred for an active exclusive GPU handoff."
            return $null
        }
    New-Item -ItemType Directory -Force -Path (Join-Path $SessionDir "in-flight") | Out-Null
    # Stale markers from a previous supervisor instance must not satisfy or
    # confuse a fresh start; crashed clients leave their counters behind.
    foreach ($staleFile in @("ready.json", "heartbeat.json", "startup_error.json", "start_requested.json", "stopped.json")) {
        $path = Join-Path $SessionDir $staleFile
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
    Remove-StaleSharedLlamaInflightCounters -SessionDir $SessionDir

    $host_ = "127.0.0.1"
    $port = 8090
    try {
        $parsed = [uri]$LlamaCppBaseUrl
        if ($parsed.Host) { $host_ = $parsed.Host }
        if ($parsed.Port -gt 0) { $port = $parsed.Port }
    } catch {
    }
    # Production flag set measured for the RTX 4070 SUPER (see
    # exercise_motion_pkg/SHARED_LLAMA_SERVER.md). Slot count, context
    # geometry, and reasoning mode come from the same params that feed the
    # bake/discovery requests so the clients' attach-time runtime validation
    # (parallel slots, reasoning flags, budget) always matches the supervisor.
    $parallel = if ($null -ne $LlamaCppParallel) { [int]$LlamaCppParallel } else { 8 }
    $ctxSize = if ($null -ne $LlamaCppCtxSize) { [int]$LlamaCppCtxSize } else { 49152 }
    $batchSize = if ($null -ne $LlamaCppBatchSize) { [int]$LlamaCppBatchSize } else { 1024 }
    $ubatchSize = if ($null -ne $LlamaCppUBatchSize) { [int]$LlamaCppUBatchSize } else { 512 }
    $threadsHttp = if ($null -ne $LlamaCppThreadsHttp) { [int]$LlamaCppThreadsHttp } else { 8 }
    $reasoningBudget = if ($null -ne $LlamaCppReasoningBudget) { [int]$LlamaCppReasoningBudget } else { 64 }
    $gpuLayers = if ($LlamaCppFit -eq "off") { "all" } else { "auto" }
    $fitCtx = if ($null -ne $LlamaCppFitCtx) { [int]$LlamaCppFitCtx } else { $ctxSize }
    $fitTarget = if ($null -ne $LlamaCppFitTarget) { [int]$LlamaCppFitTarget } else { 2048 }
    $serverArgs = @(
        "-m", $LlamaCppModel,
        "--host", $host_, "--port", "$port",
        "--mmproj", $LlamaCppMmproj, "--mmproj-offload",
        "--parallel", "$parallel",
        "--ctx-size", "$ctxSize",
        "--batch-size", "$batchSize",
        "--ubatch-size", "$ubatchSize",
        "--flash-attn", $LlamaCppFlashAttn,
        "--cache-type-k", $LlamaCppCacheTypeK,
        "--cache-type-v", $LlamaCppCacheTypeV,
        "--fit", $LlamaCppFit, "--fit-ctx", "$fitCtx", "--fit-target", "$fitTarget",
        "--threads-http", "$threadsHttp",
        "--reasoning", "on", "--reasoning-format", "deepseek", "--reasoning-budget", "$reasoningBudget",
        "--cont-batching",
        "--gpu-layers", $gpuLayers,
        "--split-mode", "layer"
    )
    $launchId = "$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')-$([guid]::NewGuid().ToString('N'))"
    $logPath = Join-Path $SessionDir "server-$launchId.log"
    $errorLogPath = Join-Path $SessionDir "server-$launchId.err.log"
    $baseUrl = "http://${host_}:${port}"
    $serverEnvironment = @{}
    $exclusiveGpuDevice = "$env:EXERCISE_MOTION_EXCLUSIVE_GPU_DEVICE".Trim()
    if ($exclusiveGpuDevice -match '^[1-9]\d*$') {
        $gpuRows = @(& nvidia-smi --query-gpu=index,uuid --format=csv,noheader,nounits 2>$null)
        $gpuUuids = @{}
        foreach ($gpuRow in $gpuRows) {
            $parts = $gpuRow.Split(',', 2)
            if ($parts.Count -eq 2) { $gpuUuids[$parts[0].Trim()] = $parts[1].Trim() }
        }
        if ($LASTEXITCODE -ne 0 -or -not $gpuUuids.ContainsKey('0') -or -not $gpuUuids.ContainsKey($exclusiveGpuDevice)) {
            throw "Cannot pin the shared llama.cpp server away from exclusive GPU ${exclusiveGpuDevice}: nvidia-smi did not confirm both physical GPU UUIDs."
        }
        $serverEnvironment['CUDA_VISIBLE_DEVICES'] = $gpuUuids['0']
    }
    # Persist an unknown process owner before spawn. If the wrapper is
    # interrupted between process creation and PID recording, a later run must
    # retain this session instead of assuming it is safe to start another one.
    $runtimeOwner = [ordered]@{
        kind = "process"
        service = "llama-server"
        pid = 0
        processIdentity = $null
        baseUrl = $baseUrl
    }
    Set-MotionServiceSessionRuntimeOwner `
        -SessionDirectory $sessionLeaseKey `
        -RuntimeOwner $runtimeOwner `
        -ServiceState "starting"
    Write-Host "Starting shared llama.cpp server ($($serverArgs -join ' '))..."
    $launchAttemptStartedAt = [DateTime]::UtcNow
    try {
        $process = Start-Process `
            -FilePath $LlamaCppServerCommand `
            -ArgumentList (@($serverArgs | ForEach-Object { if ($_ -match '\s') { '"{0}"' -f $_ } else { $_ } })) `
            -RedirectStandardOutput $logPath `
            -RedirectStandardError $errorLogPath `
            -Environment $serverEnvironment `
            -WindowStyle Hidden `
            -PassThru
    } catch {
        $launchError = $_
        $possibleServerProcess = $false
        $serverProcessName = [System.IO.Path]::GetFileNameWithoutExtension($LlamaCppServerCommand)
        for ($probeAttempt = 0; $probeAttempt -lt 4 -and -not $possibleServerProcess; $probeAttempt++) {
            try {
                $possibleServerProcess = @(
                    Get-Process -Name $serverProcessName -ErrorAction SilentlyContinue |
                        Where-Object { $_.StartTime.ToUniversalTime() -ge $launchAttemptStartedAt.AddSeconds(-1) }
                ).Count -gt 0
            } catch {
                # Inability to inspect a possible child is not proof that it
                # failed to start; keep the durable unknown owner in that case.
                $possibleServerProcess = $true
            }
            if (-not $possibleServerProcess -and $probeAttempt -lt 3) {
                Start-Sleep -Milliseconds 250
            }
        }
        $endpointResponding = $false
        try {
            $null = Invoke-RestMethod -Uri "$baseUrl/v1/models" -TimeoutSec 2
            $endpointResponding = $true
        } catch {
        }
        if (-not $possibleServerProcess -and -not $endpointResponding) {
            # Start-Process threw, no matching child appeared during the
            # observation window, and the configured endpoint is not serving.
            # This is the one case where the PID-zero owner is known to be a
            # failed launch rather than an interrupted post-spawn handoff.
            Set-MotionServiceSessionRuntimeOwner `
                -SessionDirectory $sessionLeaseKey `
                -RuntimeOwner $null `
                -ServiceState "stopped"
            $null = Release-MotionServiceSessionLease -SessionDirectory $sessionLeaseKey
            throw "Shared llama.cpp process launch failed before a child was created: $($launchError.Exception.Message)"
        }
        Write-Warning "Shared llama.cpp launch failed but a child process or responding endpoint may exist; retaining the unknown runtime owner."
        throw $launchError
    }
    $runtimeOwner.pid = $process.Id
    $runtimeOwner.processIdentity = [long]$process.StartTime.ToUniversalTime().ToFileTimeUtc()
    Set-MotionServiceSessionRuntimeOwner `
        -SessionDirectory $sessionLeaseKey `
        -RuntimeOwner $runtimeOwner `
        -ServiceState "running"
    $deadline = (Get-Date).AddSeconds($LlamaCppServerStartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-MotionRunCancelRequested) {
            Stop-SharedLlamaServer -Server ([pscustomobject]@{
                processId = $process.Id
                sessionDir = $SessionDir
                sessionLeaseKey = $sessionLeaseKey
                runtimeOwner = $runtimeOwner
            })
            Exit-IfMotionRunInterrupted
        }
        if ($process.HasExited) {
            if (Test-SharedLlamaServerStoppedByLiveExclusiveHandoff -SessionDir $SessionDir) {
                Write-Host "Shared llama.cpp startup was quiesced by a live exclusive GPU handoff; restart remains pending."
                $null = Release-MotionServiceSessionLease -SessionDirectory $sessionLeaseKey
                return $null
            }
            $stdoutTail = (Get-Content -LiteralPath $logPath -Tail 12 -ErrorAction SilentlyContinue) -join " | "
            $stderrTail = (Get-Content -LiteralPath $errorLogPath -Tail 12 -ErrorAction SilentlyContinue) -join " | "
            $startupFailure = "Shared llama.cpp server exited during startup (code $($process.ExitCode)). Logs: $logPath, $errorLogPath. stdout: $stdoutTail stderr: $stderrTail"
            $null = Release-MotionServiceSessionLease -SessionDirectory $sessionLeaseKey
            if ($StartupAttempt -lt 3) {
                Write-Warning "$startupFailure Retrying server startup ($($StartupAttempt + 1)/3) without restarting the movement pass."
                $transitionLock.Dispose()
                $transitionLock = $null
                Start-Sleep -Seconds 2
                Exit-IfMotionRunInterrupted
                return Start-SharedLlamaServer -SessionDir $SessionDir -StartupAttempt ($StartupAttempt + 1)
            }
            throw $startupFailure
        }
        # Queued holders need our transition lock to quiesce this server; finish startup before releasing it.
        try {
            $null = Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 5
            $ready = [ordered]@{
                pid = $process.Id
                baseUrl = $baseUrl
                model = $LlamaCppModel
                parallel = $parallel
                startedAtUnixSeconds = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            }
            $ready | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $SessionDir "ready.json") -Encoding UTF8
            Update-SharedLlamaServerHeartbeat -SessionDir $SessionDir
            Write-Host ("Shared llama.cpp server ready (pid {0}) at {1}." -f $process.Id, $baseUrl)
            return [pscustomobject]@{
                processId = $process.Id
                sessionDir = $SessionDir
                baseUrl = $baseUrl
                logPath = $logPath
                sessionLeaseKey = $sessionLeaseKey
                runtimeOwner = $runtimeOwner
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    $startupCleanupState = Stop-MotionProcessWithIdentity `
        -ProcessId $process.Id `
        -ExpectedProcessIdentity $runtimeOwner.processIdentity `
        -WaitTimeoutSeconds 10
    if ($startupCleanupState -ne "stopped") {
        Write-Warning "Shared llama.cpp startup timed out and process cleanup could not be confirmed (pid $($process.Id), state $startupCleanupState)."
    }
    @{ error = "Timed out waiting for shared llama.cpp server startup after $LlamaCppServerStartupTimeoutSeconds seconds." } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $SessionDir "startup_error.json") -Encoding UTF8
    throw "Timed out waiting for shared llama.cpp server startup after $LlamaCppServerStartupTimeoutSeconds seconds. Logs: $logPath"
    } finally {
        if ($null -ne $transitionLock) {
            $transitionLock.Dispose()
        }
    }
}

function Update-SharedLlamaServerHeartbeat {
    param([string]$SessionDir)

    @{ updatedAtUnixSeconds = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $SessionDir "heartbeat.json") -Encoding UTF8
}

function Test-SharedLlamaServerRestartAdmission {
    param(
        [bool]$RestartRequired,
        [bool]$StartRequested,
        [bool]$ReadyMarkerExists,
        [bool]$LiveExclusiveHandoffActive = $false,
        [int]$SafeBakeRunningJobCount,
        [int]$UnsafeBakeRunningJobCount,
        [int]$PrefetchRunningJobCount,
        [int]$PendingPrefetchCount,
        [int]$DiscoveryRunningJobCount,
        [int]$PendingDiscoveryCount,
        [int]$PendingLegacyBakeCount
    )

    if ($LiveExclusiveHandoffActive) {
        return $false
    }

    $hasWork = (
        $SafeBakeRunningJobCount -gt 0 -or
        $PrefetchRunningJobCount -gt 0 -or
        $PendingPrefetchCount -gt 0 -or
        $DiscoveryRunningJobCount -gt 0 -or
        $PendingDiscoveryCount -gt 0 -or
        $PendingLegacyBakeCount -gt 0
    )
    $hasRestartSignal = $RestartRequired -or $StartRequested -or -not $ReadyMarkerExists
    return [bool]($UnsafeBakeRunningJobCount -eq 0 -and $hasWork -and $hasRestartSignal)
}

function Test-SharedLlamaExclusiveHandoffActive {
    param([string]$SessionDir)

    # An idle extractor still occupies VRAM between GPU operations. Its owner
    # clears this marker after releasing the worker for the next VLM request.
    $holdersPath = Join-Path $SessionDir "generation-holders"
    if (Test-Path -LiteralPath $holdersPath -PathType Container) {
        foreach ($holderPath in @(Get-ChildItem -LiteralPath $holdersPath -Filter '*.json' -File)) {
            try {
                $holder = Get-Content -LiteralPath $holderPath.FullName -Raw | ConvertFrom-Json
                $holderState = Get-MotionProcessIdentityState -ProcessId ([int]$holder.pid) -ExpectedProcessIdentity ([long]$holder.processIdentity)
                if ($holderState -ne "stopped") { return $true }
            } catch { return $true }
        }
    }
    $stopIntentPath = Join-Path $SessionDir "stop_intent.json"
    if (-not (Test-Path -LiteralPath $stopIntentPath -PathType Leaf)) {
        return $false
    }
    try {
        $intent = Get-Content -LiteralPath $stopIntentPath -Raw | ConvertFrom-Json
        $ownerPid = [int]$intent.pid
        $ownerIdentity = [long]$intent.processIdentity
        if ($ownerPid -le 0 -or
            (Get-MotionProcessIdentityState -ProcessId $ownerPid -ExpectedProcessIdentity $ownerIdentity) -ne "running") {
            return $false
        }
        $counterPath = Join-Path (Join-Path $SessionDir "in-flight") ("{0}.json" -f $ownerPid)
        if (-not (Test-Path -LiteralPath $counterPath -PathType Leaf)) {
            return $false
        }
        $counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
        return [bool]([int]$counter.pid -eq $ownerPid -and
            [long]$counter.processIdentity -eq $ownerIdentity)
    } catch {
        return $false
    }
}

function Test-SharedLlamaServerStoppedByLiveExclusiveHandoff {
    param([string]$SessionDir)

    if (-not (Test-SharedLlamaExclusiveHandoffActive -SessionDir $SessionDir)) {
        return $false
    }
    try {
        $intent = Get-Content -LiteralPath (Join-Path $SessionDir "stop_intent.json") -Raw | ConvertFrom-Json
        $stopped = Get-Content -LiteralPath (Join-Path $SessionDir "stopped.json") -Raw | ConvertFrom-Json
        return [bool]([int]$stopped.stoppedByPid -eq [int]$intent.pid)
    } catch {
        return $false
    }
}

function Get-SharedLlamaBakeRestartCounts {
    param([object[]]$RunningJobs)

    # A staged wave owns the exclusive GPU only during RECONSTRUCTION generation. Its
    # source and final validation phases need the shared vision server, so a
    # blanket "any bake job" gate can strand those phases after a model
    # handoff. Treat unknown/missing checkpoints conservatively.
    $safeStages = @("source_validation", "reconstruction_released", "cpu_preparation", "final_validation", "generation_and_validation")
    $safeCount = 0
    $unsafeCount = 0
    foreach ($job in @($RunningJobs)) {
        if (-not ($job.PSObject.Properties.Name -contains "IsStagedWave") -or
            -not $job.IsStagedWave -or
            -not ($job.PSObject.Properties.Name -contains "WaveWorkspace") -or
            [string]::IsNullOrWhiteSpace([string]$job.WaveWorkspace)) {
            # Shared clients publish exclusive GPU ownership through the handoff protocol.
            if ($job.PSObject.Properties.Name -contains "WorkItem" -and
                $null -ne $job.WorkItem -and
                $job.WorkItem.PSObject.Properties.Name -contains "bakeArgs" -and
                '--shared-llama-server' -in @($job.WorkItem.bakeArgs)) {
                $safeCount++
            } else {
                $unsafeCount++
            }
            continue
        }
        $checkpointPath = Join-Path $job.WaveWorkspace "staged_wave_checkpoint.json"
        if (-not (Test-Path -LiteralPath $checkpointPath)) {
            # A request still in the service queue has not acquired the GPU.
            if ($job.PSObject.Properties.Name -contains "RequestId" -and
                -not [string]::IsNullOrWhiteSpace([string]$script:StagedWaveServiceQueueRoot) -and
                (Test-Path -LiteralPath (Join-Path (Join-Path $script:StagedWaveServiceQueueRoot "requests") "$($job.RequestId).json"))) {
                $safeCount++
                continue
            }
            $unsafeCount++
            continue
        }
        try {
            $checkpoint = Get-Content -LiteralPath $checkpointPath -Raw | ConvertFrom-ReconstructionJson
            if ([string]$checkpoint.stage -in $safeStages) {
                $safeCount++
            } else {
                $unsafeCount++
            }
        } catch {
            $unsafeCount++
        }
    }
    return [pscustomobject]@{
        safeBakeRunningJobCount = $safeCount
        unsafeBakeRunningJobCount = $unsafeCount
    }
}

function Stop-SharedLlamaServer {
    param([object]$Server)

    if ($null -eq $Server) {
        return
    }
    $sessionDir = $Server.sessionDir
    Set-MotionServiceSessionState `
        -SessionDirectory $Server.sessionLeaseKey `
        -RuntimeOwner $Server.runtimeOwner `
        -ServiceState "stopping"
    try {
        # Close attached clients' admission gates before draining, mirroring the
        # Python quiesce protocol's stop-intent ordering.
        $supervisorProcess = Get-Process -Id $PID -ErrorAction SilentlyContinue
        $supervisorIdentity = $null
        if ($null -ne $supervisorProcess) {
            try { $supervisorIdentity = [long]$supervisorProcess.StartTime.ToUniversalTime().ToFileTimeUtc() } catch {}
        }
        @{ pid = $PID; processIdentity = $supervisorIdentity; requestedAtUnixSeconds = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() } |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $sessionDir "stop_intent.json") -Encoding UTF8
    } catch {
    }
    $deadline = (Get-Date).AddSeconds($SharedLlamaServerStopDrainTimeoutSeconds)
    $drainCompleted = $false
    while ((Get-Date) -lt $deadline) {
        $live = @(Get-SharedLlamaLiveInflightCounters -SessionDir $sessionDir)
        if ($live.Count -eq 0) {
            $drainCompleted = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    $remainingRequests = @(Get-SharedLlamaLiveInflightCounters -SessionDir $sessionDir)
    if (-not $drainCompleted -and $remainingRequests.Count -gt 0) {
        Remove-Item -LiteralPath (Join-Path $sessionDir "stop_intent.json") -Force -ErrorAction SilentlyContinue
        Write-Warning "Shared llama.cpp server drain timed out with $($remainingRequests.Count) live client counter(s); leaving the server running."
        $null = Release-MotionServiceSessionLease -SessionDirectory $Server.sessionLeaseKey
        return
    }

    $stopState = Stop-MotionProcessWithIdentity `
        -ProcessId ([int]$Server.processId) `
        -ExpectedProcessIdentity $Server.runtimeOwner.processIdentity `
        -WaitTimeoutSeconds 10
    if ($stopState -ne "stopped") {
        Write-Warning "Shared llama.cpp server shutdown could not be confirmed (pid $($Server.processId), state $stopState)."
    }
    $runtimeState = Release-MotionServiceSessionLease -SessionDirectory $Server.sessionLeaseKey
    if ($runtimeState -eq "stopped") {
        foreach ($marker in @("stop_intent.json", "ready.json", "heartbeat.json")) {
            $path = Join-Path $sessionDir $marker
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            }
        }
        @{ stoppedByPid = $PID; stoppedAtUnixSeconds = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() } |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $sessionDir "stopped.json") -Encoding UTF8
    } else {
        Write-Warning "Shared llama.cpp server shutdown could not be confirmed; preserving its session markers and owner evidence."
    }
}

function Start-GvhmrWarmWorker {
    param(
        [string]$SessionDir,
        [string]$MountRoot,
        [string]$WorkerScriptPath
    )

    $sessionLeaseKey = Acquire-MotionServiceSessionLease `
        -SessionDirectory $SessionDir `
        -Stage "GVHMR warm-worker service"
    New-Item -ItemType Directory -Force -Path $SessionDir | Out-Null
    $workerQueueDirectories = @("jobs", "running", "results", "job_logs", "ambiguous")
    foreach ($child in $workerQueueDirectories) {
        New-Item -ItemType Directory -Force -Path (Join-Path $SessionDir $child) | Out-Null
    }
    # Preserve unclaimed jobs; the worker classifies claimed jobs before model loading.
    foreach ($staleFile in @("ready.json", "heartbeat.json", "startup_error.json", "stop", "stopped.json")) {
        $path = Join-Path $SessionDir $staleFile
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }

    $containerName = "mwa-gvhmr-worker-$([guid]::NewGuid().ToString('N'))"
    $runtimeOwner = [ordered]@{
        kind = "docker"
        service = "gvhmr-warm-worker"
        containerName = $containerName
        containerId = $null
    }
    Set-MotionServiceSessionRuntimeOwner `
        -SessionDirectory $sessionLeaseKey `
        -RuntimeOwner $runtimeOwner `
        -ServiceState "starting"
    $dockerArgs = @("run", "-d", "--rm", "--name", $containerName)
    if (-not [string]::IsNullOrWhiteSpace($ReconstructionDockerGpus)) {
        $dockerArgs += @("--gpus", $ReconstructionDockerGpus)
    }
    $warmWorkerRetentionPath = Join-Path (Split-Path -Parent $WorkerScriptPath) "warm_worker_retention.py"
        $dockerArgs += @("--shm-size", "8g")
        $dockerArgs += @(
            "-v", "$((Join-Path (Split-Path -Parent $WorkerScriptPath) 'gvhmr_inference.py')):/worker/gvhmr_inference.py:ro",
            "-v", "$((Join-Path (Split-Path -Parent $WorkerScriptPath) 'gvhmr_pkl_export.py')):/worker/gvhmr_pkl_export.py:ro",
            "-v", "$($MountRoot):/workspace",
            "-v", "$($SessionDir):/worker_state",
            "-v", "$($WorkerScriptPath):/worker/gvhmr_warm_worker.py:ro",
            "-v", "$($warmWorkerRetentionPath):/worker/warm_worker_retention.py:ro",
            "-w", "/opt/gvhmr",
            $ReconstructionDockerImage,
            "python", "-u", "/worker/gvhmr_warm_worker.py",
            "--state-dir", "/worker_state"
        )

    if ($script:GvhmrWorkerStartedOnce) {
        Write-Host "Restarting motion extractor..."
    } else {
        Write-Host "Starting motion extractor..."
        $script:GvhmrWorkerStartedOnce = $true
    }
    $containerId = (& docker @dockerArgs 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start warm GVHMR worker container: $containerId"
    }
    $containerId = ([string]$containerId).Trim()
    $runtimeOwner.containerId = $containerId
    Set-MotionServiceSessionRuntimeOwner `
        -SessionDirectory $sessionLeaseKey `
        -RuntimeOwner $runtimeOwner `
        -ServiceState "running"
    $readyPath = Join-Path $SessionDir "ready.json"
    $startupErrorPath = Join-Path $SessionDir "startup_error.json"
    $deadline = (Get-Date).AddSeconds($GvhmrWorkerStartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-MotionRunCancelRequested) {
            # The caller has no worker handle until startup returns.
            Stop-GvhmrWarmWorker -Worker ([pscustomobject]@{
                containerName = $containerName
                containerId = $containerId
                sessionDir = $SessionDir
                sessionLeaseKey = $sessionLeaseKey
                runtimeOwner = $runtimeOwner
            })
            Exit-IfMotionRunInterrupted
        }
        if (Test-Path -LiteralPath $readyPath) {
            $ready = Get-Content -LiteralPath $readyPath -Raw | ConvertFrom-Json
            Write-Host ("Motion extractor ready in {0}s ({1})." -f $ready.loadSeconds, $ready.gpuName)
            return [pscustomobject]@{
                containerName = $containerName
                containerId = $containerId
                sessionDir = $SessionDir
                mountRoot = $MountRoot
                readyPath = $readyPath
                sessionLeaseKey = $sessionLeaseKey
                runtimeOwner = $runtimeOwner
            }
        }
        if (Test-Path -LiteralPath $startupErrorPath) {
            $errorPayload = Get-Content -LiteralPath $startupErrorPath -Raw
            try {
                & docker logs $containerName 2>&1 | Add-Content -LiteralPath (Join-Path $SessionDir "container.log") -Encoding UTF8
            } catch {
            }
            try {
                & docker stop $containerName | Out-Null
            } catch {
            }
            throw "Warm GVHMR worker failed during startup: $errorPayload"
        }
        $running = (& docker inspect -f "{{.State.Running}}" $containerName 2>$null)
        if ($LASTEXITCODE -ne 0 -or "$running".Trim().ToLowerInvariant() -ne "true") {
            $logs = (& docker logs $containerName 2>&1)
            throw "Warm GVHMR worker container exited before ready. Logs: $logs"
        }
        Start-Sleep -Seconds 2
    }
    try {
        & docker logs $containerName 2>&1 | Add-Content -LiteralPath (Join-Path $SessionDir "container.log") -Encoding UTF8
    } catch {
    }
    try {
        & docker stop $containerName | Out-Null
    } catch {
    }
    throw "Timed out waiting for warm GVHMR worker startup after $GvhmrWorkerStartupTimeoutSeconds seconds."
}

function Stop-GvhmrWarmWorker {
    param([object]$Worker)
    if ($null -eq $Worker) {
        return
    }
    Set-MotionServiceSessionState `
        -SessionDirectory $Worker.sessionLeaseKey `
        -RuntimeOwner $Worker.runtimeOwner `
        -ServiceState "stopping"
    try {
        "stop" | Set-Content -LiteralPath (Join-Path $Worker.sessionDir "stop") -Encoding UTF8
    } catch {
    }
    try {
        & docker stop --time 10 $Worker.containerName | Out-Null
    } catch {
        Write-Warning "Failed to stop warm RECONSTRUCTION worker container '$($Worker.containerName)': $($_.Exception.Message)"
    }
    $runtimeState = Release-MotionServiceSessionLease -SessionDirectory $Worker.sessionLeaseKey
    if ($runtimeState -eq "stopped") {
        # Docker termination may bypass the worker's Python finally block.
        foreach ($marker in @("ready.json", "heartbeat.json")) {
            Remove-Item -LiteralPath (Join-Path $Worker.sessionDir $marker) -Force -ErrorAction SilentlyContinue
        }
        @{ status = "stopped"; stoppedByPid = $PID } | ConvertTo-Json |
            Set-Content -LiteralPath (Join-Path $Worker.sessionDir "stopped.json") -Encoding UTF8
    } else {
        Write-Warning "Warm $($Worker.runtimeOwner.service) shutdown could not be confirmed; preserving its session owner evidence."
    }
}

function Remove-IntermediateArtifactFile {
    param([string]$Path)

    $retryDelaysMilliseconds = @(100, 250, 500)
    for ($attempt = 0; $attempt -le $retryDelaysMilliseconds.Count; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
            return
        } catch {
            $exception = $_.Exception
            $sharingViolation = $false
            while ($null -ne $exception) {
                if (($exception.HResult -band 0xFFFF) -in @(32, 33)) {
                    $sharingViolation = $true
                    break
                }
                $exception = $exception.InnerException
            }
            if (-not $sharingViolation) {
                throw
            }
            if ($attempt -lt $retryDelaysMilliseconds.Count) {
                Start-Sleep -Milliseconds $retryDelaysMilliseconds[$attempt]
                continue
            }
            Write-Warning "Retaining locked intermediate artifact after bounded cleanup retries: $Path"
            return
        }
    }
}

function Remove-ExerciseIntermediateArtifacts {
    param([object]$WorkItem)

    if ($ArtifactRetention -eq "full") {
        return
    }

    foreach ($path in @($WorkItem.bakeWorkspace)) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
            $bakeRoot = [IO.Path]::GetFullPath($path).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
            $bakePrefix = $bakeRoot + [IO.Path]::DirectorySeparatorChar
            $preservedFiles = @{}
            $selectionPath = Join-Path $bakeRoot "selection_manifest.json"
            if (Test-Path -LiteralPath $selectionPath -PathType Leaf) {
                try {
                    $bakeSelection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-ReconstructionJson
                    $selected = $bakeSelection.selected
                    $clearance = if ($selected) { $selected.sourceSelectionClearance } else { $null }
                    if ($clearance -and $clearance.status -in @("cleared", "not_required")) {
                        $proofPaths = @($clearance.sourceManifestPath, $clearance.selectedSegmentPath)
                        if ($clearance.status -eq "cleared") {
                            $proofPaths += @($clearance.sourceCutReviewVideoPath, $clearance.sourceCutOriginalVideoPath)
                            foreach ($image in @($clearance.sourceCutReviewFrameEvidence.images)) {
                                $proofPaths += [string]$image.path
                            }
                            try {
                                $sourceManifest = Get-Content -LiteralPath $clearance.sourceManifestPath -Raw | ConvertFrom-ReconstructionJson
                                $proofPaths += [string]$sourceManifest.exactSourcePhaseValidation.sourcePoseReferencePath
                            } catch {
                            }
                        }
                        foreach ($proofPath in $proofPaths) {
                            if ([string]::IsNullOrWhiteSpace([string]$proofPath)) { continue }
                            $resolvedProofPath = [IO.Path]::GetFullPath([string]$proofPath)
                            if ($resolvedProofPath.StartsWith($bakePrefix, [StringComparison]::OrdinalIgnoreCase) -and
                                (Test-Path -LiteralPath $resolvedProofPath -PathType Leaf)) {
                                $preservedFiles[$resolvedProofPath.ToLowerInvariant()] = $true
                            }
                        }
                    }
                } catch {
                    $preservedFiles = @{}
                }
            }
            foreach ($file in @(Get-ChildItem -LiteralPath $bakeRoot -File -Recurse -Force -ErrorAction SilentlyContinue)) {
                $resolvedFile = [IO.Path]::GetFullPath($file.FullName)
                if (-not $preservedFiles.ContainsKey($resolvedFile.ToLowerInvariant())) {
                    Remove-IntermediateArtifactFile -Path $resolvedFile
                }
            }
            foreach ($directory in @(Get-ChildItem -LiteralPath $bakeRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue | Sort-Object { $_.FullName.Length } -Descending)) {
                if (-not (Get-ChildItem -LiteralPath $directory.FullName -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) {
                    Remove-Item -LiteralPath $directory.FullName -Force
                }
            }
            if (-not (Get-ChildItem -LiteralPath $bakeRoot -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) {
                Remove-Item -LiteralPath $bakeRoot -Force
            }
        }
    }
    foreach ($path in @($WorkItem.exercisePlanPath, $WorkItem.exerciseCandidatesPath)) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}

function Get-SelectedOutputArtifacts {
    param([object]$WorkItem)

    # Structural completeness of a retained selection: the manifest plus one
    # consistent set of skeleton/preview/input outputs. Shared by the reuse
    # gate and the stale-policy re-audit so both judge the exact same files.
    $selectedOutputDir = Join-Path $WorkItem.exerciseWorkspace "selected"
    $selectionPath = Join-Path $selectedOutputDir "selection_manifest.json"
    if (-not (Test-Path -LiteralPath $selectionPath)) {
        return $null
    }

    $selectedFilePrefix = $WorkItem.exerciseSlug -replace "-", "_"
    $wearSkeletonFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_wear_skeleton.json" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    if ($wearSkeletonFiles.Count -eq 0) {
        return $null
    }
    foreach ($wearSkeletonFile in $wearSkeletonFiles) {
        if (-not (Test-MovementSkeletonIntegrity -Path $wearSkeletonFile.FullName)) {
            return $null
        }
    }

    $previewFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_selected_preview.webm" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    $inputFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_selected_input.mp4" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    $inputWebmFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_selected_input.webm" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    $previewHtmlFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_selected_preview.html" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    if ($previewFiles.Count -ne $wearSkeletonFiles.Count -or $previewHtmlFiles.Count -ne $wearSkeletonFiles.Count -or $inputFiles.Count -ne $wearSkeletonFiles.Count) {
        return $null
    }
    $interactivePreviewHtmlFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_interactive_preview.html" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    return [ordered]@{
        SelectedOutputDir = $selectedOutputDir
        SelectionPath = $selectionPath
        WearSkeletonFiles = $wearSkeletonFiles
        PreviewFiles = $previewFiles
        InputFiles = $inputFiles
        InputWebmFiles = $inputWebmFiles
        PreviewHtmlFiles = $previewHtmlFiles
        InteractivePreviewHtmlFiles = $interactivePreviewHtmlFiles
    }
}

function Test-SourceSelectionClearanceCurrent {
    param(
        [object]$Selection,
        [string]$SelectedInputPath,
        [string]$ExpectedExerciseName,
        [string]$ExpectedContractSha256,
        [bool]$AllowRawSkip
    )

    if ($null -eq $Selection -or $null -eq $Selection.selected -or $null -eq $Selection.selected.sourceSelectionClearance) {
        return $false
    }
    $clearance = $Selection.selected.sourceSelectionClearance
    $rawSkip = $AllowRawSkip -and
        $Selection.preReconstructionSourceValidationEnabled -eq $false -and
        $Selection.preReconstructionSourceValidationExplicitlyDisabled -eq $true
    $expectedStatus = if ($rawSkip) { "not_required" } else { "cleared" }
    if ($clearance.status -ne $expectedStatus -or
        [int]$clearance.sourceSelectionPolicyVersion -ne $SourceSelectionPolicyVersion -or
        [int]$clearance.sourceSelectionClearancePolicyVersion -ne $SourceSelectionClearancePolicyVersion) {
        return $false
    }
    if ($expectedStatus -eq "cleared" -and (
        [string]::IsNullOrWhiteSpace($ExpectedExerciseName) -or
        [string]$Selection.selected.exerciseName -ine $ExpectedExerciseName -or
        [string]$clearance.reviewedExerciseName -ine $ExpectedExerciseName -or
        [string]::IsNullOrWhiteSpace($ExpectedContractSha256) -or
        [string]$clearance.exerciseMotionContractSha256 -ine $ExpectedContractSha256
    )) {
        return $false
    }
    $clearancePaths = @('sourceManifestPath', 'selectedSegmentPath')
    if ($expectedStatus -eq "cleared") {
        $clearancePaths += @('sourceCutReviewVideoPath', 'sourceCutOriginalVideoPath')
    }
    foreach ($pathProperty in $clearancePaths) {
        $pathValue = [string]$clearance.$pathProperty
        if ([string]::IsNullOrWhiteSpace($pathValue) -or -not (Test-Path -LiteralPath $pathValue -PathType Leaf)) {
            return $false
        }
    }
    if ($rawSkip -and [string]::IsNullOrWhiteSpace([string]$clearance.sourcePrepReason)) {
        return $false
    }
    if (-not $rawSkip -and (
        [string]::IsNullOrWhiteSpace([string]$clearance.sourceCutReviewVideoSha256) -or
        [string]::IsNullOrWhiteSpace([string]$clearance.sourceCutOriginalVideoSha256) -or
        [string]::IsNullOrWhiteSpace([string]$clearance.sourceCutReviewFrameEvidenceSha256) -or
        $null -eq $clearance.sourceCutReviewFrameEvidence -or
        [string]$clearance.sourceCutReviewFrameEvidence.candidateId -cne [string]$clearance.authorizedCandidateId -or
        [string]::IsNullOrWhiteSpace([string]$clearance.sourceCutReviewFrameEvidence.extractionProfileSha256) -or
        @($clearance.sourceCutReviewFrameEvidence.images).Count -eq 0
    )) {
        return $false
    }
    try {
        $manifestHash = (Get-FileHash -LiteralPath $clearance.sourceManifestPath -Algorithm SHA256).Hash
        $segmentHash = (Get-FileHash -LiteralPath $clearance.selectedSegmentPath -Algorithm SHA256).Hash
        if ($manifestHash -ine [string]$clearance.sourceManifestSha256 -or
            $segmentHash -ine [string]$clearance.selectedSegmentSha256) {
            return $false
        }
        if (-not $rawSkip) {
            $reviewVideoHash = (Get-FileHash -LiteralPath $clearance.sourceCutReviewVideoPath -Algorithm SHA256).Hash
            $originalVideoHash = (Get-FileHash -LiteralPath $clearance.sourceCutOriginalVideoPath -Algorithm SHA256).Hash
            if ($reviewVideoHash -ine [string]$clearance.sourceCutReviewVideoSha256 -or
                $originalVideoHash -ine [string]$clearance.sourceCutOriginalVideoSha256) {
                return $false
            }
            foreach ($imageEvidence in @($clearance.sourceCutReviewFrameEvidence.images)) {
                $imagePath = [string]$imageEvidence.path
                if ([string]::IsNullOrWhiteSpace($imagePath) -or -not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
                    return $false
                }
                $imageHash = (Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash
                if ($imageHash -ine [string]$imageEvidence.sha256) { return $false }
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($SelectedInputPath)) {
            if (-not (Test-Path -LiteralPath $SelectedInputPath -PathType Leaf)) { return $false }
            $selectedInputHash = (Get-FileHash -LiteralPath $SelectedInputPath -Algorithm SHA256).Hash
            if ($selectedInputHash -ine [string]$clearance.selectedSegmentSha256) { return $false }
        }
        return $true
    } catch {
        return $false
    }
}

function Get-ExistingSelectedSummary {
    param([object]$WorkItem)

    $artifacts = Get-SelectedOutputArtifacts -WorkItem $WorkItem
    if ($null -eq $artifacts) {
        return $null
    }
    $selectedOutputDir = $artifacts.SelectedOutputDir
    $selectionPath = $artifacts.SelectionPath
    $wearSkeletonFiles = @($artifacts.WearSkeletonFiles)
    $previewFiles = @($artifacts.PreviewFiles)
    $inputFiles = @($artifacts.InputFiles)
    $inputWebmFiles = @($artifacts.InputWebmFiles)
    $previewHtmlFiles = @($artifacts.PreviewHtmlFiles)
    $interactivePreviewHtmlFiles = @($artifacts.InteractivePreviewHtmlFiles)
    $debugDir = Join-Path $selectedOutputDir "debug"
    $candidateDebugPath = Join-Path $debugDir "youtube_candidates.full.json"
    $candidateDecisionsPath = Join-Path $debugDir "candidate_decisions.jsonl"

    $selection = $null
    try {
        $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-ReconstructionJson
    } catch {
        $selection = $null
    }
    $revalidationPath = Join-Path $selectedOutputDir "revalidation.json"
    $currentRevalidation = $null
    if (Test-Path -LiteralPath $revalidationPath) {
        try {
            $candidateRevalidation = Get-Content -LiteralPath $revalidationPath -Raw | ConvertFrom-ReconstructionJson
            $matchesSelection = -not ($candidateRevalidation.PSObject.Properties.Name -contains 'selectedManifestSha256') -or
                $candidateRevalidation.selectedManifestSha256 -eq (Get-FileHash -LiteralPath $selectionPath -Algorithm SHA256).Hash
            if (-not $matchesSelection) { return $null }
            if (
                $matchesSelection -and
                [int]$candidateRevalidation.selectionValidationPolicyVersion -ge $SelectionValidationPolicyVersion -and
                [int]$candidateRevalidation.sourceSelectionPolicyVersion -ge $SourceSelectionPolicyVersion
            ) {
                $currentRevalidation = $candidateRevalidation
            }
        } catch {
            return $null
        }
    }
    if ((Test-Path -LiteralPath $revalidationPath) -and $null -eq $currentRevalidation) {
        return $null
    }
    if ($currentRevalidation -and $currentRevalidation.status -ne "valid") {
        return $null
    }
    $bakeSelectionManifestPath = Join-Path $WorkItem.exerciseWorkspace "bake\selection_manifest.json"
    if (
        $currentRevalidation -and
        -not (Test-Path -LiteralPath $bakeSelectionManifestPath) -and
        (
            -not ($currentRevalidation.PSObject.Properties.Name -contains "retainedSelectedArtifactFallbackVersion") -or
            [int]$currentRevalidation.retainedSelectedArtifactFallbackVersion -lt $RetainedSelectedRevalidationVersion
        )
    ) {
        return $null
    }
    $selectionPolicyCurrent = $selection -and (
        $selection.PSObject.Properties.Name -contains "selectionValidationPolicyVersion"
    ) -and [int]$selection.selectionValidationPolicyVersion -ge $SelectionValidationPolicyVersion
    $sourcePolicyCurrent = $selection -and (
        $selection.PSObject.Properties.Name -contains "sourceSelectionPolicyVersion"
    ) -and [int]$selection.sourceSelectionPolicyVersion -ge $SourceSelectionPolicyVersion
    if ((-not $selectionPolicyCurrent -or -not $sourcePolicyCurrent) -and -not $currentRevalidation) {
        return $null
    }
    $manifestSelected = if ($selection -and $selection.selected) { $selection.selected } else { $null }
    $sourceClearanceStatus = if ($manifestSelected -and $manifestSelected.sourceSelectionClearance) {
        [string]$manifestSelected.sourceSelectionClearance.status
    } else { "" }
    $selectedInputPath = if ($inputFiles.Count -gt 0) { $inputFiles[0].FullName } else { "" }
    if (-not (Test-SourceSelectionClearanceCurrent -Selection $selection -SelectedInputPath $selectedInputPath -ExpectedExerciseName ([string]$WorkItem.exerciseName) -ExpectedContractSha256 ([string]$WorkItem.currentContractSha256) -AllowRawSkip $SkipPreReconstructionSourceValidation)) {
        return $null
    }
    $manifestSelectedOptions = if ($selection -and $selection.PSObject.Properties.Name -contains "selectedResults" -and $selection.selectedResults) {
        @($selection.selectedResults)
    } elseif ($manifestSelected) {
        @($manifestSelected)
    } else {
        @()
    }

    $selectedResultOutputs = @()
    for ($index = 0; $index -lt $wearSkeletonFiles.Count; $index += 1) {
        $manifestOption = if ($index -lt $manifestSelectedOptions.Count) { $manifestSelectedOptions[$index] } else { $null }
        $selectedResultOutputs += [ordered]@{
            optionIndex = $index + 1
            label = if ($manifestOption -and $manifestOption.PSObject.Properties.Name -contains "manualSelectionLabel") { $manifestOption.manualSelectionLabel } else { "Option $($index + 1)" }
            selectedWearSkeletonPath = $wearSkeletonFiles[$index].FullName
            selectedPreviewVideoPath = if ($index -lt $previewFiles.Count) { $previewFiles[$index].FullName } else { $null }
            selectedPreviewHtmlPath = if ($index -lt $previewHtmlFiles.Count) { $previewHtmlFiles[$index].FullName } else { $null }
            selectedInteractivePreviewHtmlPath = if ($index -lt $interactivePreviewHtmlFiles.Count) { $interactivePreviewHtmlFiles[$index].FullName } else { $null }
            selectedSourceVideoPath = if ($index -lt $inputFiles.Count) { $inputFiles[$index].FullName } else { $null }
            selectedSourceVideoWebmPath = if ($index -lt $inputWebmFiles.Count) { $inputWebmFiles[$index].FullName } else { $null }
            selectedSourceVideoOriginalPath = if ($manifestOption -and $manifestOption.PSObject.Properties.Name -contains "selectedInputVideoPath") { $manifestOption.selectedInputVideoPath } else { $null }
            selectedSourceVideoMissing = $false
            selectionScore = if ($manifestOption -and $manifestOption.PSObject.Properties.Name -contains "selectionScore") { $manifestOption.selectionScore } else { $null }
            candidateTitle = if ($manifestOption -and $manifestOption.PSObject.Properties.Name -contains "candidateTitle") { $manifestOption.candidateTitle } else { $null }
        }
    }

    Write-Host ("Already have a movement for {0}." -f $WorkItem.exerciseName)

    return [ordered]@{
        exerciseId = $WorkItem.exerciseId
        exerciseName = $WorkItem.exerciseName
        status = "completed"
        reusedExistingSelected = $true
        error = $null
        candidateCount = $WorkItem.candidateCount
        excludeCandidateJsonPaths = $WorkItem.excludeCandidateJsonPaths
        candidatesJsonPath = $null
        selectionManifestPath = $selectionPath
        logPath = $WorkItem.logPath
        selectedWearSkeletonPath = $wearSkeletonFiles[0].FullName
        selectedPreviewVideoPath = if ($previewFiles.Count -gt 0) { $previewFiles[0].FullName } else { $null }
        selectedInteractivePreviewHtmlPath = if ($interactivePreviewHtmlFiles.Count -gt 0) { $interactivePreviewHtmlFiles[0].FullName } else { $null }
        selectedSourceVideoPath = if ($inputFiles.Count -gt 0) { $inputFiles[0].FullName } else { $null }
        selectedSourceVideoWebmPath = if ($inputWebmFiles.Count -gt 0) { $inputWebmFiles[0].FullName } else { $null }
        selectedSourceVideoOriginalPath = if ($manifestSelected -and $manifestSelected.PSObject.Properties.Name -contains "selectedInputVideoPath") { $manifestSelected.selectedInputVideoPath } else { $null }
        selectedSourceVideoMissing = $false
        selectedResults = $selectedResultOutputs
        selectedCandidateDebugPath = if (Test-Path -LiteralPath $candidateDebugPath) { $candidateDebugPath } else { $null }
        selectedCandidateDecisionsPath = if (Test-Path -LiteralPath $candidateDecisionsPath) { $candidateDecisionsPath } else { $null }
    }
}

function Test-SelectionNeedsPolicyReaudit {
    param([object]$WorkItem)

    # A retained selection can be structurally complete yet carry session
    # state written by older code (policy-version markers, audit checksums,
    # fallback-version stamps). Reuse must not silently discard that work: the
    # stale state means "re-audit under the current policy", not "no
    # selection". This mirrors Get-ExistingSelectedSummary's gate and asks for
    # a re-audit exactly when that gate would reject on stale session state;
    # an explicit prior verdict (invalid / needs review) always stands.
    $artifacts = Get-SelectedOutputArtifacts -WorkItem $WorkItem
    if ($null -eq $artifacts) {
        return $false
    }
    try {
        $selection = Get-Content -LiteralPath $artifacts.SelectionPath -Raw | ConvertFrom-ReconstructionJson
    } catch {
        return $false
    }
    $manifestCurrent = ($selection.PSObject.Properties.Name -contains "selectionValidationPolicyVersion") -and
        [int]$selection.selectionValidationPolicyVersion -ge $SelectionValidationPolicyVersion
    $revalidationPath = Join-Path $artifacts.SelectedOutputDir "revalidation.json"
    if (-not (Test-Path -LiteralPath $revalidationPath)) {
        return -not $manifestCurrent
    }
    try {
        $marker = Get-Content -LiteralPath $revalidationPath -Raw | ConvertFrom-ReconstructionJson
        if ("$($marker.status)" -in @("invalid", "needs_manual_review")) {
            return $false
        }
        $shaOk = -not ($marker.PSObject.Properties.Name -contains "selectedManifestSha256") -or
            $marker.selectedManifestSha256 -eq (Get-FileHash -LiteralPath $artifacts.SelectionPath -Algorithm SHA256).Hash
        if (-not $shaOk) {
            return $true
        }
        $markerCurrent = ($marker.PSObject.Properties.Name -contains "selectionValidationPolicyVersion") -and
            [int]$marker.selectionValidationPolicyVersion -ge $SelectionValidationPolicyVersion
        $sourceMarkerCurrent = ($marker.PSObject.Properties.Name -contains "sourceSelectionPolicyVersion") -and
            [int]$marker.sourceSelectionPolicyVersion -ge $SourceSelectionPolicyVersion
        if (-not $sourceMarkerCurrent) {
            return $true
        }
        if ($markerCurrent -and "$($marker.status)" -ne "valid") {
            return $true
        }
        $bakeSelectionManifestPath = Join-Path $WorkItem.exerciseWorkspace "bake\selection_manifest.json"
        if (
            $markerCurrent -and
            -not (Test-Path -LiteralPath $bakeSelectionManifestPath) -and
            (
                -not ($marker.PSObject.Properties.Name -contains "retainedSelectedArtifactFallbackVersion") -or
                [int]$marker.retainedSelectedArtifactFallbackVersion -lt $RetainedSelectedRevalidationVersion
            )
        ) {
            return $true
        }
        $sourceManifestCurrent = ($selection.PSObject.Properties.Name -contains "sourceSelectionPolicyVersion") -and
            [int]$selection.sourceSelectionPolicyVersion -ge $SourceSelectionPolicyVersion
        if ((-not $manifestCurrent -and -not $markerCurrent) -or
            (-not $sourceManifestCurrent -and -not $sourceMarkerCurrent)) {
            return $true
        }
        $selected = $selection.selected
        $clearanceStatus = if ($selected -and $selected.sourceSelectionClearance) {
            [string]$selected.sourceSelectionClearance.status
        } else { "" }
        $inputPath = if ($artifacts.InputFiles.Count -gt 0) { $artifacts.InputFiles[0].FullName } else { "" }
        if (-not (Test-SourceSelectionClearanceCurrent -Selection $selection -SelectedInputPath $inputPath -ExpectedExerciseName ([string]$WorkItem.exerciseName) -ExpectedContractSha256 ([string]$WorkItem.currentContractSha256) -AllowRawSkip $SkipPreReconstructionSourceValidation)) {
            return $true
        }
        return $false
    } catch {
        return $true
    }
}

function Invoke-SelectionPolicyReaudit {
    param([string[]]$ExerciseSlugs)

    # Refresh stale selection session state by re-auditing the retained
    # artifacts under the current quality policy (the shared library
    # revalidation flow), so reuse is decided by a current audit instead of
    # silently discarding validated selections. Failures fall back to the
    # recorded markers, which is never worse than skipping the re-audit.
    $reportPath = Join-Path $resolvedWorkspaceRoot "exercise_library_reuse_revalidation_report.json"
    Write-Host ("Revalidating {0} retained selection(s) under the current quality policy before reuse." -f $ExerciseSlugs.Count)
    $reauditArguments = [string[]]@(
        "-m", "exercise_motion_pkg.cli", "revalidate-library-workspace",
        "--workspace-root", $resolvedWorkspaceRoot,
        "--exercise-library-json", $resolvedWorkoutPlanJson,
        "--out-json", $reportPath,
        "--selected-artifacts-only"
    )
    if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
        $reauditArguments += @("--equipment-json", $EquipmentJson)
    }
    foreach ($exerciseSlug in $ExerciseSlugs) {
        $reauditArguments += @("--only-exercise-slug", $exerciseSlug)
    }
    & $PythonCommand @reauditArguments
    $reauditExitCode = $LASTEXITCODE
    if ((Test-MotionRunCancelRequested) -or $reauditExitCode -eq 130) {
        Write-MotionInterruptReceived
        exit 130
    }
    if ($reauditExitCode -ne 0) {
        Write-Warning ("Selection re-audit exited with code {0}; reuse falls back to the recorded markers." -f $reauditExitCode)
    }
}

function Resume-YieldedDiscovery {
    param([object]$WorkItem, [object]$PendingQueue)

    $payload = Get-Content -LiteralPath $WorkItem.exerciseCandidatesPath -Raw | ConvertFrom-ReconstructionJson
    $turn = @($payload.exercises)[0].candidateExpansion.discoveryTurn
    if ($turn.stopReason -ne 'scheduler_yield') { return $false }

    # Keep the original allowance across scheduler pauses. Starting a new
    # process must not grant another full candidate or time budget.
    $limits = @{
        '--discovery-candidate-budget' = if ([int]$turn.candidateBudget -gt 0) {
            [Math]::Max(0, [int]$turn.candidateBudget - [int]$turn.reviewedThisTurn)
        } else { 0 }
        '--discovery-time-budget-seconds' = if ([double]$turn.timeBudgetSeconds -gt 0) {
            [double]$turn.remainingTimeSeconds
        } else { 0 }
    }
    if (([int]$turn.candidateBudget -gt 0 -and $limits['--discovery-candidate-budget'] -le 0) -or
        ([double]$turn.timeBudgetSeconds -gt 0 -and $limits['--discovery-time-budget-seconds'] -le 0)) {
        return $false
    }
    $arguments = [string[]]@($WorkItem.discoveryArgs)
    foreach ($name in $limits.Keys) {
        $position = [Array]::IndexOf($arguments, $name)
        if ($position -lt 0 -or $position + 1 -ge $arguments.Length) {
            throw "Missing discovery budget argument: $name"
        }
        $arguments[$position + 1] = ([double]$limits[$name]).ToString('G', [Globalization.CultureInfo]::InvariantCulture)
    }
    $WorkItem.discoveryArgs = $arguments
    $PendingQueue.Enqueue($WorkItem)
    return $true
}

function Set-DiscoveryArgumentValue {
    param([string[]]$Arguments, [string]$Name, [string]$Value)
    $updated = [System.Collections.Generic.List[string]]::new()
    $replaced = $false
    for ($index = 0; $index -lt $Arguments.Count; $index += 1) {
        if ($Arguments[$index] -eq $Name) {
            $updated.Add($Name)
            $updated.Add($Value)
            $replaced = $true
            $index += 1
            continue
        }
        $updated.Add($Arguments[$index])
    }
    if (-not $replaced) { $updated.Add($Name); $updated.Add($Value) }
    return [string[]]$updated.ToArray()
}

function Set-BoundedSourceRecoveryDiscovery {
    param([object]$WorkItem, [object]$WaveState, [int]$CandidateBudget)

    $retryCount = if ($WorkItem.PSObject.Properties.Name -contains 'sourceDiscoveryRetryCount') {
        [int]$WorkItem.sourceDiscoveryRetryCount
    } else { 0 }
    if ($retryCount -ge 1) { return $false }

    $source = Get-ObjectProperty -Object $WaveState -Name 'source'
    $attemptedCandidateKeys = @(
        @($source.priorAttemptedCandidateKeys) +
        @($source.attempts | ForEach-Object { $_.candidateKey })
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -Unique
    $attemptedVideoIds = @(
        @($source.priorAttemptedVideoIds) +
        @($source.attempts | ForEach-Object { $_.videoId })
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -Unique
    # Candidate keys include the exact source window. Keep these keys out of
    # the next ranked manifest without excluding other windows from the same
    # video, which may still contain usable evidence.
    $sourceTurnResume = [ordered]@{
        sourceSelectionPolicyVersion = Resolve-WaveSourceSelectionPolicyVersion -Source $source
        nextCandidateKey = $null
        attemptedCandidateKeys = @($attemptedCandidateKeys)
        attemptedVideoIds = @($attemptedVideoIds)
    }
    $resumePath = Join-Path $WorkItem.bakeWorkspace 'source_turn_resume.json'
    New-Item -ItemType Directory -Path (Split-Path -Parent $resumePath) -Force | Out-Null
    [System.IO.File]::WriteAllText(
        $resumePath,
        ($sourceTurnResume | ConvertTo-Json -Depth 8),
        [System.Text.UTF8Encoding]::new($false)
    )
    $arguments = [string[]]$WorkItem.discoveryArgs
    $recoveryCandidateBudget = if ($CandidateBudget -gt 0) {
        $CandidateBudget
    } else {
        [Math]::Max(1, $attemptedCandidateKeys.Count + 1)
    }
    $arguments = Set-DiscoveryArgumentValue -Arguments $arguments -Name '--discovery-candidate-budget' -Value "$recoveryCandidateBudget"
    $WorkItem.discoveryArgs = $arguments
    $WorkItem.discoveryArgumentsSha256 = Get-ArgumentArraySha256 -Arguments $arguments
    $WorkItem.candidateReviewTargetSuitableCount = 1
    if ($WorkItem.PSObject.Properties.Name -contains 'sourceDiscoveryRetryCount') {
        $WorkItem.sourceDiscoveryRetryCount = $retryCount + 1
    } else {
        $WorkItem | Add-Member -NotePropertyName sourceDiscoveryRetryCount -NotePropertyValue ($retryCount + 1)
    }
    return $true
}

function Start-InitialDiscoveryJob {
    param([object]$WorkItem)

    $yieldRequestPath = Join-Path (Split-Path -Parent $WorkItem.exerciseCandidatesPath) 'discovery_yield.request'
    if (Test-Path -LiteralPath $yieldRequestPath) { Remove-Item -LiteralPath $yieldRequestPath -Force }
    Write-Host ("Finding a source for {0}." -f $WorkItem.exerciseName)
    $job = Start-Job -InitializationScript $script:ReconstructionJobInitialization -Name "discover-$($WorkItem.exerciseSlug)" -ScriptBlock {
        param(
            [string]$PythonCommand,
            [string[]]$DiscoveryArguments,
            [string]$LogPath,
            [string]$CandidatesPath,
            [int]$InitialTargetSuitableCount,
            [int]$MaxTargetSuitableCount,
            [int]$BaseMaxCandidates,
            [int]$BaseVisionCandidates,
            [string]$ArgumentsSha256,
            [string]$ExercisePlanSha256,
            [string]$EquipmentSha256,
            [int]$StagePolicyVersion
        )

        $ErrorActionPreference = "Continue"

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

        function Get-CandidateCounts {
            param([string]$Path)
            $candidateCount = 0
            $recommendedCount = 0
            if (Test-Path -LiteralPath $Path) {
                try {
                    $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-ReconstructionJson
                    foreach ($exercise in @($payload.exercises)) {
                        foreach ($item in @($exercise.candidates)) {
                            $candidateCount += 1
                            if ("$($item.status)".ToLowerInvariant() -eq "recommended") {
                                $recommendedCount += 1
                            }
                        }
                    }
                } catch {
                    $candidateCount = 0
                    $recommendedCount = 0
                }
            }
            return [pscustomobject]@{
                candidateCount = $candidateCount
                recommendedCount = $recommendedCount
            }
        }

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
        "[$(Get-Date -Format o)] initial discovery stage started" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        $targetSuitableCount = [Math]::Max(1, $InitialTargetSuitableCount)
        $attemptMaxCandidates = [Math]::Max($BaseMaxCandidates, $targetSuitableCount)
        $attemptVisionCandidates = [Math]::Max($BaseVisionCandidates, $targetSuitableCount)
        $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $DiscoveryArguments -Name "--candidate-review-target-suitable-count" -Value "$targetSuitableCount"
        $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--max-candidates" -Value "$attemptMaxCandidates"
        $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--vision-candidates-per-exercise" -Value "$attemptVisionCandidates"

        $maxTransientServerAttempts = 3
        $discoveryAttempts = @()
        $discoverySeconds = 0.0
        $definitionReviewReason = $null
        for ($attemptIndex = 1; $attemptIndex -le $maxTransientServerAttempts; $attemptIndex += 1) {
            "[$(Get-Date -Format o)] initial discovery attempt $attemptIndex started; target suitable candidates $targetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            & $PythonCommand @attemptDiscoveryArgs *>> $LogPath
            $exitCode = $LASTEXITCODE
            if ($exitCode -eq 0 -and (Test-Path -LiteralPath $CandidatesPath)) {
                try {
                    $candidatePayload = Get-Content -LiteralPath $CandidatesPath -Raw | ConvertFrom-ReconstructionJson
                    $definitionEntry = @($candidatePayload.exercises | Where-Object { $_.status -eq "needs_definition_review" } | Select-Object -First 1)
                    if ($definitionEntry.Count -gt 0) {
                        $definitionReviewReason = [string]$definitionEntry[0].reason
                    } elseif ($candidatePayload.status -eq "needs_definition_review") {
                        $definitionReviewReason = [string]$candidatePayload.reason
                    }
                    $candidatePayload | Add-Member -NotePropertyName wrapperDiscoverySignature -NotePropertyValue ([pscustomobject]@{
                        schemaVersion = 1
                        policyVersion = $StagePolicyVersion
                        completedAt = (Get-Date).ToUniversalTime().ToString("o")
                        argumentsSha256 = $ArgumentsSha256
                        exercisePlanSha256 = $ExercisePlanSha256
                        equipmentSha256 = if ([string]::IsNullOrWhiteSpace($EquipmentSha256)) { $null } else { $EquipmentSha256 }
                    }) -Force
                    $temporaryCandidatesPath = "$CandidatesPath.tmp"
                    $candidatePayload | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $temporaryCandidatesPath -Encoding UTF8
                    Move-Item -Force -LiteralPath $temporaryCandidatesPath -Destination $CandidatesPath
                } catch {
                    "[$(Get-Date -Format o)] discovery completion signature write failed: $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                    $exitCode = 1
                }
            }
            $stopwatch.Stop()
            $elapsedSeconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
            $discoverySeconds = [Math]::Round(($discoverySeconds + $elapsedSeconds), 3)
            $counts = Get-CandidateCounts -Path $CandidatesPath
            "[$(Get-Date -Format o)] initial discovery attempt $attemptIndex finished with exit code $exitCode; recommended $($counts.recommendedCount), candidates $($counts.candidateCount), elapsed ${elapsedSeconds}s" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            $discoveryAttempts += [ordered]@{
                attemptIndex = $attemptIndex
                stage = "initial_discovery"
                exitCode = $exitCode
                targetSuitableCount = $targetSuitableCount
                candidateCount = $counts.candidateCount
                recommendedCount = $counts.recommendedCount
                elapsedSeconds = $elapsedSeconds
            }
            if ($exitCode -eq 0) {
                break
            }
            $logTail = (Get-Content -LiteralPath $LogPath -Tail 100 -ErrorAction SilentlyContinue) -join "`n"
            $isTransientServerStartupFailure = $logTail -match "llama-server did not become healthy"
            $isTransientPythonSourceLoadFailure = $logTail -match "(?m)(SyntaxError|IndentationError):"
            $maximumAttemptsForFailure = if ($isTransientServerStartupFailure) {
                $maxTransientServerAttempts
            } elseif ($isTransientPythonSourceLoadFailure) {
                2
            } else {
                1
            }
            if ($attemptIndex -ge $maximumAttemptsForFailure) {
                break
            }
            $retryReason = if ($isTransientServerStartupFailure) {
                "transient llama-server startup failure"
            } else {
                "transient Python source-load failure"
            }
            "[$(Get-Date -Format o)] retrying initial discovery after $retryReason" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            Start-Sleep -Seconds 5
        }
        [pscustomobject]@{
            exitCode = $exitCode
            stage = "initial_discovery"
            logPath = $LogPath
            candidateCount = $counts.candidateCount
            recommendedCount = $counts.recommendedCount
            definitionReviewReason = $definitionReviewReason
            discoverySeconds = $discoverySeconds
            attempts = $discoveryAttempts
            attemptIndex = $discoveryAttempts.Count
            targetSuitableCount = $targetSuitableCount
        }
    } -ArgumentList $PythonCommand, ([string[]]$WorkItem.discoveryArgs), $WorkItem.logPath, $WorkItem.exerciseCandidatesPath, $WorkItem.candidateReviewTargetSuitableCount, $WorkItem.maxCandidateReviewTargetSuitableCount, $WorkItem.maxCandidates, $WorkItem.visionCandidatesPerExercise, $WorkItem.discoveryArgumentsSha256, $WorkItem.exercisePlanSha256, $WorkItem.equipmentSha256, $discoveryStagePolicyVersion
    $job | Add-Member -MemberType NoteProperty -Name WorkItem -Value $WorkItem
    return $job
}

function Start-CandidatePrefetchJob {
    param([object]$WorkItem)

    $job = Start-Job -InitializationScript $script:ReconstructionJobInitialization -Name "prefetch-$($WorkItem.exerciseSlug)" -ScriptBlock {
        param(
            [string]$PythonCommand,
            [string[]]$PrefetchArguments,
            [string]$LogPath,
            [string]$PrefetchPath,
            [string]$ArgumentsSha256,
            [string]$ExercisePlanSha256,
            [string]$EquipmentSha256
        )

        $ErrorActionPreference = "Continue"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
        "[$(Get-Date -Format o)] CPU/network candidate prefetch started" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        & $PythonCommand @PrefetchArguments *>> $LogPath
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0 -and (Test-Path -LiteralPath $PrefetchPath)) {
            try {
                $prefetchPayload = Get-Content -LiteralPath $PrefetchPath -Raw | ConvertFrom-ReconstructionJson
                $prefetchPayload | Add-Member -NotePropertyName wrapperPrefetchSignature -NotePropertyValue ([pscustomobject]@{
                    schemaVersion = 1
                    argumentsSha256 = $ArgumentsSha256
                    exercisePlanSha256 = $ExercisePlanSha256
                    equipmentSha256 = if ([string]::IsNullOrWhiteSpace($EquipmentSha256)) { $null } else { $EquipmentSha256 }
                }) -Force
                $temporaryPrefetchPath = "$PrefetchPath.tmp"
                $prefetchPayload | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $temporaryPrefetchPath -Encoding UTF8
                Move-Item -Force -LiteralPath $temporaryPrefetchPath -Destination $PrefetchPath
            } catch {
                "[$(Get-Date -Format o)] candidate prefetch signature write failed: $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                $exitCode = 1
            }
        }
        $stopwatch.Stop()
        $elapsedSeconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
        "[$(Get-Date -Format o)] CPU/network candidate prefetch finished with exit code $exitCode; elapsed ${elapsedSeconds}s" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        [pscustomobject]@{
            exitCode = $exitCode
            stage = "candidate_prefetch"
            prefetchSeconds = $elapsedSeconds
        }
    } -ArgumentList $PythonCommand, ([string[]]$WorkItem.prefetchArgs), $WorkItem.logPath, $WorkItem.prefetchPath, $WorkItem.prefetchArgumentsSha256, $WorkItem.exercisePlanSha256, $WorkItem.equipmentSha256
    $job | Add-Member -MemberType NoteProperty -Name WorkItem -Value $WorkItem
    return $job
}

function Start-SourceDownloadJob {
    param(
        [object]$WorkItem,
        [string[]]$Arguments,
        [ValidateSet("primary", "fallback")]
        [string]$Kind
    )

    $sourceDownloadLogPath = if ($Kind -eq "primary") {
        $WorkItem.primarySourceDownloadLogPath
    } else {
        $WorkItem.fallbackSourceDownloadLogPath
    }
    $reportPath = if ($Kind -eq "primary") {
        $WorkItem.sourceDownloadReportPath
    } else {
        $WorkItem.fallbackSourceDownloadReportPath
    }
    $argumentsSha256 = if ($Kind -eq "primary") {
        $WorkItem.primarySourceDownloadArgumentsSha256
    } else {
        $WorkItem.fallbackSourceDownloadArgumentsSha256
    }
    $job = Start-Job -InitializationScript $script:ReconstructionJobInitialization -Name "source-download-$Kind-$($WorkItem.exerciseSlug)" -ScriptBlock {
        param(
            [string]$PythonCommand,
            [string[]]$SourceDownloadArguments,
            [string]$LogPath,
            [string]$DownloadKind,
            [string]$ReportPath,
            [string]$CandidatesPath,
            [string]$ArgumentsSha256,
            [string]$ExercisePlanSha256,
            [string]$EquipmentSha256,
            [int]$StagePolicyVersion
        )

        $ErrorActionPreference = "Continue"
        "[$(Get-Date -Format o)] $DownloadKind full-source download prefetch started" | Set-Content -LiteralPath $LogPath -Encoding UTF8
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        & $PythonCommand @SourceDownloadArguments *>> $LogPath
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0 -and (Test-Path -LiteralPath $ReportPath) -and (Test-Path -LiteralPath $CandidatesPath)) {
            try {
                $sourcePayload = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-ReconstructionJson
                $candidateSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $CandidatesPath).Hash.ToLowerInvariant()
                $sourcePayload | Add-Member -NotePropertyName wrapperSourceDownloadSignature -NotePropertyValue ([pscustomobject]@{
                    schemaVersion = 1
                    policyVersion = $StagePolicyVersion
                    kind = $DownloadKind
                    completedAt = (Get-Date).ToUniversalTime().ToString("o")
                    argumentsSha256 = $ArgumentsSha256
                    exercisePlanSha256 = $ExercisePlanSha256
                    equipmentSha256 = if ([string]::IsNullOrWhiteSpace($EquipmentSha256)) { $null } else { $EquipmentSha256 }
                    candidatesSha256 = $candidateSha256
                }) -Force
                $temporaryReportPath = "$ReportPath.tmp"
                $sourcePayload | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $temporaryReportPath -Encoding UTF8
                Move-Item -Force -LiteralPath $temporaryReportPath -Destination $ReportPath
            } catch {
                "[$(Get-Date -Format o)] $DownloadKind source-download completion signature write failed: $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                $exitCode = 1
            }
        }
        $stopwatch.Stop()
        $elapsedSeconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
        "[$(Get-Date -Format o)] $DownloadKind full-source download prefetch finished with exit code $exitCode; elapsed ${elapsedSeconds}s" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        [pscustomobject]@{
            exitCode = $exitCode
            stage = "source_download_prefetch"
            sourceDownloadSeconds = $elapsedSeconds
            logPath = $LogPath
        }
    } -ArgumentList $PythonCommand, ([string[]]$Arguments), $sourceDownloadLogPath, $Kind, $reportPath, $WorkItem.exerciseCandidatesPath, $argumentsSha256, $WorkItem.exercisePlanSha256, $WorkItem.equipmentSha256, $sourceDownloadStagePolicyVersion
    $job | Add-Member -MemberType NoteProperty -Name WorkItem -Value $WorkItem
    $job | Add-Member -MemberType NoteProperty -Name DownloadKind -Value $Kind
    return $job
}

function Test-CandidatePrefetchReady {
    param([object]$WorkItem)

    if (-not (Test-Path -LiteralPath $WorkItem.prefetchPath)) {
        return $false
    }
    try {
        $payload = Get-Content -LiteralPath $WorkItem.prefetchPath -Raw | ConvertFrom-ReconstructionJson
        if ($payload.kind -ne "youtube_candidate_prefetch") {
            return $false
        }
        if ("$($payload.sourcePlanSha256)".ToLowerInvariant() -ne $WorkItem.exercisePlanSha256) {
            return $false
        }
        $signature = $payload.wrapperPrefetchSignature
        if ($null -eq $signature -or [int]$signature.schemaVersion -ne 1) {
            return $false
        }
        if ("$($signature.argumentsSha256)".ToLowerInvariant() -ne $WorkItem.prefetchArgumentsSha256) {
            return $false
        }
        if ("$($signature.exercisePlanSha256)".ToLowerInvariant() -ne $WorkItem.exercisePlanSha256) {
            return $false
        }
        $cachedEquipmentHash = "$($signature.equipmentSha256)".ToLowerInvariant()
        if ($cachedEquipmentHash -ne $WorkItem.equipmentSha256) {
            return $false
        }
        return $true
    } catch {
        return $false
    }
}

function Test-DiscoveryStageReady {
    param([object]$WorkItem, [object]$Payload)

    if (-not (Test-Path -LiteralPath $WorkItem.exerciseCandidatesPath)) {
        return $false
    }
    try {
        if ($null -eq $Payload) {
            $Payload = Get-Content -LiteralPath $WorkItem.exerciseCandidatesPath -Raw | ConvertFrom-ReconstructionJson
        }
        $signature = $payload.wrapperDiscoverySignature
        if ($null -eq $signature -or [int]$signature.schemaVersion -ne 1) {
            return $false
        }
        if ($null -ne (Get-DefinitionReviewReason -Payload $Payload)) {
            return (
                [int]$signature.policyVersion -eq $discoveryStagePolicyVersion -and
                "$($signature.argumentsSha256)".ToLowerInvariant() -eq $WorkItem.discoveryArgumentsSha256 -and
                "$($signature.exercisePlanSha256)".ToLowerInvariant() -eq $WorkItem.exercisePlanSha256 -and
                "$($signature.equipmentSha256)".ToLowerInvariant() -eq $WorkItem.equipmentSha256
            )
        }
        # The owner's naming convention changes target identity, so even an
        # old recommended source needs review under the explicit one-arm rule.
        $hasSingleDumbbellTarget = @($payload.exercises | Where-Object {
            $_.exerciseName -match '^Single[\s_-]+Dumbbell[\s_-]'
        }).Count -gt 0
        if ($hasSingleDumbbellTarget -and [int]$payload.ranking.singleDumbbellNamingPolicyVersion -lt 3) {
            return $false
        }
        # Revisit old all-rejected discovery under the bounded contradiction
        # policy. Successful source sets and downstream artifacts remain reusable.
        $hasRecommendedCandidate = Test-HasIdentityReviewedRecommendedCandidate `
            -CandidatesPath $WorkItem.exerciseCandidatesPath -Payload $payload
        $hasStaticHold = @($payload.exercises | Where-Object {
            $_.exerciseMotionContract.completionMode -eq "stable_hold"
        }).Count -gt 0
        if (-not $hasRecommendedCandidate -and $hasStaticHold -and [int]$payload.ranking.staticHoldReviewPolicyVersion -lt 1) {
            return $false
        }
        if (-not $hasRecommendedCandidate) {
            # A decoder/network failure is unfinished discovery, including old
            # manifests that mislabeled it as a pose-quality rejection.
            $incompletePoseReviews = @($payload.exercises | ForEach-Object {
                @($_.candidates) + @($_.debugCandidates)
            } | Where-Object {
                $pose = $_.visionPayload.posePrefilter
                $pose.reviewStatus -eq 'incomplete' -or
                -not [string]::IsNullOrWhiteSpace([string]$pose.error) -or
                $pose.failureReason -in @('pose_prefilter_failed', 'youtube_rate_limited')
            })
            if ($incompletePoseReviews.Count -gt 0) { return $false }
        }
        $yieldRequestPath = Join-Path (Split-Path -Parent $WorkItem.exerciseCandidatesPath) 'discovery_yield.request'
        $yieldedTurns = @($payload.exercises | Where-Object {
            $turn = $_.candidateExpansion.discoveryTurn
            $turn.stopReason -eq 'scheduler_yield' -or (
                [string]::IsNullOrWhiteSpace([string]$turn.stopReason) -and
                $turn.budgetExhausted -and (Test-Path -LiteralPath $yieldRequestPath) -and
                ([int]$turn.candidateBudget -le 0 -or [int]$turn.reviewedThisTurn -lt [int]$turn.candidateBudget)
            )
        })
        if (-not $hasRecommendedCandidate -and $yieldedTurns.Count -gt 0) { return $false }
        if (-not $hasRecommendedCandidate) {
            $staleCameraRejections = @($payload.exercises | ForEach-Object { $_.debugCandidates } | Where-Object {
                $pose = $_.visionPayload.posePrefilter
                $pose.passed -eq $false -and [int]$pose.cameraPolicyVersion -lt 1 -and
                @($pose.blockingIssues) -contains 'camera_or_track_instability'
            })
            if ($staleCameraRejections.Count -gt 0) { return $false }
        }
        if (-not $hasRecommendedCandidate -and [int]$payload.ranking.sourceRejectionReviewPolicyVersion -lt 1) {
            return $false
        }
        if ("$($signature.exercisePlanSha256)".ToLowerInvariant() -ne $WorkItem.exercisePlanSha256) {
            return $false
        }
        if ("$($signature.equipmentSha256)".ToLowerInvariant() -ne $WorkItem.equipmentSha256) {
            return $false
        }
        $previousSelectionPath = Join-Path $WorkItem.bakeWorkspace "selection_manifest.json"
        $hasPreviousSelection = $false
        if (Test-Path -LiteralPath $previousSelectionPath) {
            $previousSelection = Get-Content -LiteralPath $previousSelectionPath -Raw | ConvertFrom-ReconstructionJson
            $hasPreviousSelection = (
                $null -ne $previousSelection.selected -or
                @($previousSelection.selectedResults).Count -gt 0
            )
        }
        if (
            [int]$signature.policyVersion -ne $discoveryStagePolicyVersion -or
            "$($signature.argumentsSha256)".ToLowerInvariant() -ne $WorkItem.discoveryArgumentsSha256
        ) {
            # A previously accepted reconstruction is authoritative evidence
            # that this candidate set contains a usable source. Downstream
            # cleanup, IK, rendering, or validation policy changes must not
            # force another network/VLM discovery pass for that same exercise.
            if (-not $hasPreviousSelection) {
                return $false
            }
        }
        return @($payload.exercises).Count -gt 0
    } catch {
        return $false
    }
}

function Test-MovementSkeletonIntegrity {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    try {
        $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-ReconstructionJson
        return (
            @($payload.jointNames).Count -gt 0 -and
            @($payload.frames).Count -gt 1 -and
            [int]$payload.frameCount -eq @($payload.frames).Count -and
            [double]$payload.fps -gt 0
        )
    } catch {
        return $false
    }
}

function Test-BakeStageReady {
    param([object]$WorkItem)

    $selectionPath = Join-Path $WorkItem.bakeWorkspace "selection_manifest.json"
    if (-not (Test-Path -LiteralPath $selectionPath)) {
        return $false
    }
    try {
        $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-ReconstructionJson
        if ([int]$selection.selectionValidationPolicyVersion -lt $SelectionValidationPolicyVersion) {
            return $false
        }
        $selectedResults = if (
            $selection.PSObject.Properties.Name -contains "selectedResults" -and
            @($selection.selectedResults).Count -gt 0
        ) {
            @($selection.selectedResults)
        } elseif ($null -ne $selection.selected) {
            @($selection.selected)
        } else {
            @()
        }
        if ($selectedResults.Count -eq 0) {
            return $false
        }
        foreach ($selectedResult in $selectedResults) {
            $skeletonPath = "$($selectedResult.selectedWearSkeletonPath)"
            if ([string]::IsNullOrWhiteSpace($skeletonPath)) {
                $skeletonPath = "$($selectedResult.skeletonPath)"
            }
            if (-not (Test-MovementSkeletonIntegrity -Path $skeletonPath)) {
                return $false
            }
        }
        return $true
    } catch {
        return $false
    }
}

function Test-SelectionHasNeedsMotionProcessing {
    param([string]$SelectionPath)

    if ([string]::IsNullOrWhiteSpace($SelectionPath) -or -not (Test-Path -LiteralPath $SelectionPath)) {
        return $false
    }
    try {
        $selection = Get-Content -LiteralPath $SelectionPath -Raw | ConvertFrom-ReconstructionJson
        $results = @()
        if ($selection.PSObject.Properties.Name -contains "candidateResults") {
            $results += @($selection.candidateResults)
        }
        if ($selection.PSObject.Properties.Name -contains "candidateDiagnostics") {
            $results += @($selection.candidateDiagnostics)
        }
        return (@($results | Where-Object { "$($_.status)" -eq "needs_motion_processing" }).Count -gt 0)
    } catch {
        return $false
    }
}

function Test-CandidateIdentityEvidenceComplete {
    param([object]$Candidate)

    if ($null -eq $Candidate -or "$($Candidate.status)" -ne 'recommended') {
        return $false
    }
    $reasons = @($Candidate.scoreReasons | ForEach-Object { "$_" })
    if ($reasons -contains 'vision_review_not_completed') { return $false }

    $vision = $Candidate.visionPayload
    if ($null -eq $vision) { return $true }
    if ($vision -isnot [pscustomobject] -and $vision -isnot [System.Collections.IDictionary]) {
        return $true
    }
    if ($vision.sourceObservedBoundaryAuthoritative) { return $false }

    $identityMatch = $vision.target_identity_match
    if ($null -ne $identityMatch) {
        if ($identityMatch -is [bool]) { return $identityMatch }
        switch ("$identityMatch".Trim().ToLowerInvariant()) {
            { $_ -in @('true', '1', 'yes', 'y') } { return $true }
            { $_ -in @('false', '0', 'no', 'n') } { return $false }
        }
    }

    foreach ($score in @($vision.source_score, $Candidate.visionScore)) {
        if ($null -eq $score) { continue }
        $parsedScore = 0.0
        if ([double]::TryParse(
            "$score",
            [Globalization.NumberStyles]::Float,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$parsedScore
        )) {
            return $true
        }
    }
    $fallbackType = "$($vision.deterministicSourceFallback.type)"
    return (
        $fallbackType -eq 'semantic_pose_short_demo' -or
        $reasons -contains 'semantic_pose_short_demo_source_fallback'
    )
}

function Test-HasIdentityReviewedRecommendedCandidate {
    param([string]$CandidatesPath, [object]$Payload)

    if ($null -eq $Payload -and ([string]::IsNullOrWhiteSpace($CandidatesPath) -or
        -not (Test-Path -LiteralPath $CandidatesPath))) {
        return $false
    }
    try {
        if ($null -eq $Payload) {
            $Payload = Get-Content -LiteralPath $CandidatesPath -Raw | ConvertFrom-ReconstructionJson
        }
        foreach ($exercise in @($payload.exercises)) {
            foreach ($candidate in @($exercise.candidates)) {
                if (Test-CandidateIdentityEvidenceComplete -Candidate $candidate) {
                    return $true
                }
            }
        }
    } catch {
        return $false
    }
    return $false
}

function Test-PreparedCandidatesJson {
    param(
        [string]$ExerciseSlug,
        [string]$CandidatesJsonPath,
        [string]$ExpectedVideoId
    )

    try {
        $payload = Get-Content -LiteralPath $CandidatesJsonPath -Raw | ConvertFrom-ReconstructionJson
    } catch {
        throw "Prepared candidates JSON for '$ExerciseSlug' is not valid JSON: $CandidatesJsonPath. $($_.Exception.Message)"
    }
    # Candidate rows may sit at the top level or inside the standard discovery
    # 'exercises' wrapper; either way the manifest must carry exactly one
    # identity-reviewed recommended candidate matching the expected video id.
    $candidateRows = @()
    if ($payload.PSObject.Properties.Name -contains "candidates") {
        $candidateRows = @($payload.candidates)
    } else {
        foreach ($exercise in @($payload.exercises)) {
            if ($null -ne $exercise) {
                $candidateRows += @($exercise.candidates)
            }
        }
    }
    if ($candidateRows.Count -eq 0) {
        throw "Prepared candidates JSON for '$ExerciseSlug' contains no candidates: $CandidatesJsonPath"
    }
    $recommendedRows = @($candidateRows | Where-Object { "$($_.status)" -eq "recommended" })
    if ($recommendedRows.Count -ne 1) {
        throw ("Prepared candidates JSON for '{0}' must contain exactly one recommended candidate and found {1}: {2}" -f $ExerciseSlug, $recommendedRows.Count, $CandidatesJsonPath)
    }
    if ("$($recommendedRows[0].videoId)" -ne $ExpectedVideoId) {
        throw ("Prepared candidates JSON for '{0}' recommends video id '{1}' instead of the expected '{2}': {3}" -f $ExerciseSlug, "$($recommendedRows[0].videoId)", $ExpectedVideoId, $CandidatesJsonPath)
    }
    if (-not (Test-CandidateIdentityEvidenceComplete -Candidate $recommendedRows[0])) {
        throw "Prepared recommended candidate for '$ExerciseSlug' lacks complete identity-review evidence: $CandidatesJsonPath"
    }
}

function Import-PreparedCandidatesManifest {
    param([string]$ManifestPath)

    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Prepared candidates manifest not found: $ManifestPath"
    }
    try {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-ReconstructionJson
    } catch {
        throw "Prepared candidates manifest is not valid JSON: $ManifestPath. $($_.Exception.Message)"
    }
    if ([int](Get-ObjectProperty -Object $manifest -Name "schemaVersion") -ne 1) {
        throw "Prepared candidates manifest schemaVersion must be 1: $ManifestPath"
    }
    if ("$(Get-ObjectProperty -Object $manifest -Name 'kind')" -ne "prepared_exercise_candidates") {
        throw "Prepared candidates manifest kind must be 'prepared_exercise_candidates': $ManifestPath"
    }
    $itemsBySlug = @{}
    foreach ($item in @(Get-ObjectProperty -Object $manifest -Name "items")) {
        if ($null -eq $item) {
            throw "Prepared candidates manifest contains a null item: $ManifestPath"
        }
        $exerciseId = "$(Get-ObjectProperty -Object $item -Name 'exerciseId')".Trim()
        $exerciseSlug = "$(Get-ObjectProperty -Object $item -Name 'exerciseSlug')".Trim()
        $candidatesJson = "$(Get-ObjectProperty -Object $item -Name 'candidatesJson')".Trim()
        $expectedVideoId = "$(Get-ObjectProperty -Object $item -Name 'expectedVideoId')".Trim()
        if ([string]::IsNullOrWhiteSpace($exerciseId) -or
            [string]::IsNullOrWhiteSpace($exerciseSlug) -or
            [string]::IsNullOrWhiteSpace($candidatesJson) -or
            [string]::IsNullOrWhiteSpace($expectedVideoId)) {
            throw "Prepared candidates manifest items require non-empty exerciseId, exerciseSlug, candidatesJson, and expectedVideoId: $ManifestPath"
        }
        if (-not (Test-Path -LiteralPath $candidatesJson -PathType Leaf)) {
            throw "Prepared candidates JSON not found for '$exerciseSlug': $candidatesJson"
        }
        $slugKey = ConvertTo-Slug $exerciseSlug
        if ($itemsBySlug.ContainsKey($slugKey)) {
            throw "Prepared candidates manifest contains duplicate exerciseSlug '$exerciseSlug': $ManifestPath"
        }
        Test-PreparedCandidatesJson -ExerciseSlug $exerciseSlug -CandidatesJsonPath $candidatesJson -ExpectedVideoId $expectedVideoId
        $itemsBySlug[$slugKey] = [pscustomobject]@{
            exerciseId = $exerciseId
            exerciseSlug = $exerciseSlug
            candidatesJson = (Resolve-StrictPath $candidatesJson)
            expectedVideoId = $expectedVideoId
        }
    }
    if ($itemsBySlug.Count -eq 0) {
        throw "Prepared candidates manifest contains no items: $ManifestPath"
    }
    return $itemsBySlug
}

function Test-MotionProcessingResumeReady {
    param([object]$WorkItem)

    # Incomplete controlled-motion fits already paid RECONSTRUCTION/bake. Resume bake even
    # when DisableStageResume blocks discovery/download stage reuse.
    if ([string]::IsNullOrWhiteSpace($WorkItem.exerciseCandidatesPath) -or
        -not (Test-Path -LiteralPath $WorkItem.exerciseCandidatesPath)) {
        return $false
    }
    if (Test-BakeStageReady -WorkItem $WorkItem) {
        return $false
    }
    # A retained fit is useful only if its discovery manifest can still supply
    # a candidate accepted by bake_and_rank's identity-review gate. Otherwise
    # resuming skips discovery and deterministically fails with
    # no_approved_discovery_candidates.
    if (-not (Test-HasIdentityReviewedRecommendedCandidate -CandidatesPath $WorkItem.exerciseCandidatesPath)) {
        return $false
    }
    $manifestPaths = @(
        (Join-Path $WorkItem.bakeWorkspace "selection_manifest.json"),
        (Join-Path $WorkItem.bakeWorkspace "attempt_manifests\best_no_selection_manifest.json")
    )
    foreach ($manifestPath in $manifestPaths) {
        if (Test-SelectionHasNeedsMotionProcessing -SelectionPath $manifestPath) {
            return $true
        }
    }
    $attemptDir = Join-Path $WorkItem.bakeWorkspace "attempt_manifests"
    if (Test-Path -LiteralPath $attemptDir) {
        foreach ($attemptManifest in @(Get-ChildItem -LiteralPath $attemptDir -Filter "selection_manifest.attempt-*.json" -File -ErrorAction SilentlyContinue)) {
            if (Test-SelectionHasNeedsMotionProcessing -SelectionPath $attemptManifest.FullName) {
                return $true
            }
        }
    }
    return $false
}

function Test-SourceTurnResumePresent {
    param([object]$WorkItem)

    $resumePath = Join-Path $WorkItem.bakeWorkspace "source_turn_resume.json"
    return (Test-Path -LiteralPath $resumePath)
}

function Get-BakeQueuePriority {
    param([object]$WorkItem)

    if (
        ($WorkItem.PSObject.Properties.Name -contains "preparedCandidates" -and $WorkItem.preparedCandidates) -or
        ($WorkItem.PSObject.Properties.Name -contains "motionProcessingResumed" -and $WorkItem.motionProcessingResumed) -or
        (Test-MotionProcessingResumeReady -WorkItem $WorkItem)
    ) {
        return 0
    }
    if (Test-SourceTurnResumePresent -WorkItem $WorkItem) {
        return 1
    }
    return 2
}

function Optimize-PendingBakeQueue {
    param([System.Collections.Queue]$Queue)

    if ($null -eq $Queue -or $Queue.Count -le 1) {
        return
    }
    $items = @($Queue)
    $ranked = [System.Collections.Generic.List[object]]::new()
    for ($order = 0; $order -lt $items.Count; $order += 1) {
        Exit-IfMotionRunInterrupted
        if (-not ($items[$order].PSObject.Properties.Name -contains 'PendingBakePriority')) {
            $items[$order] | Add-Member -NotePropertyName PendingBakePriority -NotePropertyValue (Get-BakeQueuePriority -WorkItem $items[$order])
        }
        $ranked.Add([pscustomobject]@{
            Item = $items[$order]
            Priority = $items[$order].PendingBakePriority
            Order = $order
        })
    }
    $sorted = @($ranked | Sort-Object Priority, Order)
    Exit-IfMotionRunInterrupted
    $Queue.Clear()
    foreach ($entry in $sorted) {
        [void]$Queue.Enqueue($entry.Item)
    }
}

function Test-SourceDownloadStageReady {
    param(
        [object]$WorkItem,
        [ValidateSet("primary", "fallback")]
        [string]$Kind
    )

    $reportPath = if ($Kind -eq "primary") {
        $WorkItem.sourceDownloadReportPath
    } else {
        $WorkItem.fallbackSourceDownloadReportPath
    }
    $argumentsSha256 = if ($Kind -eq "primary") {
        $WorkItem.primarySourceDownloadArgumentsSha256
    } else {
        $WorkItem.fallbackSourceDownloadArgumentsSha256
    }
    if (-not (Test-Path -LiteralPath $reportPath) -or -not (Test-Path -LiteralPath $WorkItem.exerciseCandidatesPath)) {
        return $false
    }
    try {
        $payload = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-ReconstructionJson
        $signature = $payload.wrapperSourceDownloadSignature
        if ($null -eq $signature -or [int]$signature.schemaVersion -ne 1) {
            return $false
        }
        if ([int]$signature.policyVersion -ne $sourceDownloadStagePolicyVersion -or "$($signature.kind)" -ne $Kind) {
            return $false
        }
        if ("$($signature.argumentsSha256)".ToLowerInvariant() -ne $argumentsSha256) {
            return $false
        }
        if ("$($signature.exercisePlanSha256)".ToLowerInvariant() -ne $WorkItem.exercisePlanSha256) {
            return $false
        }
        if ("$($signature.equipmentSha256)".ToLowerInvariant() -ne $WorkItem.equipmentSha256) {
            return $false
        }
        $candidateSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $WorkItem.exerciseCandidatesPath).Hash.ToLowerInvariant()
        if ("$($signature.candidatesSha256)".ToLowerInvariant() -ne $candidateSha256) {
            return $false
        }
        foreach ($result in @($payload.results)) {
            $artifactPath = "$($result.path)"
            if (-not [string]::IsNullOrWhiteSpace($artifactPath) -and -not (Test-Path -LiteralPath $artifactPath)) {
                return $false
            }
        }
        return $true
    } catch {
        return $false
    }
}

function Start-BakeJob {
    param(
        [object]$WorkItem,
        [bool]$UseExistingCandidatesForFirstAttempt = $true,
        [bool]$ReusePreviousTerminalResults = $false,
        [bool]$YieldAfterUnsuccessfulBake = $true
    )

    if (-not $script:AnnouncedIndividualGeneration) {
        Write-Host "Retrying remaining exercises one at a time."
        $script:AnnouncedIndividualGeneration = $true
    }
    Write-Host ("Generating: {0}" -f $WorkItem.exerciseName)
    $job = Start-Job -InitializationScript $script:ReconstructionJobInitialization -Name $WorkItem.exerciseSlug -ScriptBlock {
        param(
            [string]$PythonCommand,
            [string[]]$DiscoveryArguments,
            [string[]]$BakeArguments,
            [string]$LogPath,
            [string]$CandidatesPath,
            [string]$BakeWorkspace,
            [int]$InitialTargetSuitableCount,
            [int]$MaxTargetSuitableCount,
            [int]$BaseMaxCandidates,
            [int]$BaseVisionCandidates,
            [int]$MaxSelectedResults,
            [bool]$UseExistingCandidatesForFirstAttempt,
            [bool]$ReusePreviousTerminalResults,
            [bool]$YieldAfterUnsuccessfulBake,
            [string]$DiscoveryArgumentsSha256,
            [string]$ExercisePlanSha256,
            [string]$EquipmentSha256,
            [int]$DiscoveryStagePolicyVersion
        )

        $ErrorActionPreference = "Continue"

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

        function Get-RecommendedCandidateCount {
            param([string]$Path)
            if (-not (Test-Path -LiteralPath $Path)) {
                return 0
            }
            try {
                $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-ReconstructionJson
                $recommended = 0
                foreach ($exercise in @($payload.exercises)) {
                    foreach ($item in @($exercise.candidates)) {
                        if ("$($item.status)".ToLowerInvariant() -eq "recommended") {
                            $recommended += 1
                        }
                    }
                }
                return $recommended
            } catch {
                return 0
            }
        }

        function Get-DiscoveryTerminalReason {
            param([string]$Path)
            if (-not (Test-Path -LiteralPath $Path)) {
                return "candidate_evidence_exhausted"
            }
            try {
                $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-ReconstructionJson
                foreach ($exercise in @($payload.exercises)) {
                    $reason = "$($exercise.candidateExpansion.terminalReason)".Trim()
                    if (-not [string]::IsNullOrWhiteSpace($reason)) {
                        return $reason
                    }
                }
            } catch {
            }
            return "candidate_evidence_exhausted"
        }

        function Get-SelectedResultCount {
            param([string]$Workspace)
            $selectionPath = Join-Path $Workspace "selection_manifest.json"
            if (-not (Test-Path -LiteralPath $selectionPath)) {
                return 0
            }
            try {
                $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-ReconstructionJson
                if ($selection -and $selection.PSObject.Properties.Name -contains "selectedResults" -and $selection.selectedResults) {
                    return @($selection.selectedResults).Count
                }
                if ($selection -and $selection.selected) {
                    return 1
                }
                return 0
            } catch {
                return 0
            }
        }

        function Test-SelectionManifest {
            param([string]$Workspace)
            return (Test-Path -LiteralPath (Join-Path $Workspace "selection_manifest.json"))
        }

        function Save-AttemptCandidateSnapshot {
            param(
                [string]$Path,
                [int]$AttemptIndex
            )
            if (-not (Test-Path -LiteralPath $Path)) {
                return $null
            }
            try {
                $snapshotDir = Join-Path (Split-Path -Parent $Path) "attempt_exclusions"
                New-Item -ItemType Directory -Force -Path $snapshotDir | Out-Null
                $snapshotTimestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
                $snapshotPath = Join-Path $snapshotDir ("youtube_candidates.attempt-{0:D2}.{1}.json" -f $AttemptIndex, $snapshotTimestamp)
                Copy-Item -LiteralPath $Path -Destination $snapshotPath
                return $snapshotPath
            } catch {
                "[$(Get-Date -Format o)] failed to snapshot attempt $AttemptIndex candidates for retry exclusion: $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                return $null
            }
        }

        function Get-AttemptCandidateSnapshotPaths {
            param(
                [string]$CandidatesPath,
                [string]$DiscoveryArgumentsSha256,
                [string]$ExercisePlanSha256,
                [string]$EquipmentSha256,
                [int]$DiscoveryStagePolicyVersion
            )
            $snapshotDir = Join-Path (Split-Path -Parent $CandidatesPath) "attempt_exclusions"
            if (-not (Test-Path -LiteralPath $snapshotDir)) {
                return @()
            }
            return @(
                Get-ChildItem -LiteralPath $snapshotDir -Filter "youtube_candidates.attempt-*.json" -File |
                    Sort-Object FullName |
                    ForEach-Object {
                        try {
                            $snapshot = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-ReconstructionJson
                            $signature = $snapshot.wrapperDiscoverySignature
                            $cachedArgumentsHash = "$($signature.argumentsSha256)".ToLowerInvariant()
                            $expectedArgumentsHash = "$DiscoveryArgumentsSha256".ToLowerInvariant()
                            $cachedPlanHash = "$($signature.exercisePlanSha256)".ToLowerInvariant()
                            $expectedPlanHash = "$ExercisePlanSha256".ToLowerInvariant()
                            $cachedEquipmentHash = "$($signature.equipmentSha256)".ToLowerInvariant()
                            $expectedEquipmentHash = "$EquipmentSha256".ToLowerInvariant()
                            if (
                                $signature -and
                                [int]$signature.schemaVersion -eq 1 -and
                                [int]$signature.policyVersion -eq $DiscoveryStagePolicyVersion -and
                                $cachedArgumentsHash -eq $expectedArgumentsHash -and
                                $cachedPlanHash -eq $expectedPlanHash -and
                                $cachedEquipmentHash -eq $expectedEquipmentHash
                            ) {
                                $_.FullName
                            }
                        } catch {
                            # Unversioned or malformed snapshots must not
                            # permanently exclude candidates under a newer
                            # source-selection policy.
                        }
                    }
            )
        }

        function Get-CandidateEvidenceIdentities {
            param([string]$Path)
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
                return @()
            }
            try {
                $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-ReconstructionJson
            } catch {
                return @()
            }
            $identities = [System.Collections.Generic.HashSet[string]]::new(
                [System.StringComparer]::OrdinalIgnoreCase
            )
            foreach ($exercise in @($payload.exercises)) {
                foreach ($candidate in @($exercise.candidates)) {
                    if ($null -eq $candidate) {
                        continue
                    }
                    $identity = @(
                        $candidate.videoId,
                        $candidate.id,
                        $candidate.url,
                        $candidate.webpageUrl
                    ) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -First 1
                    if ([string]::IsNullOrWhiteSpace([string]$identity)) {
                        $serialized = $candidate | ConvertTo-Json -Depth 64 -Compress
                        $identity = [Convert]::ToHexString(
                            [System.Security.Cryptography.SHA256]::HashData(
                                [System.Text.Encoding]::UTF8.GetBytes($serialized)
                            )
                        )
                    }
                    [void]$identities.Add([string]$identity)
                }
            }
            return @($identities)
        }

        function Get-NewCandidateEvidenceCount {
            param(
                [string]$CandidatesPath,
                [string[]]$PreviousCandidateJsonPaths
            )
            $known = [System.Collections.Generic.HashSet[string]]::new(
                [System.StringComparer]::OrdinalIgnoreCase
            )
            foreach ($previousPath in @($PreviousCandidateJsonPaths | Select-Object -Unique)) {
                foreach ($identity in @(Get-CandidateEvidenceIdentities -Path $previousPath)) {
                    [void]$known.Add([string]$identity)
                }
            }
            $newCount = 0
            foreach ($identity in @(Get-CandidateEvidenceIdentities -Path $CandidatesPath)) {
                if ($known.Add([string]$identity)) {
                    $newCount += 1
                }
            }
            return $newCount
        }

        function Save-AttemptSelectionManifest {
            param(
                [string]$Workspace,
                [int]$AttemptIndex
            )
            $selectionPath = Join-Path $Workspace "selection_manifest.json"
            if (-not (Test-Path -LiteralPath $selectionPath)) {
                return $null
            }
            try {
                $snapshotDir = Join-Path $Workspace "attempt_manifests"
                New-Item -ItemType Directory -Force -Path $snapshotDir | Out-Null
                $snapshotTimestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
                $snapshotPath = Join-Path $snapshotDir ("selection_manifest.attempt-{0:D2}.{1}.json" -f $AttemptIndex, $snapshotTimestamp)
                Copy-Item -LiteralPath $selectionPath -Destination $snapshotPath
                return $snapshotPath
            } catch {
                "[$(Get-Date -Format o)] failed to snapshot selection manifest for attempt $AttemptIndex`: $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                return $null
            }
        }

        function Get-SelectionManifestEvidenceScore {
            param([string]$Path)
            if (-not (Test-Path -LiteralPath $Path)) {
                return -1.0
            }
            try {
                $selection = Get-Content -LiteralPath $Path -Raw | ConvertFrom-ReconstructionJson
                $score = [double]@($selection.candidateResults).Count
                $score += 1000.0 * [double]@($selection.reviewItems).Count
                if ($selection.rejectedBest) {
                    $score += 1000000.0
                    $rejectedBestScore = $selection.rejectedBest.selectionScore
                    if ($null -ne $rejectedBestScore) {
                        $score += [double]$rejectedBestScore
                    }
                }
                return $score
            } catch {
                return -1.0
            }
        }

        function Preserve-BestNoSelectionManifest {
            param([string]$SnapshotPath)
            if ([string]::IsNullOrWhiteSpace($SnapshotPath) -or -not (Test-Path -LiteralPath $SnapshotPath)) {
                return
            }
            $bestPath = Join-Path $BakeWorkspace "attempt_manifests\best_no_selection_manifest.json"
            $snapshotScore = Get-SelectionManifestEvidenceScore -Path $SnapshotPath
            $bestScore = Get-SelectionManifestEvidenceScore -Path $bestPath
            if ($snapshotScore -gt $bestScore) {
                Copy-Item -LiteralPath $SnapshotPath -Destination $bestPath -Force
            }
        }

        function Restore-BestNoSelectionManifest {
            $bestPath = Join-Path $BakeWorkspace "attempt_manifests\best_no_selection_manifest.json"
            if (Test-Path -LiteralPath $bestPath) {
                Copy-Item -LiteralPath $bestPath -Destination (Join-Path $BakeWorkspace "selection_manifest.json") -Force
            }
        }

        function Write-DiscoveryCompletionSignature {
            param([string]$Path)

            if (-not (Test-Path -LiteralPath $Path)) {
                return $false
            }
            try {
                $candidatePayload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-ReconstructionJson
                $candidatePayload | Add-Member -NotePropertyName wrapperDiscoverySignature -NotePropertyValue ([pscustomobject]@{
                    schemaVersion = 1
                    policyVersion = $DiscoveryStagePolicyVersion
                    completedAt = (Get-Date).ToUniversalTime().ToString("o")
                    argumentsSha256 = $DiscoveryArgumentsSha256
                    exercisePlanSha256 = $ExercisePlanSha256
                    equipmentSha256 = if ([string]::IsNullOrWhiteSpace($EquipmentSha256)) { $null } else { $EquipmentSha256 }
                }) -Force
                $temporaryCandidatesPath = "$Path.tmp"
                $candidatePayload | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $temporaryCandidatesPath -Encoding UTF8
                Move-Item -Force -LiteralPath $temporaryCandidatesPath -Destination $Path
                return $true
            } catch {
                "[$(Get-Date -Format o)] discovery completion signature write failed: $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                return $false
            }
        }

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
        if (Test-Path -LiteralPath $LogPath) {
            "[$(Get-Date -Format o)] bake stage started" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        } else {
            "[$(Get-Date -Format o)] movement generation started" | Set-Content -LiteralPath $LogPath -Encoding UTF8
            "[$(Get-Date -Format o)] bake stage started" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        }
        # Begin at the requested initial review target. Starting at the maximum
        # makes a zero-recommendation discovery look as though every retry has
        # already been consumed, so the exercise is never rediscovered.
        $targetSuitableCount = [Math]::Max(1, $InitialTargetSuitableCount)
        $hasTargetLimit = $MaxTargetSuitableCount -gt 0
        $targetLimitLabel = if ($hasTargetLimit) { "$MaxTargetSuitableCount" } else { "evidence-exhaustion" }
        $attemptIndex = 1
        $previousAttemptCandidateJsonPaths = @(
            Get-AttemptCandidateSnapshotPaths `
                -CandidatesPath $CandidatesPath `
                -DiscoveryArgumentsSha256 $DiscoveryArgumentsSha256 `
                -ExercisePlanSha256 $ExercisePlanSha256 `
                -EquipmentSha256 $EquipmentSha256 `
                -DiscoveryStagePolicyVersion $DiscoveryStagePolicyVersion
        )
        $useExistingCandidates = $UseExistingCandidatesForFirstAttempt -and (Test-Path -LiteralPath $CandidatesPath)
        $discoverySecondsTotal = 0.0
        $bakeSecondsTotal = 0.0
        $discoveryAttemptCount = 0
        $bakeAttemptCount = 0
        $maxTransientServerAttempts = 3
        $transientBakeFailureCount = 0
        $attempts = @()
        while ($true) {
            if ($useExistingCandidates) {
                "[$(Get-Date -Format o)] using pre-discovered candidates for attempt $attemptIndex" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                $recommendedCount = Get-RecommendedCandidateCount -Path $CandidatesPath
                if (Test-Path -LiteralPath $CandidatesPath) {
                    $attemptCandidateSnapshotPath = Save-AttemptCandidateSnapshot -Path $CandidatesPath -AttemptIndex $attemptIndex
                    if (-not [string]::IsNullOrWhiteSpace($attemptCandidateSnapshotPath)) {
                        $previousAttemptCandidateJsonPaths += $attemptCandidateSnapshotPath
                    }
                }
                $attempts += [ordered]@{
                    attemptIndex = $attemptIndex
                    stage = "pre_discovered_candidates"
                    exitCode = 0
                    targetSuitableCount = $targetSuitableCount
                    recommendedCount = $recommendedCount
                    elapsedSeconds = 0.0
                }
                $useExistingCandidates = $false
            } else {
                $cumulativeCandidateBudget = if ($hasTargetLimit) {
                    $BaseMaxCandidates * $MaxTargetSuitableCount
                } else {
                    $BaseMaxCandidates
                }
                $attemptMaxCandidates = [Math]::Max($cumulativeCandidateBudget, $targetSuitableCount)
                $attemptVisionCandidates = [Math]::Max($BaseVisionCandidates, $targetSuitableCount)
                $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $DiscoveryArguments -Name "--candidate-review-target-suitable-count" -Value "$targetSuitableCount"
                $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--max-candidates" -Value "$attemptMaxCandidates"
                $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--vision-candidates-per-exercise" -Value "$attemptVisionCandidates"
                foreach ($previousAttemptCandidateJsonPath in @($previousAttemptCandidateJsonPaths | Select-Object -Unique)) {
                    if (Test-Path -LiteralPath $previousAttemptCandidateJsonPath) {
                        $attemptDiscoveryArgs += @("--exclude-youtube-candidates-json", $previousAttemptCandidateJsonPath)
                    }
                }

                for ($serverAttempt = 1; $serverAttempt -le $maxTransientServerAttempts; $serverAttempt += 1) {
                    "[$(Get-Date -Format o)] discovery attempt $attemptIndex started; target suitable candidates $targetSuitableCount/$targetLimitLabel (server attempt $serverAttempt/$maxTransientServerAttempts)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                    $discoveryStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
                    & $PythonCommand @attemptDiscoveryArgs *>> $LogPath
                    $discoveryExitCode = $LASTEXITCODE
                    if ($discoveryExitCode -eq 0 -and -not (Write-DiscoveryCompletionSignature -Path $CandidatesPath)) {
                        $discoveryExitCode = 1
                    }
                    $discoveryStopwatch.Stop()
                    $discoverySeconds = [Math]::Round($discoveryStopwatch.Elapsed.TotalSeconds, 3)
                    $discoverySecondsTotal = [Math]::Round(($discoverySecondsTotal + $discoverySeconds), 3)
                    $discoveryAttemptCount += 1
                    $recommendedCount = Get-RecommendedCandidateCount -Path $CandidatesPath
                    "[$(Get-Date -Format o)] discovery attempt $attemptIndex finished with exit code $discoveryExitCode; recommended $recommendedCount, elapsed ${discoverySeconds}s (server attempt $serverAttempt/$maxTransientServerAttempts)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                    $attempts += [ordered]@{
                        attemptIndex = $attemptIndex
                        stage = "discovery"
                        serverAttempt = $serverAttempt
                        exitCode = $discoveryExitCode
                        targetSuitableCount = $targetSuitableCount
                        recommendedCount = $recommendedCount
                        elapsedSeconds = $discoverySeconds
                    }
                    if ($discoveryExitCode -eq 0) {
                        break
                    }
                    $logTail = (Get-Content -LiteralPath $LogPath -Tail 100 -ErrorAction SilentlyContinue) -join "`n"
                    $isTransientServerStartupFailure = $logTail -match "llama-server did not become healthy"
                    if (-not $isTransientServerStartupFailure -or $serverAttempt -ge $maxTransientServerAttempts) {
                        break
                    }
                    "[$(Get-Date -Format o)] retrying discovery after transient llama-server startup failure" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                    Start-Sleep -Seconds 5
                }
                if ($discoveryExitCode -ne 0) {
                    [pscustomobject]@{
                        exitCode = $discoveryExitCode
                        stage = "discovery"
                        logPath = $LogPath
                        discoverySeconds = $discoverySecondsTotal
                        bakeSeconds = $bakeSecondsTotal
                        discoveryAttemptCount = $discoveryAttemptCount
                        bakeAttemptCount = $bakeAttemptCount
                        attempts = $attempts
                    }
                    return
                }

                if ($previousAttemptCandidateJsonPaths.Count -gt 0) {
                    $newCandidateEvidenceCount = Get-NewCandidateEvidenceCount `
                        -CandidatesPath $CandidatesPath `
                        -PreviousCandidateJsonPaths $previousAttemptCandidateJsonPaths
                    if ($newCandidateEvidenceCount -eq 0) {
                        "[$(Get-Date -Format o)] discovery returned no new candidate identities; stopping after evidence exhaustion" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                        Restore-BestNoSelectionManifest
                        $restoredSelectionPath = Join-Path $BakeWorkspace "selection_manifest.json"
                        $restoredSelection = if (Test-Path -LiteralPath $restoredSelectionPath) {
                            Get-Content -LiteralPath $restoredSelectionPath -Raw | ConvertFrom-ReconstructionJson
                        } else {
                            $null
                        }
                        $terminalReason = if ($restoredSelection -and $restoredSelection.manualReviewFallback) {
                            $null
                        } else {
                            "no_new_candidate_identities"
                        }
                        [pscustomobject]@{
                            exitCode = 0
                            stage = "discovery_evidence_exhausted"
                            logPath = $LogPath
                            discoverySeconds = $discoverySecondsTotal
                            bakeSeconds = $bakeSecondsTotal
                            discoveryAttemptCount = $discoveryAttemptCount
                            bakeAttemptCount = $bakeAttemptCount
                            noNewWork = $true
                            terminalReason = $terminalReason
                            attempts = $attempts
                        }
                        return
                    }
                }

                if (Test-Path -LiteralPath $CandidatesPath) {
                    $attemptCandidateSnapshotPath = Save-AttemptCandidateSnapshot -Path $CandidatesPath -AttemptIndex $attemptIndex
                    if (-not [string]::IsNullOrWhiteSpace($attemptCandidateSnapshotPath)) {
                        $previousAttemptCandidateJsonPaths += $attemptCandidateSnapshotPath
                    }
                }
            }
            if ($recommendedCount -le 0) {
                if (-not $hasTargetLimit -or $targetSuitableCount -ge $MaxTargetSuitableCount) {
                    Restore-BestNoSelectionManifest
                    [pscustomobject]@{
                        exitCode = 0
                        stage = "discovery_no_recommended"
                        logPath = $LogPath
                        discoverySeconds = $discoverySecondsTotal
                        bakeSeconds = $bakeSecondsTotal
                        discoveryAttemptCount = $discoveryAttemptCount
                        bakeAttemptCount = $bakeAttemptCount
                        noNewWork = $true
                        terminalReason = Get-DiscoveryTerminalReason -Path $CandidatesPath
                        attempts = $attempts
                    }
                    return
                }
                $targetSuitableCount = [Math]::Min($MaxTargetSuitableCount, $targetSuitableCount + 1)
                $attemptIndex += 1
                "[$(Get-Date -Format o)] no recommended candidates; expanding review target to $targetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                continue
            }

            "[$(Get-Date -Format o)] bake attempt $attemptIndex started with $recommendedCount recommended candidate(s)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            $bakeStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            $attemptBakeArguments = @($BakeArguments)
            if ($bakeAttemptCount -gt 0 -or $ReusePreviousTerminalResults) {
                $attemptBakeArguments += "--reuse-previous-terminal-results"
            }
            $previousReconstructionLazyStart = $env:EXERCISE_MOTION_RECONSTRUCTION_LAZY_START
            $previousGvhmrLazyStart = $env:EXERCISE_MOTION_GVHMR_LAZY_START
            try {
                # The legacy retry runs outside the staged service process. Let
                # its warm-worker client request a supervised restart when a
                # prior GPU handoff stopped the worker. Python publishes that
                # request only after acquiring the shared GPU and Docker locks.
                if ($attemptBakeArguments -contains "--warm-reconstruction-worker") {
                    $env:EXERCISE_MOTION_RECONSTRUCTION_LAZY_START = "1"
                }
                if ($attemptBakeArguments -contains "--warm-gvhmr-worker") {
                    $env:EXERCISE_MOTION_GVHMR_LAZY_START = "1"
                }
                & $PythonCommand @attemptBakeArguments *>> $LogPath
                $bakeExitCode = $LASTEXITCODE
            }
            finally {
                if ($null -eq $previousReconstructionLazyStart) { Remove-Item Env:EXERCISE_MOTION_RECONSTRUCTION_LAZY_START -ErrorAction SilentlyContinue }
                else { $env:EXERCISE_MOTION_RECONSTRUCTION_LAZY_START = $previousReconstructionLazyStart }
                if ($null -eq $previousGvhmrLazyStart) { Remove-Item Env:EXERCISE_MOTION_GVHMR_LAZY_START -ErrorAction SilentlyContinue }
                else { $env:EXERCISE_MOTION_GVHMR_LAZY_START = $previousGvhmrLazyStart }
            }
            if ($bakeExitCode -eq 75) {
                [pscustomobject]@{ exitCode = 75; stage = "storage"; logPath = $LogPath }
                return
            }
            $bakeStopwatch.Stop()
            $bakeSeconds = [Math]::Round($bakeStopwatch.Elapsed.TotalSeconds, 3)
            $bakeSecondsTotal = [Math]::Round(($bakeSecondsTotal + $bakeSeconds), 3)
            $bakeAttemptCount += 1

            $selectedResultCount = Get-SelectedResultCount -Workspace $BakeWorkspace
            $attemptSelectionSnapshotPath = Save-AttemptSelectionManifest -Workspace $BakeWorkspace -AttemptIndex $attemptIndex
            if ($selectedResultCount -eq 0 -and $attemptSelectionSnapshotPath) {
                $attemptSelection = Get-Content -LiteralPath $attemptSelectionSnapshotPath -Raw | ConvertFrom-ReconstructionJson
                if (@($attemptSelection.candidateResults | Where-Object { $_.status -eq 'needs_motion_processing' }).Count -gt 0) {
                    [pscustomobject]@{
                        exitCode = 0
                        stage = "motion_processing"
                        processingIncomplete = $true
                        logPath = $LogPath
                        selectedResultCount = 0
                        discoverySeconds = $discoverySecondsTotal
                        bakeSeconds = $bakeSecondsTotal
                        discoveryAttemptCount = $discoveryAttemptCount
                        bakeAttemptCount = $bakeAttemptCount
                        attempts = $attempts
                    }
                    return
                }
            }
            if ($selectedResultCount -eq 0) {
                Preserve-BestNoSelectionManifest -SnapshotPath $attemptSelectionSnapshotPath
            }
            "[$(Get-Date -Format o)] bake attempt $attemptIndex finished with exit code $bakeExitCode; selected $selectedResultCount/$MaxSelectedResults result(s), elapsed ${bakeSeconds}s" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            $attempts += [ordered]@{
                attemptIndex = $attemptIndex
                stage = "bake"
                exitCode = $bakeExitCode
                targetSuitableCount = $targetSuitableCount
                recommendedCount = $recommendedCount
                selectedResultCount = $selectedResultCount
                elapsedSeconds = $bakeSeconds
            }
            if ($selectedResultCount -gt 0) {
                if ($selectedResultCount -lt $MaxSelectedResults -and (-not $hasTargetLimit -or $targetSuitableCount -lt $MaxTargetSuitableCount)) {
                    if ($hasTargetLimit) {
                        $targetSuitableCount = [Math]::Min($MaxTargetSuitableCount, $targetSuitableCount + 1)
                    }
                    $attemptIndex += 1
                    "[$(Get-Date -Format o)] selected $selectedResultCount/$MaxSelectedResults result(s); expanding review target to $targetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                    continue
                }
                [pscustomobject]@{
                    exitCode = 0
                    stage = "bake"
                    logPath = $LogPath
                    selectedResultCount = $selectedResultCount
                    discoverySeconds = $discoverySecondsTotal
                    bakeSeconds = $bakeSecondsTotal
                    discoveryAttemptCount = $discoveryAttemptCount
                    bakeAttemptCount = $bakeAttemptCount
                    attempts = $attempts
                }
                return
            }
            if ($bakeExitCode -ne 0 -and -not (Test-SelectionManifest -Workspace $BakeWorkspace)) {
                $logTail = (Get-Content -LiteralPath $LogPath -Tail 100 -ErrorAction SilentlyContinue) -join "`n"
                $isTransientServerStartupFailure = $logTail -match "llama-server did not become healthy"
                if ($isTransientServerStartupFailure -and $transientBakeFailureCount -lt ($maxTransientServerAttempts - 1)) {
                    $transientBakeFailureCount += 1
                    "[$(Get-Date -Format o)] retrying bake after transient llama-server startup failure" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                    Start-Sleep -Seconds 5
                    continue
                }
                [pscustomobject]@{
                    # A transient later attempt must not erase a useful
                    # no-selection diagnosis produced by an earlier bake.
                    exitCode = $bakeExitCode
                    stage = "bake"
                    logPath = $LogPath
                    selectedResultCount = $selectedResultCount
                    discoverySeconds = $discoverySecondsTotal
                    bakeSeconds = $bakeSecondsTotal
                    discoveryAttemptCount = $discoveryAttemptCount
                    bakeAttemptCount = $bakeAttemptCount
                    attempts = $attempts
                }
                Restore-BestNoSelectionManifest
                return
            }
            if ($bakeExitCode -ne 0) {
                "[$(Get-Date -Format o)] bake returned exit code $bakeExitCode after writing a no-selection manifest; expanding review target if possible" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            }

            if ($YieldAfterUnsuccessfulBake) {
                Restore-BestNoSelectionManifest
                [pscustomobject]@{
                    exitCode = 0
                    stage = "bake_round_robin_yield"
                    logPath = $LogPath
                    selectedResultCount = 0
                    discoverySeconds = $discoverySecondsTotal
                    bakeSeconds = $bakeSecondsTotal
                    discoveryAttemptCount = $discoveryAttemptCount
                    bakeAttemptCount = $bakeAttemptCount
                    attempts = $attempts
                    retryPending = $true
                }
                return
            }

            if ($hasTargetLimit -and $targetSuitableCount -ge $MaxTargetSuitableCount) {
                Restore-BestNoSelectionManifest
                [pscustomobject]@{
                    exitCode = 0
                    stage = "bake_no_selection"
                    logPath = $LogPath
                    selectedResultCount = $selectedResultCount
                    discoverySeconds = $discoverySecondsTotal
                    bakeSeconds = $bakeSecondsTotal
                    discoveryAttemptCount = $discoveryAttemptCount
                    bakeAttemptCount = $bakeAttemptCount
                    attempts = $attempts
                }
                return
            }

            if ($hasTargetLimit) {
                $targetSuitableCount = [Math]::Min($MaxTargetSuitableCount, $targetSuitableCount + 1)
            }
            $attemptIndex += 1
            "[$(Get-Date -Format o)] no selected Wear skeleton; expanding review target to $targetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        }
    } -ArgumentList $PythonCommand, ([string[]]$WorkItem.discoveryArgs), ([string[]]$WorkItem.bakeArgs), $WorkItem.logPath, $WorkItem.exerciseCandidatesPath, $WorkItem.bakeWorkspace, $WorkItem.candidateReviewTargetSuitableCount, $WorkItem.maxCandidateReviewTargetSuitableCount, $WorkItem.maxCandidates, $WorkItem.visionCandidatesPerExercise, $WorkItem.maxSelectedResults, $UseExistingCandidatesForFirstAttempt, $ReusePreviousTerminalResults, $YieldAfterUnsuccessfulBake, $WorkItem.discoveryArgumentsSha256, $WorkItem.exercisePlanSha256, $WorkItem.equipmentSha256, $discoveryStagePolicyVersion
    $job | Add-Member -MemberType NoteProperty -Name WorkItem -Value $WorkItem
    return $job
}

function ConvertTo-StagedServiceArgument {
    param([AllowEmptyString()][string]$Value)

    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append([char]34)
    $backslashCount = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]92) {
            $backslashCount += 1
            continue
        }
        if ($character -eq [char]34) {
            [void]$builder.Append(([string]([char]92) * (2 * $backslashCount + 1)))
            [void]$builder.Append([char]34)
            $backslashCount = 0
            continue
        }
        if ($backslashCount -gt 0) {
            [void]$builder.Append(([string]([char]92) * $backslashCount))
            $backslashCount = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashCount -gt 0) {
        [void]$builder.Append(([string]([char]92) * (2 * $backslashCount)))
    }
    [void]$builder.Append([char]34)
    return $builder.ToString()
}

function Get-StagedBakeQueueServiceState {
    param([string]$QueueRoot)

    $statePath = Join-Path $QueueRoot "worker_state.json"
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return [pscustomobject]@{
            healthy = $false
            processState = "unknown"
            matchingProcess = $false
            state = $null
            process = $null
        }
    }
    try {
        $workerState = Get-Content -LiteralPath $statePath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ([int]$workerState.schemaVersion -ne 1 -or
            -not [string]::Equals([string]$workerState.queueRoot, $QueueRoot, [StringComparison]::OrdinalIgnoreCase)) {
            return [pscustomobject]@{
                healthy = $false
                processState = "unknown"
                matchingProcess = $false
                state = $workerState
                process = $null
            }
        }
        $workerPid = 0
        try { $workerPid = [int]$workerState.pid } catch {}
        if ($workerPid -le 0) {
            return [pscustomobject]@{
                healthy = $false
                processState = "unknown"
                matchingProcess = $false
                state = $workerState
                process = $null
            }
        }
        $workerProcess = Get-Process -Id $workerPid -ErrorAction SilentlyContinue
        if ($null -eq $workerProcess) {
            return [pscustomobject]@{
                healthy = $false
                processState = "stopped"
                matchingProcess = $false
                state = $workerState
                process = $null
            }
        }
        $expectedIdentity = 0L
        try { $expectedIdentity = [int64]$workerState.processIdentity } catch {}
        if ($expectedIdentity -le 0) {
            return [pscustomobject]@{
                healthy = $false
                processState = "unknown"
                matchingProcess = $false
                state = $workerState
                process = $workerProcess
            }
        }
        try {
            $actualIdentity = [int64]$workerProcess.StartTime.ToUniversalTime().ToFileTimeUtc()
            if ($actualIdentity -ne $expectedIdentity -or $workerProcess.HasExited) {
                return [pscustomobject]@{
                    healthy = $false
                    processState = "stopped"
                    matchingProcess = $false
                    state = $workerState
                    process = $workerProcess
                }
            }
        } catch {
            return [pscustomobject]@{
                healthy = $false
                processState = "unknown"
                matchingProcess = $false
                state = $workerState
                process = $workerProcess
            }
        }
        $heartbeatAge = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0 - [double]$workerState.updatedAtEpoch
        $healthy = (
            [string]$workerState.status -in @("idle", "running") -and
            $heartbeatAge -ge -5 -and $heartbeatAge -lt 20
        )
        return [pscustomobject]@{
            healthy = $healthy
            processState = "running"
            matchingProcess = $true
            state = $workerState
            process = $workerProcess
        }
    } catch {
        return [pscustomobject]@{
            healthy = $false
            processState = "unknown"
            matchingProcess = $false
            state = $null
            process = $null
        }
    }
}

function Get-StagedBakeServiceConfigurationFingerprint {
    param(
        [string]$ConfiguredPythonCommand,
        [int]$MaxWaveItems
    )

    $resolvedPythonCommand = $ConfiguredPythonCommand
    try {
        $command = Get-Command -Name $ConfiguredPythonCommand -ErrorAction Stop | Select-Object -First 1
        if (-not [string]::IsNullOrWhiteSpace([string]$command.Source)) {
            $resolvedPythonCommand = [string]$command.Source
        }
    } catch {
    }
    $serviceEnvironment = [ordered]@{}
    Get-ChildItem Env: | Where-Object { $_.Name -like "EXERCISE_MOTION_*" } | Sort-Object Name | ForEach-Object {
        $serviceEnvironment[[string]$_.Name] = [string]$_.Value
    }
    # The service always enables lazy warm-worker startup, regardless of the
    # caller's ambient values. Fingerprint the effective values it receives.
    $serviceEnvironment["EXERCISE_MOTION_RECONSTRUCTION_LAZY_START"] = "1"
    $serviceEnvironment["EXERCISE_MOTION_GVHMR_LAZY_START"] = "1"
    $payload = [ordered]@{
        pythonCommand = $resolvedPythonCommand
        maxWaveItems = [int]$MaxWaveItems
        environment = $serviceEnvironment
    }
    $json = $payload | ConvertTo-Json -Depth 16 -Compress
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        return (($hasher.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally {
        $hasher.Dispose()
    }
}

function Get-StagedWaveAdmissionMutexNames {
    param(
        [string]$QueueRoot,
        [switch]$IncludeLegacyCompatibility
    )

    $legacyName = "Global\MyWorkoutAssistant.StagedWaveAdmission.v1"
    $statePath = Join-Path $QueueRoot "worker_state.json"
    $lockVersion = 2
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw -ErrorAction Stop |
                ConvertFrom-ReconstructionJson -ErrorAction Stop
            if ([int]$state.admissionLockVersion -ne 2) {
                $lockVersion = 1
            }
        } catch {
            # Keep unidentified existing workers on the legacy lock protocol.
            $lockVersion = 1
        }
    }
    if ($lockVersion -eq 1) {
        return @($legacyName)
    }

    $fullQueueRoot = [System.IO.Path]::GetFullPath($QueueRoot)
    $rootPath = [System.IO.Path]::GetPathRoot($fullQueueRoot)
    if ($fullQueueRoot.Length -gt $rootPath.Length) {
        $fullQueueRoot = $fullQueueRoot.TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
    }
    $normalizedQueueRoot = $fullQueueRoot.ToUpperInvariant()
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($normalizedQueueRoot)
        $digest = ($hasher.ComputeHash($bytes) | ForEach-Object {
            $_.ToString("x2")
        }) -join ""
    } finally {
        $hasher.Dispose()
    }
    $queueMutexName = "Global\MyWorkoutAssistant.StagedWaveAdmission.v2.$digest"
    if ($IncludeLegacyCompatibility) {
        return @($legacyName, $queueMutexName)
    }
    return @($queueMutexName)
}

function Invoke-WithStagedWaveAdmissionLock {
    param(
        [string]$QueueRoot,
        [scriptblock]$Operation,
        [switch]$IncludeLegacyCompatibility
    )

    $mutexNames = Get-StagedWaveAdmissionMutexNames `
        -QueueRoot $QueueRoot `
        -IncludeLegacyCompatibility:$IncludeLegacyCompatibility
    $mutexes = [System.Collections.Generic.List[object]]::new()
    $owned = [System.Collections.Generic.List[bool]]::new()
    try {
        foreach ($mutexName in $mutexNames) {
            # Named OS mutexes are released automatically if either process exits.
            $mutex = [System.Threading.Mutex]::new($false, [string]$mutexName)
            [void]$mutexes.Add($mutex)
            [void]$owned.Add($false)
            try {
                $ownsMutex = $mutex.WaitOne([TimeSpan]::FromSeconds(30))
            } catch [System.Threading.AbandonedMutexException] {
                $ownsMutex = $true
            }
            if (-not $ownsMutex) {
                throw "Timed out waiting for staged-wave admission lock for '$QueueRoot'."
            }
            $owned[$owned.Count - 1] = $true
        }
        return & $Operation
    } finally {
        for ($index = $mutexes.Count - 1; $index -ge 0; $index--) {
            if ($owned[$index]) {
                $mutexes[$index].ReleaseMutex()
            }
            $mutexes[$index].Dispose()
        }
    }
}

function Start-StagedBakeQueueServiceGeneration {
    param(
        [string]$QueueRoot,
        [string]$PythonCommand,
        [int]$MaxWaveItems,
        [string]$SourceIdentityFingerprint,
        [string]$ConfigurationFingerprint,
        [string]$RepositoryRoot
    )

    $serviceLogPath = Join-Path $QueueRoot "service.log"
    $serviceErrorPath = Join-Path $QueueRoot "service.error.log"
    $serviceArguments = @(
        "-m", "exercise_motion_pkg.staged_wave_service",
        "--queue-root", $QueueRoot,
        "--max-wave-items", [string]$MaxWaveItems,
        "--source-identity-fingerprint", $SourceIdentityFingerprint,
        "--service-configuration-fingerprint", $ConfigurationFingerprint,
        "--idle-timeout-seconds", "600"
    )

    return Invoke-WithStagedWaveAdmissionLock -QueueRoot $QueueRoot -Operation {
        $serviceBeforeLaunch = Get-StagedBakeQueueServiceState -QueueRoot $QueueRoot
        if ($serviceBeforeLaunch.healthy) {
            $sourceIdentityMatches = [string]$serviceBeforeLaunch.state.sourceIdentityFingerprint -eq $SourceIdentityFingerprint
            $configurationMatches = [string]$serviceBeforeLaunch.state.serviceConfigurationFingerprint -eq $ConfigurationFingerprint
            if ($sourceIdentityMatches -and $configurationMatches) {
                return [pscustomobject]@{
                    launched = $false
                    process = $serviceBeforeLaunch.process
                }
            }
            throw "A live staged-wave service changed before replacement; refusing to start a duplicate worker."
        }
        if ($serviceBeforeLaunch.matchingProcess) {
            throw "Staged-wave service process $($serviceBeforeLaunch.state.pid) is still alive before replacement; refusing to start a duplicate worker."
        }

        $pythonExtension = [System.IO.Path]::GetExtension($PythonCommand).ToLowerInvariant()
        $commandArguments = @($serviceArguments | ForEach-Object { ConvertTo-StagedServiceArgument -Value ([string]$_) }) -join " "
        if ($pythonExtension -in @(".cmd", ".bat")) {
            $commandLine = '"{0}" {1}' -f $PythonCommand, $commandArguments
            $startArgument = '/d /s /c "{0}"' -f $commandLine
            $startFilePath = $env:ComSpec
            $startArguments = $startArgument
        } else {
            $startFilePath = $PythonCommand
            $startArguments = $commandArguments
        }

        $previousReconstructionLazyStart = $env:EXERCISE_MOTION_RECONSTRUCTION_LAZY_START
        $previousGvhmrLazyStart = $env:EXERCISE_MOTION_GVHMR_LAZY_START
        $env:EXERCISE_MOTION_RECONSTRUCTION_LAZY_START = "1"
        $env:EXERCISE_MOTION_GVHMR_LAZY_START = "1"
        try {
            $stopRequestPath = Join-Path $QueueRoot "stop.request"
            if (Test-Path -LiteralPath $stopRequestPath -PathType Leaf) {
                if ($serviceBeforeLaunch.processState -ne "stopped") {
                    throw "Cannot clear staged-wave stop.request because the previous worker's exit is not confirmed."
                }
                Remove-Item -LiteralPath $stopRequestPath -Force -ErrorAction Stop
            }

            $process = Start-Process `
                -FilePath $startFilePath `
                -ArgumentList $startArguments `
                -WorkingDirectory $RepositoryRoot `
                -WindowStyle Hidden `
                -RedirectStandardOutput $serviceLogPath `
                -RedirectStandardError $serviceErrorPath `
                -PassThru `
                -ErrorAction Stop
        } finally {
            if ($null -eq $previousReconstructionLazyStart) { Remove-Item Env:EXERCISE_MOTION_RECONSTRUCTION_LAZY_START -ErrorAction SilentlyContinue }
            else { $env:EXERCISE_MOTION_RECONSTRUCTION_LAZY_START = $previousReconstructionLazyStart }
            if ($null -eq $previousGvhmrLazyStart) { Remove-Item Env:EXERCISE_MOTION_GVHMR_LAZY_START -ErrorAction SilentlyContinue }
            else { $env:EXERCISE_MOTION_GVHMR_LAZY_START = $previousGvhmrLazyStart }
        }

        $startupDeadline = [DateTimeOffset]::UtcNow.AddSeconds(20)
        do {
            Start-Sleep -Milliseconds 200
            $startedService = Get-StagedBakeQueueServiceState -QueueRoot $QueueRoot
            if ($startedService.healthy) {
                return [pscustomobject]@{
                    launched = $true
                    process = $process
                }
            }
            if ($process.HasExited) {
                break
            }
        } while ([DateTimeOffset]::UtcNow -lt $startupDeadline)
        $errorTail = if (Test-Path -LiteralPath $serviceErrorPath) {
            (Get-Content -LiteralPath $serviceErrorPath -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        } else { "" }
        throw "Staged-wave service failed to publish a valid PID, process-start identity, and heartbeat. Process=$($process.Id). $errorTail"
    }
}

function Ensure-StagedBakeQueueService {
    param([int]$MaxWaveItems)

    $queueRoot = $script:StagedWaveServiceQueueRoot
    $configurationFingerprint = Get-StagedBakeServiceConfigurationFingerprint `
        -ConfiguredPythonCommand $PythonCommand `
        -MaxWaveItems $MaxWaveItems
    foreach ($directoryName in @("requests", "processing", "results", "ambiguous", "cancelled_runs")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $queueRoot $directoryName) | Out-Null
    }
    $existingService = Get-StagedBakeQueueServiceState -QueueRoot $queueRoot
    if ($existingService.matchingProcess -and [string]$existingService.state.status -eq "stopping") {
        # Idle shutdown closes admission while holding the same mutex used by
        # producers. Wait for that generation to exit, then start a fresh one.
        $existingService.process.WaitForExit(20000)
        $existingService = Get-StagedBakeQueueServiceState -QueueRoot $queueRoot
        if ($existingService.matchingProcess) {
            throw "Staged-wave service process $($existingService.state.pid) is still stopping; refusing to enqueue until its generation exits."
        }
    }
    if ($existingService.healthy) {
        $sourceIdentityMatches = [string]$existingService.state.sourceIdentityFingerprint -eq $script:MotionSourceIdentityFingerprint
        $configurationMatches = [string]$existingService.state.serviceConfigurationFingerprint -eq $configurationFingerprint
        if ($sourceIdentityMatches -and $configurationMatches) {
            return
        }
        $changedIdentity = if (-not $sourceIdentityMatches) { "source identity" } else { "runtime configuration" }
        if ([string]$existingService.state.status -ne "idle") {
            throw "Staged-wave service process $($existingService.state.pid) is still using a different $changedIdentity; refusing to submit work to stale code or settings. Retry after that wave stops."
        }
        $pendingRequests = @(
            Get-ChildItem -LiteralPath (Join-Path $queueRoot "requests") -Filter "*.json" -File -ErrorAction SilentlyContinue
        )
        $processingRequests = @(
            Get-ChildItem -LiteralPath (Join-Path $queueRoot "processing") -Filter "*.json" -File -ErrorAction SilentlyContinue
        )
        if ($pendingRequests.Count -gt 0 -or $processingRequests.Count -gt 0) {
            throw "Staged-wave service $changedIdentity changed while old requests remain queued; refusing to reuse or replace that worker until its queue drains."
        }
        $stopRequestPath = Join-Path $queueRoot "stop.request"
        "$changedIdentity changed" | Set-Content -LiteralPath $stopRequestPath -Encoding UTF8
        $existingService.process.WaitForExit(20000)
        $stoppedService = Get-StagedBakeQueueServiceState -QueueRoot $queueRoot
        if ($stoppedService.matchingProcess) {
            throw "Staged-wave service process $($existingService.state.pid) did not stop after its source identity changed; refusing to launch a duplicate worker."
        }
        $existingService = $stoppedService
    }
    if ($existingService.matchingProcess -and [string]$existingService.state.status -ne "stopped") {
        throw "Staged-wave service process $($existingService.state.pid) is alive but its heartbeat is stale or invalid; refusing to launch a second worker."
    }
    if ($existingService.matchingProcess) {
        $existingService.process.WaitForExit(20000)
        $stillRunning = Get-StagedBakeQueueServiceState -QueueRoot $queueRoot
        if ($stillRunning.matchingProcess) {
            throw "Staged-wave service process $($existingService.state.pid) is shutting down; refusing to launch a second worker."
        }
    }

    [void](Start-StagedBakeQueueServiceGeneration `
        -QueueRoot $queueRoot `
        -PythonCommand $PythonCommand `
        -MaxWaveItems $MaxWaveItems `
        -SourceIdentityFingerprint $script:MotionSourceIdentityFingerprint `
        -ConfigurationFingerprint $configurationFingerprint `
        -RepositoryRoot $repoRoot)
}

function Publish-StagedBakeQueueRequest {
    param(
        [string]$QueueRoot,
        [int]$MaxWaveItems,
        [string]$RequestTemporaryPath,
        [string]$RequestPath
    )

    while ($true) {
        Ensure-StagedBakeQueueService -MaxWaveItems $MaxWaveItems
        $published = Invoke-WithStagedWaveAdmissionLock `
            -QueueRoot $QueueRoot `
            -IncludeLegacyCompatibility `
            -Operation {
            $service = Get-StagedBakeQueueServiceState -QueueRoot $QueueRoot
            if (
                $service.healthy -and
                [string]$service.state.status -in @("idle", "running")
            ) {
                Move-Item `
                    -LiteralPath $RequestTemporaryPath `
                    -Destination $RequestPath `
                    -Force
                return $true
            }
            if (
                $service.processState -eq "stopped" -or
                ($service.matchingProcess -and [string]$service.state.status -in @("stopping", "stopped"))
            ) {
                return $false
            }
            throw "Cannot confirm a live staged-wave service generation while publishing a request; refusing to leave an unowned queue entry."
        }
        if ($published) {
            return
        }
        # The worker closed admission between Ensure and mutex acquisition.
        # Ensure waits for its exit and launches a fresh generation before the
        # same still-private request file is published on the next iteration.
    }
}

function Stop-StagedBakeQueueServiceProcessTree {
    param(
        [int]$TargetPid,
        [int]$TimeoutMilliseconds = 5000
    )

    $taskkillPath = Join-Path ([Environment]::SystemDirectory) "taskkill.exe"
    if (-not (Test-Path -LiteralPath $taskkillPath -PathType Leaf)) {
        throw "Windows process-tree terminator was not found: $taskkillPath"
    }
    $terminator = $null
    try {
        $terminator = Start-Process `
            -FilePath $taskkillPath `
            -ArgumentList @("/PID", [string]$TargetPid, "/T", "/F") `
            -PassThru `
            -WindowStyle Hidden `
            -ErrorAction Stop
        if (-not $terminator.WaitForExit($TimeoutMilliseconds)) {
            Write-Warning "Windows process-tree termination for staged-wave worker $TargetPid exceeded its $TimeoutMilliseconds ms deadline."
            return $false
        }
        if ([int]$terminator.ExitCode -ne 0) {
            Write-Warning "Windows process-tree termination for staged-wave worker $TargetPid returned exit code $($terminator.ExitCode)."
            return $false
        }
        return $true
    } finally {
        if ($null -ne $terminator) {
            if (-not $terminator.HasExited) {
                try { $terminator.Kill() } catch {}
            }
            $terminator.Dispose()
        }
    }
}

function Stop-StagedBakeQueueService {
    param(
        [switch]$Cancel,
        [switch]$RunFailure
    )

    if (-not $Cancel -and -not $RunFailure) {
        # The worker stays available across workout-plan invocations and exits
        # itself after its bounded idle timeout.
        return
    }
    if ($Cancel -and -not (Test-MotionRunCancelRequested)) {
        return $true
    }
    $queueRoot = $script:StagedWaveServiceQueueRoot
    if ([string]::IsNullOrWhiteSpace($queueRoot) -or
        [string]::IsNullOrWhiteSpace($movementRunId) -or
        -not (Test-Path -LiteralPath $queueRoot -PathType Container)) {
        return $true
    }
    $cancelDirectory = Join-Path $queueRoot "cancelled_runs"
    New-Item -ItemType Directory -Force -Path $cancelDirectory | Out-Null
    $cancelPath = Join-Path $cancelDirectory "$movementRunId.json"
    $cancelPayload = [ordered]@{
        schemaVersion = 1
        runId = $movementRunId
        cancelledAtUtc = (Get-Date).ToUniversalTime().ToString("o")
        reason = if ($RunFailure) { "workout-plan scheduler failed" } else { "motion run cancelled by user" }
    }
    $cancelTemporaryPath = "$cancelPath.$([guid]::NewGuid().ToString('N')).tmp"
    $cancelPayload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $cancelTemporaryPath -Encoding UTF8
    Move-Item -LiteralPath $cancelTemporaryPath -Destination $cancelPath -Force

    $service = Get-StagedBakeQueueServiceState -QueueRoot $queueRoot
    if ($service.processState -eq "stopped") {
        # A valid worker record whose PID is gone or whose start identity no
        # longer matches confirms that this service generation cannot still
        # be using its model dependencies.
        return $true
    }
    if ($service.processState -ne "running" -or -not $service.matchingProcess) {
        # Missing, malformed, or inaccessible state is not proof of shutdown.
        # Keep the model services alive until this worker can be identified.
        Write-Warning "Could not confirm staged-wave worker ownership during shutdown; preserving its model dependencies."
        return $false
    }
    if (@($service.state.activeRequests | Where-Object {
        -not [string]::IsNullOrWhiteSpace([string]$_.runId) -and $_.runId -ne $movementRunId
    }).Count -gt 0) {
        Write-Warning "The staged-wave worker is serving another run; preserving its process and model dependencies."
        return $false
    }
    $activeWavePrefix = "$movementRunId-wave-"
    $activeWaveId = if ($service.state) { [string]$service.state.currentWaveId } else { "" }
    if (-not $activeWaveId.StartsWith($activeWavePrefix, [StringComparison]::OrdinalIgnoreCase) -and
        -not ($Cancel -and [string]::IsNullOrWhiteSpace($activeWaveId))) {
        # The cancellation marker prevents a queued request from starting.
        # Failure recovery can retain an idle worker; user cancellation stops it.
        # A worker serving another run must remain alive.
        return $true
    }
    if (-not $service.matchingProcess) {
        # The service is already gone. Its claimed request will be recovered
        # as ambiguous on the next start, without replaying model work.
        return $true
    }

    $stopRequestPath = Join-Path $queueRoot "stop.request"
    $stopRequestTemporaryPath = "$stopRequestPath.$([guid]::NewGuid().ToString('N')).tmp"
    $serviceStopRequested = $false
    try {
        "motion run '$movementRunId' cancelled" |
            Set-Content -LiteralPath $stopRequestTemporaryPath -Encoding UTF8 -ErrorAction Stop
        Move-Item `
            -LiteralPath $stopRequestTemporaryPath `
            -Destination $stopRequestPath `
            -Force `
            -ErrorAction Stop
        $serviceStopRequested = $true
    } catch {
        Write-Warning "Could not request graceful staged-wave service shutdown: $($_.Exception.Message)"
    } finally {
        if (Test-Path -LiteralPath $stopRequestTemporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $stopRequestTemporaryPath -Force -ErrorAction SilentlyContinue
        }
    }

    if ($serviceStopRequested) {
        # The service observes stop.request after its active synchronous wave
        # drains. Give that graceful path a short bounded window; a longer wave
        # may require process-tree termination below.
        try {
            [void]$service.process.WaitForExit(3000)
        } catch {
        }
    }
    $fallbackServiceState = Get-StagedBakeQueueServiceState -QueueRoot $queueRoot
    if ($fallbackServiceState.processState -eq "stopped") {
        return $true
    }
    if (-not $fallbackServiceState.matchingProcess) {
        Write-Warning "Could not reconfirm staged-wave worker ownership after its graceful-stop window; preserving its model dependencies."
        return $false
    }
    if ([int]$fallbackServiceState.state.pid -ne [int]$service.state.pid -or
        [int64]$fallbackServiceState.state.processIdentity -ne [int64]$service.state.processIdentity) {
        Write-Warning "Staged-wave worker identity changed during its graceful-stop window; preserving its model dependencies."
        return $false
    }

    # The active executor is synchronous and cannot observe cancellation while
    # blocked in model/render work, so it may outlast the graceful window.
    # Terminate its entire Windows process tree only after the owned generation
    # has had that chance to stop itself.
    try {
        [void](Stop-StagedBakeQueueServiceProcessTree `
            -TargetPid ([int]$service.state.pid) `
            -TimeoutMilliseconds 5000)
    } catch {
        Write-Warning "Could not terminate staged-wave worker process tree $($service.state.pid): $($_.Exception.Message)"
    }
    try {
        [void]$fallbackServiceState.process.WaitForExit(1000)
    } catch {
    }
    $terminatedState = Get-StagedBakeQueueServiceState -QueueRoot $queueRoot
    if ($terminatedState.processState -eq "stopped") {
        return $true
    }
    Write-Warning "Cancellation was requested, but staged-wave worker process tree $($fallbackServiceState.process.Id) has not confirmed exit."
    return $false
}

function Stop-MotionModelServicesAfterStagedWorker {
    param(
        [bool]$StagedWaveShutdownConfirmed,
        [object]$WarmGvhmrWorker,
        [object]$SharedLlamaServer
    )

    if (-not $StagedWaveShutdownConfirmed) {
        return $false
    }
    Stop-GvhmrWarmWorker -Worker $WarmGvhmrWorker
    Stop-SharedLlamaServer -Server $SharedLlamaServer
    return $true
}

function Start-StagedBakeWaveJob {
    param(
        [object[]]$WorkItems,
        [int]$WaveIndex
    )

    if ($WorkItems.Count -eq 0) {
        throw "Cannot start an empty staged movement wave."
    }
    $waveId = "{0}-wave-{1:D4}" -f $movementRunId, $WaveIndex
    $waveWorkspace = Join-Path (Join-Path $resolvedWorkspaceRoot "staged-waves") $waveId
    New-Item -ItemType Directory -Force -Path $waveWorkspace | Out-Null
    $waveManifestPath = Join-Path $waveWorkspace "wave_manifest.json"
    $waveLogPath = Join-Path $waveWorkspace "wave.log"
    $staleCheckpointPath = Join-Path $waveWorkspace "staged_wave_checkpoint.json"
    if (Test-Path -LiteralPath $staleCheckpointPath) {
        Remove-Item -LiteralPath $staleCheckpointPath -Force
    }
    $wavePayload = [ordered]@{
        schemaVersion = 1
        runId = $movementRunId
        waveId = $waveId
        workspace = $waveWorkspace
        items = @(
            $WorkItems | ForEach-Object {
                $candidateSnapshotPath = Join-Path $waveWorkspace ("candidates-{0}.json" -f [guid]::NewGuid().ToString('N'))
                Copy-Item -LiteralPath $_.exerciseCandidatesPath -Destination $candidateSnapshotPath -ErrorAction Stop
                [ordered]@{
                    exerciseId = $_.exerciseId
                    exerciseName = $_.exerciseName
                    exercisePlanJson = $_.exercisePlanPath
                    candidatesJson = $candidateSnapshotPath
                    workspace = $_.bakeWorkspace
                }
            }
        )
    }
    $wavePayload | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $waveManifestPath -Encoding UTF8
    # A resumed worker may have left a request after its caller exited.
    if ($effectiveWarmGvhmrWorker) {
        Remove-Item -LiteralPath (Join-Path $resolvedGvhmrWorkerSessionDir 'start_requested.json') -Force -ErrorAction SilentlyContinue
    }
    $applicationArguments = @($WorkItems[0].bakeArgs | Select-Object -Skip 2)
    $applicationArguments += @("--staged-wave-manifest", $waveManifestPath)
    $requestId = [guid]::NewGuid().ToString("N")
    $unixEpochTicks = [DateTime]::UnixEpoch.Ticks
    $enqueuedAtUnixNs = [long](([DateTime]::UtcNow.Ticks - $unixEpochTicks) * 100)
    $requestPath = Join-Path (Join-Path $script:StagedWaveServiceQueueRoot "requests") "$requestId.json"
    $requestPayload = [ordered]@{
        schemaVersion = 1
        requestId = $requestId
        enqueuedAtUnixNs = $enqueuedAtUnixNs
        runId = $movementRunId
        waveId = $waveId
        allowCpuPhaseOverlap = $effectiveMaxConcurrentStagedWaves -gt 1
        sourceIdentityFingerprint = $script:MotionSourceIdentityFingerprint
        serviceConfigurationFingerprint = (Get-StagedBakeServiceConfigurationFingerprint `
            -ConfiguredPythonCommand $PythonCommand `
            -MaxWaveItems $StagedWaveSize)
        arguments = [string[]]$applicationArguments
        logPath = $waveLogPath
    }
    $requestDirectory = Split-Path -Parent $requestPath
    New-Item -ItemType Directory -Force -Path $requestDirectory | Out-Null
    $requestTemporaryPath = "$requestPath.$([guid]::NewGuid().ToString('N')).tmp"
    $requestPayload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $requestTemporaryPath -Encoding UTF8
    try {
        Publish-StagedBakeQueueRequest `
            -QueueRoot $script:StagedWaveServiceQueueRoot `
            -MaxWaveItems $StagedWaveSize `
            -RequestTemporaryPath $requestTemporaryPath `
            -RequestPath $requestPath
    } finally {
        if (Test-Path -LiteralPath $requestTemporaryPath) {
            Remove-Item -LiteralPath $requestTemporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host ("Starting batch {0} ({1} exercises)." -f $WaveIndex, $WorkItems.Count)
    $job = Start-Job -Name "await-$waveId" -ScriptBlock {
        param(
            [string]$LogPath,
            [string]$WaveWorkspace,
            [string]$ExpectedWaveId,
            [string]$ExpectedRequestId,
            [string]$QueueRoot
        )
        $requestPath = Join-Path (Join-Path $QueueRoot "requests") "$ExpectedRequestId.json"
        $processingPath = Join-Path (Join-Path $QueueRoot "processing") "$ExpectedRequestId.json"
        $resultPath = Join-Path (Join-Path $QueueRoot "results") "$ExpectedRequestId.json"
        $statePath = Join-Path $QueueRoot "worker_state.json"
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        $lastVerifiedWorkerStateSeconds = 0.0
        $reportPath = Join-Path $WaveWorkspace "staged_wave_report.json"
        $report = $null
        $errorMessage = $null
        $exitCode = 1
        $serviceStatus = "failed"
        while ($true) {
            if (Test-Path -LiteralPath $resultPath) {
                try {
                    $serviceResult = Get-Content -LiteralPath $resultPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
                    if ($serviceResult.requestId -ne $ExpectedRequestId -or $serviceResult.waveId -ne $ExpectedWaveId) {
                        $serviceStatus = $using:StagedWaveAmbiguousRecoveryStatus
                        $exitCode = $using:StagedWaveAmbiguousRecoveryExitCode
                        $errorMessage = "Staged service published a result with an unexpected request or wave identity. Inspect the retained request and wave workspace before retrying."
                        break
                    }
                    $exitCode = [int]$serviceResult.exitCode
                    $serviceStatus = [string]$serviceResult.status
                    $errorMessage = $serviceResult.error
                    if ($serviceStatus -eq $using:StagedWaveAmbiguousRecoveryStatus) {
                        # The service status is authoritative for recovered
                        # in-flight work; keep it distinct from storage code 75.
                        $exitCode = $using:StagedWaveAmbiguousRecoveryExitCode
                    } elseif ($exitCode -eq $using:StagedWaveAmbiguousRecoveryExitCode -and
                        [string]::IsNullOrWhiteSpace($serviceStatus)) {
                            $serviceStatus = $using:StagedWaveAmbiguousRecoveryStatus
                    }
                    if ($exitCode -eq 0 -and (Test-Path -LiteralPath $reportPath)) {
                        $report = Get-Content -LiteralPath $reportPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
                        if ($report.waveId -ne $ExpectedWaveId) {
                            $report = $null
                            $exitCode = $using:StagedWaveAmbiguousRecoveryExitCode
                            $serviceStatus = $using:StagedWaveAmbiguousRecoveryStatus
                            $errorMessage = "Staged report has an unexpected wave identity. Inspect the retained wave workspace before retrying."
                        }
                    } elseif ($exitCode -eq 0) {
                        $exitCode = $using:StagedWaveAmbiguousRecoveryExitCode
                        $serviceStatus = $using:StagedWaveAmbiguousRecoveryStatus
                        $errorMessage = "Staged-wave service reported success without a report file. Inspect the retained wave workspace before retrying."
                    }
                    # The request waiter owns result consumption. Moving the
                    # validated terminal record lets the persistent service
                    # prune old consumed responses without touching results
                    # that a live caller may still need.
                    try {
                        $consumedDirectory = Join-Path $QueueRoot "consumed"
                        New-Item -ItemType Directory -Force -Path $consumedDirectory | Out-Null
                        Move-Item `
                            -LiteralPath $resultPath `
                            -Destination (Join-Path $consumedDirectory "$ExpectedRequestId.json") `
                            -ErrorAction Stop
                    } catch {
                        # Retain the response in results if acknowledgement
                        # cannot be persisted; cleanup must never lose it.
                    }
                    break
                } catch {
                    $serviceStatus = $using:StagedWaveAmbiguousRecoveryStatus
                    $exitCode = $using:StagedWaveAmbiguousRecoveryExitCode
                    $errorMessage = "Could not validate the staged service response: $($_.Exception.Message). Inspect the retained request and wave workspace before retrying."
                    break
                }
            }
            $workerState = $null
            if (Test-Path -LiteralPath $statePath) {
                try { $workerState = Get-Content -LiteralPath $statePath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop } catch {}
            }
            $requestQueued = Test-Path -LiteralPath $requestPath
            $requestProcessing = Test-Path -LiteralPath $processingPath
            $workerProcess = $null
            $workerIdentityMatches = $false
            if ($workerState) {
                $heartbeatAge = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0 - [double]$workerState.updatedAtEpoch
                $stateQueueMatches = [string]::Equals([string]$workerState.queueRoot, $QueueRoot, [StringComparison]::OrdinalIgnoreCase)
                $workerProcess = Get-Process -Id ([int]$workerState.pid) -ErrorAction SilentlyContinue
                if ($workerProcess -and $null -ne $workerState.processIdentity) {
                    try {
                        $workerIdentityMatches = [int64]$workerProcess.StartTime.ToUniversalTime().ToFileTimeUtc() -eq [int64]$workerState.processIdentity
                    } catch {
                        $workerIdentityMatches = $false
                    }
                }
                $workerMatchesRequest = [string]::Equals(
                    [string]$workerState.currentRequestId,
                    $ExpectedRequestId,
                    [StringComparison]::OrdinalIgnoreCase
                )
                if (-not $workerMatchesRequest) {
                    $workerMatchesRequest = @($workerState.activeRequests | Where-Object { $_.requestId -eq $ExpectedRequestId }).Count -gt 0
                }
                if ($workerState.schemaVersion -ne 1 -or -not $stateQueueMatches -or
                    $null -eq $workerProcess -or -not $workerIdentityMatches) {
                    # A published request may already have been claimed. If
                    # the owning service cannot be verified before a terminal
                    # result appears, replaying the workspace could collide
                    # with work that completed just before the worker exited.
                    $serviceStatus = $using:StagedWaveAmbiguousRecoveryStatus
                    $exitCode = $using:StagedWaveAmbiguousRecoveryExitCode
                    $errorMessage = "Staged-wave request has no terminal result and its owning service can no longer be verified. Inspect the retained request, processing record, and wave workspace before retrying."
                    break
                }
                $lastVerifiedWorkerStateSeconds = $stopwatch.Elapsed.TotalSeconds
                if ($heartbeatAge -lt -5 -or $heartbeatAge -gt 20) {
                    # Heartbeat timestamps are liveness hints, not request
                    # completion evidence. A matching live process plus a
                    # queued, claimed, or active request must never enter the
                    # individual retry lane.
                    if (-not $requestQueued -and -not $requestProcessing -and -not $workerMatchesRequest) {
                        $serviceStatus = $using:StagedWaveAmbiguousRecoveryStatus
                        $exitCode = $using:StagedWaveAmbiguousRecoveryExitCode
                        $errorMessage = "Staged-wave heartbeat is stale and the request is no longer visible in the queue or worker state. Inspect the retained wave workspace before retrying."
                        break
                    }
                } elseif ($workerState.status -eq "stopped" -and
                    -not $requestQueued -and -not $requestProcessing -and -not $workerMatchesRequest) {
                    $serviceStatus = $using:StagedWaveAmbiguousRecoveryStatus
                    $exitCode = $using:StagedWaveAmbiguousRecoveryExitCode
                    $errorMessage = "Persistent staged-wave service stopped without publishing a terminal result for this request. Inspect the retained wave workspace before retrying."
                    break
                }
            } elseif (($stopwatch.Elapsed.TotalSeconds - $lastVerifiedWorkerStateSeconds) -gt 45) {
                $serviceStatus = $using:StagedWaveAmbiguousRecoveryStatus
                $exitCode = $using:StagedWaveAmbiguousRecoveryExitCode
                $errorMessage = "Persistent staged-wave service state remained unreadable for 45 seconds. Inspect the retained request and wave workspace before retrying."
                break
            }
            Start-Sleep -Milliseconds 250
        }
        $stopwatch.Stop()
        [pscustomobject]@{
            exitCode = $exitCode
            stage = "staged_wave"
            elapsedSeconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
            reportPath = $reportPath
            report = $report
            serviceStatus = $serviceStatus
            logPath = $LogPath
            error = $errorMessage
        }
    } -ArgumentList $waveLogPath, $waveWorkspace, $waveId, $requestId, $script:StagedWaveServiceQueueRoot
    $job | Add-Member -MemberType NoteProperty -Name WorkItems -Value $WorkItems
    $job | Add-Member -MemberType NoteProperty -Name IsStagedWave -Value $true
    $job | Add-Member -MemberType NoteProperty -Name WaveWorkspace -Value $waveWorkspace
    $job | Add-Member -MemberType NoteProperty -Name WaveId -Value $waveId
    $job | Add-Member -MemberType NoteProperty -Name RequestId -Value $requestId
    $job | Add-Member -MemberType NoteProperty -Name StartedAt -Value (Get-Date)
    return $job
}

function Start-StagedResultCompletionJob {
    param([object]$WorkItem)

    $job = Start-Job -Name "complete-$($WorkItem.exerciseSlug)" -ScriptBlock {
        [pscustomobject]@{
            exitCode = 0
            stage = "staged_wave_completion"
            selectedResultCount = 1
            discoverySeconds = 0.0
            bakeSeconds = 0.0
            discoveryAttemptCount = 0
            bakeAttemptCount = 1
            attempts = @()
        }
    }
    $job | Add-Member -MemberType NoteProperty -Name WorkItem -Value $WorkItem
    $job | Add-Member -MemberType NoteProperty -Name IsStagedCompletion -Value $true
    return $job
}

function Complete-BakeJob {
    param([object]$Job)

    $workItem = $Job.WorkItem
    $status = "completed"
    $errorMessage = $null
    $failureStage = $null
    $jobResult = $null

    try {
        $received = @(Receive-Job -Job $Job -Wait -ErrorAction Stop)
        if ($received.Count -gt 0) {
            $jobResult = $received[-1]
        }
    } catch {
        $status = "failed"
        $errorMessage = $_.Exception.Message
        $failureStage = "job"
    } finally {
        Remove-Job -Job $Job -Force
    }

    if ($jobResult -and $jobResult.exitCode -eq 75) {
        Write-Host "Movement generation stopped: insufficient free storage. Free space and resume."
        exit 75
    }
    if ($jobResult -and $jobResult.retryPending -eq $true) {
        $workItem.discoverySeconds = Add-OptionalSeconds -Current $workItem.discoverySeconds -Value (Get-OptionalDouble -Value $jobResult.discoverySeconds)
        $workItem.discoveryAttemptCount = [int]$workItem.discoveryAttemptCount + [int]$jobResult.discoveryAttemptCount
        $workItem.attempts += @($jobResult.attempts)
        return [ordered]@{
            exerciseId = $workItem.exerciseId
            exerciseName = $workItem.exerciseName
            status = "retry_pending"
            workItem = $workItem
        }
    }

    if ($status -eq "completed" -and (-not $jobResult -or $jobResult.exitCode -ne 0)) {
        $status = "failed"
        $exitCode = if ($jobResult) { $jobResult.exitCode } else { "unknown" }
        $stage = if ($jobResult -and $jobResult.stage) { $jobResult.stage } else { "unknown" }
        $failureStage = $stage
        $detail = Get-ObjectProperty -Object $jobResult -Name "error"
        $detailText = if (-not [string]::IsNullOrWhiteSpace([string]$detail)) { " $detail" } else { "" }
        $failureLogPath = Get-ObjectProperty -Object $jobResult -Name "logPath"
        if ([string]::IsNullOrWhiteSpace([string]$failureLogPath)) { $failureLogPath = $workItem.logPath }
        $errorMessage = "python $stage command failed with exit code $exitCode.$detailText See log: $failureLogPath"
    }

    $selectionPath = Join-Path $workItem.bakeWorkspace "selection_manifest.json"
    $selection = $null
    if (Test-Path -LiteralPath $selectionPath) {
        $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-ReconstructionJson
    }
    $selectionTimingSummary = Get-SelectionTimingSummary -Selection $selection
    $selected = if ($selection -and $selection.selected) { $selection.selected } else { $null }
    $manualReviewFallback = if ($selection -and $selection.manualReviewFallback) { $selection.manualReviewFallback } else { $null }
    $selectedOptions = if ($selection -and $selection.PSObject.Properties.Name -contains "selectedResults" -and $selection.selectedResults) {
        @($selection.selectedResults)
    } elseif ($selected) {
        @($selected)
    } else {
        @()
    }
    if ($status -eq "completed" -and $selectedOptions.Count -eq 0) {
        if ($jobResult -and $jobResult.processingIncomplete -eq $true) {
            $status = "needs_motion_processing"
            $errorMessage = "Motion fitting did not finish; resume the retained source and reconstruction."
        } elseif ($jobResult -and -not [string]::IsNullOrWhiteSpace("$($jobResult.terminalReason)")) {
            $status = "no_selection"
            $errorMessage = switch ("$($jobResult.terminalReason)") {
                "semantic_candidates_exhausted" { "The reviewed source pool contained no semantically compatible candidate." }
                "source_pool_exhausted_after_pose_rejection" { "Semantically compatible candidates were found, but none passed reconstruction pose/visibility checks." }
                "source_pool_exhausted_after_source_review" { "No source interval was approved for reconstruction; see source-review results for rejection or unresolved evidence." }
                "insufficient_reconstruction_ready_sources" { "The reviewed source pool did not contain enough reconstruction-ready movements." }
                default { "No reconstruction-ready source remained after progressive source review." }
            }
        } elseif ($manualReviewFallback) {
            $status = "needs_manual_review"
            $errorMessage = "No candidate passed automatic validation; the best generated movement is available for manual review."
        } else {
            $status = "no_selection"
            $errorMessage = "No Wear skeleton was selected."
        }
    }
    if ($status -eq "completed") {
        $optionIndex = 1
        foreach ($option in $selectedOptions) {
            if ($option.wearSkeletonSettingsBaked -ne $true) {
                $status = "failed"
                $failureStage = "selected_output_validation"
                $errorMessage = "Selected Wear skeleton option $optionIndex does not contain baked preview settings required by Wear."
                break
            }
            $optionIndex += 1
        }
    }

    $candidateCount = $workItem.candidateCount
    $recommendedCandidateCount = 0
    if (Test-Path -LiteralPath $workItem.exerciseCandidatesPath) {
        try {
            $exerciseCandidateManifest = Get-Content -LiteralPath $workItem.exerciseCandidatesPath -Raw | ConvertFrom-ReconstructionJson
            if ($exerciseCandidateManifest.exercises -and $exerciseCandidateManifest.exercises.Count -gt 0) {
                $candidateCount = @($exerciseCandidateManifest.exercises[0].candidates).Count
                foreach ($item in @($exerciseCandidateManifest.exercises[0].candidates)) {
                    if ("$($item.status)".ToLowerInvariant() -eq "recommended") {
                        $recommendedCandidateCount += 1
                    }
                }
            }
        } catch {
            if ($null -eq $candidateCount) {
                $candidateCount = 0
            }
        }
    }
    $retryDiscoverySeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $jobResult -Name "discoverySeconds")
    if ($null -eq $retryDiscoverySeconds) {
        $retryDiscoverySeconds = 0.0
    }
    $bakeCommandSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $jobResult -Name "bakeSeconds")
    if ($null -eq $bakeCommandSeconds) {
        $bakeCommandSeconds = 0.0
    }
    $initialDiscoverySeconds = Get-OptionalDouble -Value $workItem.discoverySeconds
    if ($null -eq $initialDiscoverySeconds) {
        $initialDiscoverySeconds = 0.0
    }
    $attempts = @()
    $attempts += @($workItem.attempts)
    $attempts += @(Get-ObjectProperty -Object $jobResult -Name "attempts")

    $selectedOutputDir = Join-Path $workItem.exerciseWorkspace "selected"
    $selectedWearSkeletonPath = $null
    $selectedPreviewVideoPath = $null
    $selectedInteractivePreviewHtmlPath = $null
    $selectedInputVideoPath = $null
    $selectedInputVideoWebmPath = $null
    $selectedInputVideoSourcePath = $null
    $selectedInputVideoMissing = $false
    $selectedSelectionManifestPath = $null
    $selectedDebugDir = Join-Path $selectedOutputDir "debug"
    $selectedCandidateDebugPath = $null
    $selectedCandidateDecisionsPath = $null
    $selectedResultOutputs = @()
    if ($status -eq "needs_manual_review" -and $manualReviewFallback) {
        $manualReviewOutputDir = Join-Path $workItem.exerciseWorkspace "manual-review"
        $manualReviewFilePrefix = $workItem.exerciseSlug -replace "-", "_"
        $selectedSelectionManifestPath = Copy-SelectedFile `
            -SourcePath $selectionPath `
            -DestinationDirectory $manualReviewOutputDir `
            -DestinationFileName "selection_manifest.json"
        $selectedWearSkeletonPath = Copy-SelectedFile `
            -SourcePath $manualReviewFallback.selectedWearSkeletonPath `
            -DestinationDirectory $manualReviewOutputDir `
            -DestinationFileName "$($manualReviewFilePrefix)_wear_skeleton.json"
        $manualReviewSkeletonParity = Assert-SelectedSkeletonReviewParity `
            -SelectionEntry $manualReviewFallback `
            -SourcePath $manualReviewFallback.selectedWearSkeletonPath `
            -PackagedPath $selectedWearSkeletonPath `
            -ManualReviewFallback
        Record-PackagedSkeletonReviewParity `
            -SelectionManifestPath $selectedSelectionManifestPath `
            -OptionIndex 1 `
            -PackagedPath $selectedWearSkeletonPath `
            -Parity $manualReviewSkeletonParity `
            -ManualReviewFallback
        $selectedPreviewVideoPath = Copy-SelectedFile `
            -SourcePath $manualReviewFallback.selectedReviewVideoPath `
            -DestinationDirectory $manualReviewOutputDir `
            -DestinationFileName "$($manualReviewFilePrefix)_manual_review_preview.webm"
        $selectedInputVideoSourcePath = Get-ObjectProperty -Object $manualReviewFallback -Name "selectedInputVideoPath"
        $selectedInputVideoPath = Copy-SelectedFile `
            -SourcePath $selectedInputVideoSourcePath `
            -DestinationDirectory $manualReviewOutputDir `
            -DestinationFileName "$($manualReviewFilePrefix)_manual_review_input.mp4"
        if ($selectedInputVideoPath) {
            $selectedInputVideoWebmPath = Convert-SelectedSourceVideoToWebm `
                -SourcePath $selectedInputVideoPath `
                -DestinationDirectory $manualReviewOutputDir `
                -DestinationFileName "$($manualReviewFilePrefix)_manual_review_input.webm"
        }
        $manualReviewInteractiveSourcePath = Get-ObjectProperty -Object $manualReviewFallback -Name "sourcePreviewHtmlPath"
        if ([string]::IsNullOrWhiteSpace($manualReviewInteractiveSourcePath)) {
            $manualReviewInteractiveSourcePath = Get-ObjectProperty -Object $manualReviewFallback -Name "previewHtmlPath"
        }
        $selectedInteractivePreviewHtmlPath = Copy-SelectedFile `
            -SourcePath $manualReviewInteractiveSourcePath `
            -DestinationDirectory $manualReviewOutputDir `
            -DestinationFileName "$($manualReviewFilePrefix)_interactive_preview.html"
        Copy-SelectedPreviewRuntimeAssets `
            -SourcePreviewHtmlPath $manualReviewInteractiveSourcePath `
            -DestinationDirectory $manualReviewOutputDir
        $manualReviewStartSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $manualReviewFallback -Name "selectedSectionStartSeconds")
        if ($null -eq $manualReviewStartSeconds) {
            $manualReviewStartSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $manualReviewFallback -Name "sectionStartSeconds")
        }
        if ($null -eq $manualReviewStartSeconds) {
            $manualReviewStartSeconds = 0.0
        }
        $manualReviewEndSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $manualReviewFallback -Name "selectedSectionEndSeconds")
        if ($null -eq $manualReviewEndSeconds) {
            $manualReviewEndSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $manualReviewFallback -Name "sectionEndSeconds")
        }
        if ($null -eq $manualReviewEndSeconds) {
            $manualReviewEndSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $manualReviewFallback -Name "durationSec")
        }
        if ($null -eq $manualReviewEndSeconds) {
            $manualReviewEndSeconds = 0.0
        }
        $manualReviewSettingsJson = ConvertTo-SelectedPreviewOptionsJson `
            -Options (Get-ObjectProperty -Object $manualReviewFallback -Name "settingsOptions") `
            -WearSkeletonPath $selectedWearSkeletonPath
        $selectedPreviewHtmlPath = Join-Path $manualReviewOutputDir "$($manualReviewFilePrefix)_manual_review.html"
        $selectedPreviewHtmlPath = Write-SelectedPreviewHtml `
            -DestinationPath $selectedPreviewHtmlPath `
            -ExerciseName "$($workItem.exerciseName) - Manual review" `
            -OptionIndex 1 `
            -PreviewVideoPath $selectedPreviewVideoPath `
            -InputVideoPath $selectedInputVideoPath `
            -InputVideoWebmPath $selectedInputVideoWebmPath `
            -WearSkeletonPath $selectedWearSkeletonPath `
            -InteractivePreviewPath $selectedInteractivePreviewHtmlPath `
            -StartSeconds $manualReviewStartSeconds `
            -EndSeconds $manualReviewEndSeconds `
            -SettingsOptionsJson $manualReviewSettingsJson
        $selectedResultOutputs = @(
            [ordered]@{
                optionIndex = 1
                label = "Manual review fallback"
                selectionStatus = "needs_manual_review"
                selectedWearSkeletonPath = $selectedWearSkeletonPath
                selectedSkeletonReviewParity = $manualReviewSkeletonParity
                selectedPreviewVideoPath = $selectedPreviewVideoPath
                selectedPreviewHtmlPath = $selectedPreviewHtmlPath
                selectedInteractivePreviewHtmlPath = $selectedInteractivePreviewHtmlPath
                selectedSourceVideoPath = $selectedInputVideoPath
                selectedSourceVideoWebmPath = $selectedInputVideoWebmPath
                selectedSourceVideoOriginalPath = $selectedInputVideoSourcePath
                selectionScore = Get-ObjectProperty -Object $manualReviewFallback -Name "selectionScore"
                candidateTitle = Get-ObjectProperty -Object $manualReviewFallback -Name "candidateTitle"
            }
        )
    }
    if ($status -eq "completed" -and $selectedOptions.Count -gt 0) {
        $selectedFilePrefix = $workItem.exerciseSlug -replace "-", "_"
        $selectedSelectionManifestPath = Copy-SelectedFile `
            -SourcePath $selectionPath `
            -DestinationDirectory $selectedOutputDir `
            -DestinationFileName "selection_manifest.json"
        if (-not $selectedSelectionManifestPath) {
            $status = "failed"
            $failureStage = "selected_output_copy"
            $errorMessage = "Selection manifest was not copied to the selected output directory."
        }
        if ($status -eq "completed") {
            $selectedCandidateDebugPath = Copy-SelectedFile `
                -SourcePath $workItem.exerciseCandidatesPath `
                -DestinationDirectory $selectedDebugDir `
                -DestinationFileName "youtube_candidates.full.json"
            $candidateDecisionsPath = Join-Path (Split-Path -Parent $workItem.exerciseCandidatesPath) "candidate_decisions.jsonl"
            $selectedCandidateDecisionsPath = Copy-SelectedFile `
                -SourcePath $candidateDecisionsPath `
                -DestinationDirectory $selectedDebugDir `
                -DestinationFileName "candidate_decisions.jsonl"
        }
        $optionIndex = 1
        foreach ($option in $selectedOptions) {
            if ($status -ne "completed") {
                break
            }
            $optionSuffix = if ($optionIndex -eq 1) { "" } else { "_option_{0:D2}" -f $optionIndex }
            $optionWearSkeletonPath = Copy-SelectedFile `
                -SourcePath $option.selectedWearSkeletonPath `
                -DestinationDirectory $selectedOutputDir `
                -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_wear_skeleton.json"
            if (-not $optionWearSkeletonPath) {
                $status = "failed"
                $failureStage = "selected_output_copy"
                $errorMessage = "Selected Wear skeleton option $optionIndex was not copied to the selected output directory."
                break
            }
            try {
                $optionSkeletonReviewParity = Assert-SelectedSkeletonReviewParity `
                    -SelectionEntry $option `
                    -SourcePath $option.selectedWearSkeletonPath `
                    -PackagedPath $optionWearSkeletonPath
                Record-PackagedSkeletonReviewParity `
                    -SelectionManifestPath $selectedSelectionManifestPath `
                    -OptionIndex $optionIndex `
                    -PackagedPath $optionWearSkeletonPath `
                    -Parity $optionSkeletonReviewParity
            } catch {
                $status = "failed"
                $failureStage = "selected_output_parity"
                $errorMessage = $_.Exception.Message
                break
            }
            $optionPreviewVideoPath = $null
            if ($option.selectedReviewVideoPath) {
                $optionPreviewVideoPath = Copy-SelectedFile `
                    -SourcePath $option.selectedReviewVideoPath `
                    -DestinationDirectory $selectedOutputDir `
                    -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_selected_preview.webm"
            }
            $optionInputVideoSourcePath = if ($option.PSObject.Properties.Name -contains "selectedInputVideoPath") {
                $option.selectedInputVideoPath
            } elseif ($option.PSObject.Properties.Name -contains "copiedInputVideoPath") {
                $option.copiedInputVideoPath
            } else {
                $null
            }
            $optionInputVideoPath = $null
            $optionInputVideoWebmPath = $null
            $optionInputVideoMissing = $false
            if ($optionInputVideoSourcePath) {
                $optionInputVideoPath = Copy-SelectedFile `
                    -SourcePath $optionInputVideoSourcePath `
                    -DestinationDirectory $selectedOutputDir `
                    -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_selected_input.mp4"
                if (-not $optionInputVideoPath) {
                    $optionInputVideoMissing = $true
                    Write-Warning "Selected input video option $optionIndex was not copied for '$($workItem.exerciseName)': $optionInputVideoSourcePath"
                } else {
                    $optionInputVideoWebmPath = Convert-SelectedSourceVideoToWebm `
                        -SourcePath $optionInputVideoPath `
                        -DestinationDirectory $selectedOutputDir `
                        -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_selected_input.webm"
                }
            }
            $optionCandidateWorkspace = Get-ObjectProperty -Object $option -Name "candidateWorkspace"
            $optionAuditOutputDirectory = if ($optionIndex -eq 1) {
                $selectedOutputDir
            } else {
                Join-Path $selectedOutputDir ("audit\option_{0:D2}" -f $optionIndex)
            }
            $optionSourceAuditDirectory = Copy-SelectedSourceAuditEvidence `
                -CandidateWorkspace $optionCandidateWorkspace `
                -DestinationDirectory $optionAuditOutputDirectory
            $optionInputSourcePath = Get-ObjectProperty -Object $option -Name "selectedInputSourceVideoPath"
            $optionInputSourceCopyPath = $null
            if (-not [string]::IsNullOrWhiteSpace([string]$optionInputSourcePath)) {
                if (-not (Test-Path -LiteralPath $optionInputSourcePath -PathType Leaf)) {
                    $status = "failed"
                    $failureStage = "selected_output_copy"
                    $errorMessage = "Selected reconstruction input is missing before artifact promotion: $optionInputSourcePath"
                    break
                }
                $sourceInputIsReviewInput = $false
                if (-not [string]::IsNullOrWhiteSpace([string]$optionInputVideoSourcePath) -and
                    -not [string]::IsNullOrWhiteSpace([string]$optionInputVideoPath)) {
                    $sourceInputIsReviewInput = [string]::Equals(
                        [System.IO.Path]::GetFullPath([string]$optionInputSourcePath),
                        [System.IO.Path]::GetFullPath([string]$optionInputVideoSourcePath),
                        [System.StringComparison]::OrdinalIgnoreCase
                    )
                }
                if ($sourceInputIsReviewInput -and $optionInputVideoPath) {
                    $optionInputSourceCopyPath = $optionInputVideoPath
                } else {
                    $sourceInputExtension = [System.IO.Path]::GetExtension([string]$optionInputSourcePath)
                    if ([string]::IsNullOrWhiteSpace($sourceInputExtension)) {
                        $sourceInputExtension = ".mp4"
                    }
                    $optionInputSourceCopyPath = Copy-SelectedFile `
                        -SourcePath ([string]$optionInputSourcePath) `
                        -DestinationDirectory (Join-Path $optionAuditOutputDirectory "processing_evidence") `
                        -DestinationFileName ("selected_input_source{0}{1}" -f $optionSuffix, $sourceInputExtension)
                    if ([string]::IsNullOrWhiteSpace($optionInputSourceCopyPath)) {
                        $status = "failed"
                        $failureStage = "selected_output_copy"
                        $errorMessage = "Selected reconstruction input was not retained for option $optionIndex."
                        break
                    }
                }
            }
            $optionInteractivePreviewSourcePath = Get-ObjectProperty -Object $option -Name "sourcePreviewHtmlPath"
            $optionInteractivePreviewPath = Copy-SelectedFile `
                -SourcePath $optionInteractivePreviewSourcePath `
                -DestinationDirectory $selectedOutputDir `
                -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_interactive_preview.html"
            Copy-SelectedPreviewRuntimeAssets `
                -SourcePreviewHtmlPath $optionInteractivePreviewSourcePath `
                -DestinationDirectory $selectedOutputDir
            $optionStartSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $option -Name "selectedSectionStartSeconds")
            if ($null -eq $optionStartSeconds) {
                $optionStartSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $option -Name "loopStartSeconds")
            }
            if ($null -eq $optionStartSeconds) {
                $optionStartSeconds = 0.0
            }
            $optionEndSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $option -Name "selectedSectionEndSeconds")
            if ($null -eq $optionEndSeconds) {
                $optionEndSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $option -Name "loopEndSeconds")
            }
            if ($null -eq $optionEndSeconds) {
                $optionEndSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $option -Name "durationSec")
            }
            if ($null -eq $optionEndSeconds) {
                $optionEndSeconds = 0.0
            }
            $optionSettingsOptions = Get-ObjectProperty -Object $option -Name "settingsOptions"
            $optionSettingsOptionsJson = ConvertTo-SelectedPreviewOptionsJson `
                -Options $optionSettingsOptions `
                -WearSkeletonPath $optionWearSkeletonPath
            $optionPreviewHtmlPath = Join-Path $selectedOutputDir "$($selectedFilePrefix)$($optionSuffix)_selected_preview.html"
            $optionPreviewHtmlPath = Write-SelectedPreviewHtml `
                -DestinationPath $optionPreviewHtmlPath `
                -ExerciseName $workItem.exerciseName `
                -OptionIndex $optionIndex `
                -PreviewVideoPath $optionPreviewVideoPath `
                -InputVideoPath $optionInputVideoPath `
                -InputVideoWebmPath $optionInputVideoWebmPath `
                -WearSkeletonPath $optionWearSkeletonPath `
                -InteractivePreviewPath $optionInteractivePreviewPath `
                -StartSeconds $optionStartSeconds `
                -EndSeconds $optionEndSeconds `
                -SettingsOptionsJson $optionSettingsOptionsJson
            try {
                $optionContactSheetPaths = Copy-SelectedFinalRenderContactSheets `
                    -SelectionEntry $option `
                    -DestinationDirectory $selectedOutputDir `
                    -OptionIndex $optionIndex
                Update-PackagedSelectionArtifactReferences `
                    -SelectionManifestPath $selectedSelectionManifestPath `
                    -OptionIndex $optionIndex `
                    -SelectedOutputDirectory $selectedOutputDir `
                    -AuditOutputDirectory $optionAuditOutputDirectory `
                    -PackagedSkeletonPath $optionWearSkeletonPath `
                    -ReviewVideoPath $optionPreviewVideoPath `
                    -InputVideoPath $optionInputVideoPath `
                    -InputSourceVideoPath $optionInputSourceCopyPath `
                    -PreviewHtmlPath $optionPreviewHtmlPath `
                    -InteractivePreviewHtmlPath $optionInteractivePreviewPath `
                    -ContactSheetPaths $optionContactSheetPaths
            } catch {
                $status = "failed"
                $failureStage = "selected_output_evidence_copy"
                $errorMessage = $_.Exception.Message
                break
            }
            $selectedResultOutputs += [ordered]@{
                optionIndex = $optionIndex
                label = if ($option.PSObject.Properties.Name -contains "manualSelectionLabel") { $option.manualSelectionLabel } else { "Option $optionIndex" }
                selectedWearSkeletonPath = $optionWearSkeletonPath
                selectedPreviewVideoPath = $optionPreviewVideoPath
                selectedPreviewHtmlPath = $optionPreviewHtmlPath
                selectedInteractivePreviewHtmlPath = $optionInteractivePreviewPath
                selectedSourceVideoPath = $optionInputVideoPath
                selectedSourceVideoWebmPath = $optionInputVideoWebmPath
                selectedSourceVideoOriginalPath = if ($optionInputSourceCopyPath) { $optionInputSourceCopyPath } else { $optionInputVideoPath }
                selectedSourceVideoMissing = $optionInputVideoMissing
                selectedSourceAuditDirectory = $optionSourceAuditDirectory
                selectedSkeletonReviewParity = $optionSkeletonReviewParity
                selectionScore = if ($option.PSObject.Properties.Name -contains "selectionScore") { $option.selectionScore } else { $null }
                candidateTitle = if ($option.PSObject.Properties.Name -contains "candidateTitle") { $option.candidateTitle } else { $null }
            }
            if ($optionIndex -eq 1) {
                $selectedWearSkeletonPath = $optionWearSkeletonPath
                $selectedPreviewVideoPath = $optionPreviewVideoPath
                $selectedInteractivePreviewHtmlPath = $optionInteractivePreviewPath
                $selectedInputVideoPath = $optionInputVideoPath
                $selectedInputVideoWebmPath = $optionInputVideoWebmPath
                $selectedInputVideoSourcePath = if ($optionInputSourceCopyPath) { $optionInputSourceCopyPath } else { $optionInputVideoPath }
                $selectedInputVideoMissing = $optionInputVideoMissing
            }
            $optionIndex += 1
        }
        if ($status -eq "completed") {
            Write-PublishedSelectionAcceptanceMarker `
                -WorkItem $workItem `
                -SelectedOutputDir $selectedOutputDir `
                -SelectionManifestPath $selectedSelectionManifestPath
            Remove-ExerciseIntermediateArtifacts -WorkItem $workItem
        }
    }

    if ($status -eq "completed") {
        $optionText = if ($selectedResultOutputs.Count -gt 1) { " ($($selectedResultOutputs.Count) options)" } else { "" }
        $readyCount = @($summaryByIndex.Values | Where-Object {
            "$($_.status)" -eq 'completed' -and "$($_.exerciseId)" -ne "$($workItem.exerciseId)"
        }).Count + 1
        Write-Host ("SUCCESS: {0} | Validated movement saved{1}. | Library: {2}/{3} ready" -f $workItem.exerciseName, $optionText, $readyCount, $workItems.Count)
    } else {
        $reasonText = if (-not [string]::IsNullOrWhiteSpace($errorMessage)) { " $errorMessage" } else { "" }
        $outcomeLabel = switch ($status) {
            'needs_manual_review' { 'Needs review' }
            'needs_source_review' { 'Needs review' }
            'needs_definition_review' { 'Needs definition review' }
            'no_selection' { 'No suitable movement' }
            default { 'Failed' }
        }
        Write-Host ("{0}: {1}.{2} See {3}" -f $outcomeLabel, $workItem.exerciseName, $reasonText, $workItem.logPath)
    }

    return [ordered]@{
        exerciseId = $workItem.exerciseId
        exerciseName = $workItem.exerciseName
        status = $status
        error = $errorMessage
        stage = if ($status -eq "failed" -and -not [string]::IsNullOrWhiteSpace($failureStage)) { $failureStage } elseif ($status -eq "needs_definition_review") { "exercise_definition" } elseif ($status -eq "no_selection") { "bake_no_selection" } elseif ($status -eq "needs_manual_review") { "manual_review" } else { $null }
        candidateCount = $candidateCount
        recommendedCandidateCount = $recommendedCandidateCount
        excludeCandidateJsonPaths = $workItem.excludeCandidateJsonPaths
        candidatesJsonPath = if ($status -eq "completed") { $null } else { $workItem.exerciseCandidatesPath }
        selectionManifestPath = if ($status -in @("completed", "needs_manual_review") -and $selectedSelectionManifestPath) { $selectedSelectionManifestPath } else { $selectionPath }
        logPath = $workItem.logPath
        selectedWearSkeletonPath = $selectedWearSkeletonPath
        selectedPreviewVideoPath = $selectedPreviewVideoPath
        selectedPreviewHtmlPath = if ($status -eq "needs_manual_review") { $selectedPreviewHtmlPath } else { $null }
        selectedInteractivePreviewHtmlPath = $selectedInteractivePreviewHtmlPath
        selectedSourceVideoPath = $selectedInputVideoPath
        selectedSourceVideoWebmPath = $selectedInputVideoWebmPath
        selectedSourceVideoOriginalPath = $selectedInputVideoSourcePath
        selectedSourceVideoMissing = $selectedInputVideoMissing
        selectedResults = $selectedResultOutputs
        selectedCandidateDebugPath = $selectedCandidateDebugPath
        selectedCandidateDecisionsPath = $selectedCandidateDecisionsPath
        attempts = $attempts
        timings = [ordered]@{
            prefetchSeconds = [Math]::Round([double]$workItem.prefetchSeconds, 3)
            prefetchReused = [bool]$workItem.prefetchReused
            discoverySeconds = [Math]::Round(($initialDiscoverySeconds + $retryDiscoverySeconds), 3)
            discoveryReused = [bool]$workItem.discoveryReused
            initialDiscoverySeconds = [Math]::Round($initialDiscoverySeconds, 3)
            retryDiscoverySeconds = [Math]::Round($retryDiscoverySeconds, 3)
            sourceDownloadSeconds = [Math]::Round([double]$workItem.sourceDownloadSeconds, 3)
            primarySourceDownloadReused = [bool]$workItem.primarySourceDownloadReused
            fallbackSourceDownloadReused = [bool]$workItem.fallbackSourceDownloadReused
            bakeCommandSeconds = [Math]::Round($bakeCommandSeconds, 3)
            bakeReused = [bool]$workItem.bakeReused
            discoveryAttempts = ([int]$workItem.discoveryAttemptCount + [int](Get-ObjectProperty -Object $jobResult -Name "discoveryAttemptCount"))
            bakeAttempts = [int](Get-ObjectProperty -Object $jobResult -Name "bakeAttemptCount")
            selection = $selectionTimingSummary
        }
    }
}

function Test-UsefulProgressLogLine {
    param([string]$Line)

    if ([string]::IsNullOrWhiteSpace($Line)) {
        return $false
    }
    $usefulPatterns = @(
        "initial discovery attempt",
        "bake stage started",
        "using pre-discovered candidates",
        "discovery attempt",
        "bake attempt",
        "\[bake-and-rank\] candidate .* starting$",
        "\[bake-and-rank\] candidate .* status=",
        "\[bake-and-rank\] candidate .* rejected_",
        "\[bake-and-rank\] candidate .* accepted score=",
        "\[bake-and-rank\] candidate skipped:",
        "\[bake-and-rank\] candidate .* selected",
        "\[bake-and-rank\] source family blocked",
        "\[bake-and-rank\] Stopped after",
        "Checking source videos",
        "Extracting motion",
        "Extracted motion for",
        "Reviewing .* generated movement",
        "Batch finished:",
        "\[youtube\] full download attempt",
        "rejections=\d+/\d+",
        "selected \d+/\d+ result",
        "no recommended candidates",
        "no selected Wear skeleton",
        "finished with exit code",
        "returned exit code",
        "retrying .* after transient",
        "failed",
        "Traceback",
        "Exception",
        "ERROR"
    )
    foreach ($pattern in $usefulPatterns) {
        if ($Line -match $pattern) {
            return $true
        }
    }
    return $false
}

function Get-LatestUsefulLogLine {
    param(
        [string]$Path,
        [switch]$Detailed
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $lines = @(Get-Content -LiteralPath $Path -Tail 80 -ErrorAction SilentlyContinue)
    for ($index = $lines.Count - 1; $index -ge 0; $index -= 1) {
        $line = [string]$lines[$index]
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            $trimmed = $line.Trim()
            if ($Detailed) {
                return $trimmed
            }
            if (Test-UsefulProgressLogLine -Line $trimmed) {
                return $trimmed
            }
        }
    }
    return $null
}

function Write-LiveLogUpdates {
    param([object[]]$RunningJobs)

    foreach ($job in $RunningJobs) {
        $isStagedWave = $job.PSObject.Properties.Name -contains "IsStagedWave" -and $job.IsStagedWave
        if ($isStagedWave) {
            continue
        }
        $path = [string]$job.WorkItem.logPath
        $latestLine = Get-LatestUsefulLogLine -Path $path
        if (-not $latestLine) {
            continue
        }
        if ($script:LiveLogStateByPath.ContainsKey($path) -and $script:LiveLogStateByPath[$path] -eq $latestLine) {
            continue
        }
        $script:LiveLogStateByPath[$path] = $latestLine
        $script:LastProgressDetailByLogPath[$path] = $latestLine
        Write-Host ("  {0}: {1}" -f $job.WorkItem.exerciseName, $latestLine)
    }
}

function Get-RunningJobExerciseNames {
    param([object]$Job)

    if ($Job.PSObject.Properties.Name -contains "WorkItem" -and $null -ne $Job.WorkItem) {
        return @($Job.WorkItem.exerciseName)
    }
    if ($Job.PSObject.Properties.Name -contains "WorkItems" -and $null -ne $Job.WorkItems) {
        return @($Job.WorkItems | ForEach-Object { $_.exerciseName })
    }
    return @()
}

function Format-CompactElapsed {
    param([timespan]$Elapsed)

    if ($Elapsed.TotalSeconds -lt 0) {
        $Elapsed = [timespan]::Zero
    }
    if ($Elapsed.TotalHours -ge 1) {
        return "{0}h {1:D2}m" -f [int][Math]::Floor($Elapsed.TotalHours), $Elapsed.Minutes
    }
    if ($Elapsed.TotalMinutes -ge 1) {
        return "{0}m {1:D2}s" -f [int][Math]::Floor($Elapsed.TotalMinutes), $Elapsed.Seconds
    }
    return "{0}s" -f [int][Math]::Floor($Elapsed.TotalSeconds)
}

function Get-StagedWaveActivityText {
    param([object]$Job, [switch]$IncludeWorkerDetails)

    if (-not ($Job.PSObject.Properties.Name -contains "IsStagedWave") -or -not $Job.IsStagedWave) {
        return $null
    }
    $checkpointPath = Join-Path $Job.WaveWorkspace "staged_wave_checkpoint.json"
    $itemCount = if ($Job.PSObject.Properties.Name -contains "WorkItems") { @($Job.WorkItems).Count } else { 0 }
    if (-not (Test-Path -LiteralPath $checkpointPath)) {
        if ($itemCount -gt 0) {
            return "Starting batch of $itemCount exercises"
        }
        return "Starting batch"
    }
    try {
        $checkpoint = Get-Content -LiteralPath $checkpointPath -Raw | ConvertFrom-ReconstructionJson
        $items = @($checkpoint.items)
        $latestName = [string](Get-ObjectProperty -Object $checkpoint -Name "latestExerciseName")
        $latestSuffix = if (-not [string]::IsNullOrWhiteSpace($latestName)) { " — $latestName" } else { "" }
        switch ("$($checkpoint.stage)") {
            "source_validation" {
                $finished = @($items | Where-Object { "$($_.source.status)" -ne "pending" }).Count
                $usable = @($items | Where-Object { "$($_.source.status)" -eq "prepared" }).Count
                $failed = @($items | Where-Object { "$($_.source.status)" -eq "failed" }).Count
                $workerCount = [int](Get-ObjectProperty -Object $checkpoint.metrics -Name "sourceValidationWorkers")
                $meta = @()
                if ($usable -gt 0) { $meta += "$usable ok" }
                if ($failed -gt 0) { $meta += "$failed fail" }
                if ($workerCount -gt 0) { $meta += "$workerCount lanes" }
                $metaText = if ($meta.Count -gt 0) { " ($($meta -join ', '))" } else { "" }
                $workText = ''
                if ($IncludeWorkerDetails) {
                    $active = @($items | Where-Object {
                        $null -ne (Get-ObjectProperty -Object $_ -Name 'sourceActivity')
                    } | Sort-Object { $_.sourceActivity.startedAt })
                    if ($active.Count -gt 0) {
                        $oldest = $active[0]
                        $age = [DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($oldest.sourceActivity.startedAt)
                        $duration = Format-CompactElapsed -Elapsed $age
                        $video = Get-ObjectProperty -Object $oldest.sourceActivity -Name 'videoId'
                        $op = Get-ObjectProperty -Object $oldest.sourceActivity -Name 'operation'
                        if ([string]::IsNullOrWhiteSpace("$op")) { $op = 'source check' }
                        $op = ("$op" -replace '^preparing and validating source video$', 'prepare/validate' `
                            -replace '^checking source candidates$', 'check candidates')
                        $workText = " | $($active.Count) active: $($oldest.exerciseName)"
                        if ($video) { $workText += " /$video" }
                        $workText += " · $op · $duration"
                    }
                }
                return "Checking sources: $finished/$($items.Count)$metaText$latestSuffix$workText"
            }
            "generation_and_validation" {
                $extracted = @($items | Where-Object { "$($_.reconstruction.status)" -eq 'prepared' }).Count
                $reviewed = @($items | Where-Object { "$($_.finalValidation.status)" -notin @('', 'pending') }).Count
                $kept = @($items | Where-Object { "$($_.status)" -eq 'completed' }).Count
                $active = @($items | Where-Object { $null -ne (Get-ObjectProperty -Object $_ -Name 'finalValidationActivity') }).Count
                return "Processing: $extracted/$($items.Count) extracted | $reviewed reviewed | $kept ready | $active validating"
            }
            "reconstruction_generation" {
                $eligible = @($items | Where-Object { "$($_.source.status)" -eq "prepared" })
                $finished = @($eligible | Where-Object { "$($_.reconstruction.status)" -ne "pending" }).Count
                $failed = @($eligible | Where-Object { "$($_.reconstruction.status)" -eq "failed" }).Count
                $stillRunning = [Math]::Max(0, $eligible.Count - $finished)
                $bits = @("$finished/$($eligible.Count) done")
                if ($failed -gt 0) { $bits += "$failed fail" }
                if ($stillRunning -gt 0) { $bits += "$stillRunning run" }
                return "Extracting: $($bits -join ', ')$latestSuffix"
            }
            "reconstruction_released" {
                $eligible = @($items | Where-Object { "$($_.source.status)" -eq "prepared" })
                $ready = @($eligible | Where-Object { "$($_.reconstruction.status)" -eq "prepared" }).Count
                return "Extraction done ($ready ready) → validate"
            }
            "final_validation" {
                $eligible = @($items | Where-Object { "$($_.reconstruction.status)" -eq "prepared" })
                $finished = @($eligible | Where-Object {
                    $status = "$($_.finalValidation.status)"
                    $status -ne "" -and $status -ne "pending"
                }).Count
                $selected = @($eligible | Where-Object { "$($_.finalValidation.status)" -eq "selected" }).Count
                $manualReview = @($eligible | Where-Object { "$($_.finalValidation.status)" -eq "needs_manual_review" }).Count
                $incomplete = @($eligible | Where-Object { "$($_.finalValidation.status)" -eq "incomplete_processing" }).Count
                $failed = @($eligible | Where-Object { "$($_.finalValidation.status)" -in @("failed", "no_selection") }).Count
                $pending = @($eligible | Where-Object {
                    $status = "$($_.finalValidation.status)"
                    $status -eq "" -or $status -eq "pending"
                })
                $workerCount = [int](Get-ObjectProperty -Object $checkpoint.metrics -Name "finalValidationWorkers")
                $budget = Get-ObjectProperty -Object $checkpoint.metrics -Name "resourceBudget"
                $fitSlots = [int](Get-ObjectProperty -Object $budget -Name "cpuFitSlots")
                if ($fitSlots -le 0) {
                    $fitSlots = [int](Get-ObjectProperty -Object $checkpoint.metrics -Name "finalValidationFitSlots")
                }
                $meta = @()
                if ($selected -gt 0) { $meta += "$selected keep" }
                if ($manualReview -gt 0) { $meta += "$manualReview manual review" }
                if ($incomplete -gt 0) { $meta += "$incomplete incomplete" }
                if ($failed -gt 0) { $meta += "$failed fail" }
                if ($workerCount -gt 0 -and $fitSlots -gt 0) { $meta += "$workerCount lanes/$fitSlots fit" }
                elseif ($workerCount -gt 0) { $meta += "$workerCount lanes" }
                elseif ($fitSlots -gt 0) { $meta += "$fitSlots fit" }
                $metaText = if ($meta.Count -gt 0) { " ($($meta -join ', '))" } else { "" }
                $workText = ''
                if ($IncludeWorkerDetails -and $pending.Count -gt 0) {
                    $running = @($pending | Where-Object {
                        $activity = Get-ObjectProperty -Object $_ -Name 'finalValidationActivity'
                        if ($null -eq $activity) { return $false }
                        $operation = "$(Get-ObjectProperty -Object $activity -Name 'operation')"
                        $operation -ne '' -and $operation -ne 'wait lane'
                    } | Sort-Object {
                        $updated = Get-ObjectProperty -Object $_.finalValidationActivity -Name 'updatedAt'
                        if ([string]::IsNullOrWhiteSpace("$updated")) {
                            "$($_.finalValidationActivity.startedAt)"
                        } else {
                            "$updated"
                        }
                    })
                    $queued = [Math]::Max(0, $pending.Count - $running.Count)
                    if ($running.Count -gt 0) {
                        $oldest = $running[0]
                        $startedAt = Get-ObjectProperty -Object $oldest.finalValidationActivity -Name 'startedAt'
                        $ageText = ''
                        if (-not [string]::IsNullOrWhiteSpace("$startedAt")) {
                            $age = [DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($startedAt)
                            $ageText = " · $(Format-CompactElapsed -Elapsed $age)"
                        }
                        $operation = Get-ObjectProperty -Object $oldest.finalValidationActivity -Name 'operation'
                        if ([string]::IsNullOrWhiteSpace("$operation")) { $operation = 'bake/fit/review' }
                        $operation = ("$operation" `
                            -replace '^waiting for a final-validation worker$', 'wait lane' `
                            -replace '^queued for final bake and review$', 'start' `
                            -replace '^releasing unfinished speculative prefetch$', 'drop prefetch' `
                            -replace '^baking, fitting loops, and model review$', 'bake/fit/review' `
                            -replace '^baking and fitting$', 'bake/fit' `
                            -replace '^incomplete fit; trying next candidate$', 'fit incomplete→next' `
                            -replace '^candidate finished; continuing review$', 'next step' `
                            -replace '^model review$', 'review')
                        $detail = Get-ObjectProperty -Object $oldest.finalValidationActivity -Name 'detail'
                        $shortDetail = ''
                        if ("$detail" -match 'candidate\s+(\d+/\S+)') { $shortDetail = "cand $($Matches[1])" }
                        elseif ("$detail" -match 'status=([^\s]+)') { $shortDetail = "$($Matches[1])" }
                        $workText = " | $($running.Count) active"
                        if ($queued -gt 0) { $workText += ", $queued wait" }
                        $workText += ": $($oldest.exerciseName)$ageText · $operation"
                        if ($shortDetail) { $workText += " · $shortDetail" }
                    } else {
                        $names = @($pending | Select-Object -First 3 | ForEach-Object { $_.exerciseName }) -join ', '
                        $more = if ($pending.Count -gt 3) { " +$($pending.Count - 3)" } else { "" }
                        $workText = " | $($pending.Count) pending: $names$more"
                    }
                }
                return "Validating: $finished/$($eligible.Count)$metaText$workText"
            }
            "completed" {
                $completed = @($items | Where-Object { "$($_.status)" -eq "completed" }).Count
                return "Batch done: $completed/$($items.Count) kept"
            }
            default {
                $stageName = "$($checkpoint.stage)".Replace("_", " ")
                return "Batch $stageName$latestSuffix"
            }
        }
    } catch {
        return $null
    }
}

function Get-StagedWaveProgressLine {
    param([object]$Job)

    $activity = Get-StagedWaveActivityText -Job $Job
    if ([string]::IsNullOrWhiteSpace($activity)) {
        return $null
    }
    return "{0}." -f $activity.TrimEnd(".")
}

# Reads the stage field of a staged wave's checkpoint file for the drain
# loop's wave-overlap admission check. Uses an mtime-based cache (same
# pattern as Write-StagedWaveProgressUpdates) so polling every loop
# iteration stays cheap; the wave's 30s checkpoint heartbeat rewrites the
# file with the same stage, which the cache absorbs.
# Returns $null for non-wave jobs. Returns an empty string when no checkpoint
# exists yet or it cannot be parsed: a wave that just started has not written
# one, so callers must treat that as the earliest (overlap-blocking) stage.
function Get-StagedWaveCheckpointStage {
    param([object]$Job)

    if (-not ($Job.PSObject.Properties.Name -contains "IsStagedWave") -or -not $Job.IsStagedWave) {
        return $null
    }
    $checkpointPath = Join-Path $Job.WaveWorkspace "staged_wave_checkpoint.json"
    if (-not (Test-Path -LiteralPath $checkpointPath)) {
        return ""
    }
    $checkpointVersion = (Get-Item -LiteralPath $checkpointPath).LastWriteTimeUtc.Ticks
    $cachedStage = $script:StagedWaveCheckpointStageCacheByPath[$checkpointPath]
    if ($null -ne $cachedStage -and $cachedStage.version -eq $checkpointVersion) {
        return "$($cachedStage.stage)"
    }
    try {
        $checkpoint = Get-Content -LiteralPath $checkpointPath -Raw | ConvertFrom-ReconstructionJson
        $stage = "$($checkpoint.stage)"
        $script:StagedWaveCheckpointStageCacheByPath[$checkpointPath] = @{
            version = $checkpointVersion
            stage = $stage
        }
        return $stage
    } catch {
        return ""
    }
}

# Counts running jobs flagged with a boolean note property (IsStagedWave,
# IsStagedCompletion). Shared by the drain loop's lane accounting so the
# wave and completion budgets stay independent of each other.
function Get-FlaggedJobCount {
    param(
        [object[]]$Jobs,
        [string]$FlagPropertyName
    )

    if ($Jobs.Count -eq 0) {
        return 0
    }
    return @($Jobs | Where-Object {
        $_.PSObject.Properties.Name -contains $FlagPropertyName -and
        [bool]$_.PSObject.Properties[$FlagPropertyName].Value
    }).Count
}

# Wave-overlap admission (MaxConcurrentStagedWaves). A new staged wave may
# start only while:
#   - every running staged wave is parked in cpu_preparation (CPU-only
#     fits; source_validation and reconstruction_generation would oversubscribe the
#     per-process CPU fit lanes or contend for the exclusive GPU), and
#   - the running staged wave count is below the overlap cap, and
#   - no full GPU-capable pipeline (legacy fallback bake) is queued or
#     running, keeping those exclusive.
# Trivial staged completion jobs never block admission; they run in their own
# bounded lane. With a cap of 1 this reduces to today's serialized behavior
# except that in-flight completion jobs no longer hold back the next wave.
function Test-VerifiedExclusiveGpuSplitPlacement {
    param([string]$Device, [string[]]$GpuRows)

    if ($Device -notmatch '^[1-9]\d*$') { return $false }
    $gpuUuids = @{}
    foreach ($gpuRow in $GpuRows) {
        $parts = ([string]$gpuRow).Split(',', 2)
        if ($parts.Count -eq 2) {
            $index = $parts[0].Trim()
            $uuid = $parts[1].Trim()
            if (-not [string]::IsNullOrWhiteSpace($uuid)) { $gpuUuids[$index] = $uuid }
        }
    }
    return (
        $gpuUuids.ContainsKey('0') -and $gpuUuids.ContainsKey($Device) -and
        $gpuUuids['0'] -ne $gpuUuids[$Device]
    )
}

function Test-StagedWaveOverlapAdmission {
    param(
        [object[]]$BakeRunningJobs,
        [int]$PendingLegacyBakeItemCount,
        [int]$MaxConcurrentStagedWaves
    )

    $stagedWaveJobs = @($BakeRunningJobs | Where-Object {
        $_.PSObject.Properties.Name -contains "IsStagedWave" -and $_.IsStagedWave
    })
    $fullPipelineBakeJobs = @($BakeRunningJobs | Where-Object {
        -not ($_.PSObject.Properties.Name -contains "IsStagedWave" -and $_.IsStagedWave) -and
        -not ($_.PSObject.Properties.Name -contains "IsStagedCompletion" -and $_.IsStagedCompletion)
    })
    $allWavesInFinalValidation = $true
    foreach ($stagedWaveJob in $stagedWaveJobs) {
        if ("$(Get-StagedWaveCheckpointStage -Job $stagedWaveJob)" -notin @("cpu_preparation", "generation_and_validation")) {
            $allWavesInFinalValidation = $false
            break
        }
    }
    $admitted = (
        $stagedWaveJobs.Count -lt $MaxConcurrentStagedWaves -and
        $allWavesInFinalValidation -and
        $fullPipelineBakeJobs.Count -eq 0 -and
        $PendingLegacyBakeItemCount -eq 0
    )
    return [pscustomobject]@{
        admitted = $admitted
        runningStagedWaveCount = $stagedWaveJobs.Count
    }
}

function Receive-StagedWaveReadyItems {
    param([object[]]$RunningJobs, [System.Collections.Queue]$CompletionQueue)

    foreach ($job in $RunningJobs) {
        if (-not ($job.PSObject.Properties.Name -contains 'IsStagedWave') -or -not $job.IsStagedWave) { continue }
        $checkpointPath = Join-Path $job.WaveWorkspace 'staged_wave_checkpoint.json'
        if (-not (Test-Path -LiteralPath $checkpointPath -PathType Leaf)) { continue }
        try {
            $checkpointFile = Get-Item -LiteralPath $checkpointPath
            $checkpointVersion = "$($checkpointFile.LastWriteTimeUtc.Ticks)/$($checkpointFile.Length)"
            if ($job.PSObject.Properties.Name -contains 'ReadyCheckpointVersion' -and
                $job.ReadyCheckpointVersion -eq $checkpointVersion) { continue }
            $checkpoint = Get-Content -LiteralPath $checkpointPath -Raw | ConvertFrom-ReconstructionJson
        } catch { continue }
        if (-not ($job.PSObject.Properties.Name -contains 'CompletedExerciseIds')) {
            $job | Add-Member -MemberType NoteProperty -Name CompletedExerciseIds -Value @{}
        }
        foreach ($state in @($checkpoint.items)) {
            $exerciseId = "$($state.exerciseId)"
            if ("$($state.status)" -ne 'completed' -or $job.CompletedExerciseIds.ContainsKey($exerciseId)) { continue }
            $workItem = @($job.WorkItems | Where-Object { "$($_.exerciseId)" -eq $exerciseId }) | Select-Object -First 1
            if ($null -eq $workItem) { continue }
            Add-StagedWaveTimelineOutcome -WorkItem $workItem -WaveState $state
            $CompletionQueue.Enqueue($workItem)
            $job.CompletedExerciseIds[$exerciseId] = $true
        }
        $job | Add-Member -MemberType NoteProperty -Name ReadyCheckpointVersion -Value $checkpointVersion -Force
    }
}

function Write-StagedWaveProgressUpdates {
    param([object[]]$RunningJobs)

    foreach ($job in $RunningJobs) {
        if (-not ($job.PSObject.Properties.Name -contains "IsStagedWave") -or -not $job.IsStagedWave) {
            continue
        }
        $checkpointPath = Join-Path $job.WaveWorkspace "staged_wave_checkpoint.json"
        if (-not (Test-Path -LiteralPath $checkpointPath)) {
            continue
        }
        $checkpointVersion = (Get-Item -LiteralPath $checkpointPath).LastWriteTimeUtc.Ticks
        if (
            $script:LastStagedWaveCheckpointVersionByPath.ContainsKey($checkpointPath) -and
            $script:LastStagedWaveCheckpointVersionByPath[$checkpointPath] -eq $checkpointVersion
        ) {
            continue
        }
        $script:LastStagedWaveCheckpointVersionByPath[$checkpointPath] = $checkpointVersion
        try {
            $checkpoint = Get-Content -LiteralPath $checkpointPath -Raw | ConvertFrom-ReconstructionJson
            $events = @(Get-ObjectProperty -Object $checkpoint.metrics -Name 'sourceAttemptEvents')
            $eventKey = "$checkpointPath/source-attempts"
            $seen = if ($script:LastStagedWaveCheckpointVersionByPath.ContainsKey($eventKey)) {
                [int]$script:LastStagedWaveCheckpointVersionByPath[$eventKey]
            } else { 0 }
            for ($index = $seen; $index -lt $events.Count; $index++) {
                if ($events[$index]) { Write-Host $events[$index] }
            }
            $script:LastStagedWaveCheckpointVersionByPath[$eventKey] = $events.Count
        } catch { Write-Verbose "Source attempt events are not available yet." }
        $progressLine = Get-StagedWaveProgressLine -Job $job
        if ($progressLine) {
            Write-Host ("  {0}" -f $progressLine)
        }
    }
}

function Initialize-ExerciseRunLog {
    param(
        [string]$Path,
        [string]$RunId
    )

    $logDirectory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    if (Test-Path -LiteralPath $Path) {
        $historyDirectory = Join-Path $logDirectory "log_history"
        New-Item -ItemType Directory -Force -Path $historyDirectory | Out-Null
        $historyName = "bake.{0}.{1}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss-fff"), $RunId
        Copy-Item -LiteralPath $Path -Destination (Join-Path $historyDirectory $historyName)
    }
    "[$(Get-Date -Format o)] workout-plan movement run started; run id $RunId" |
        Set-Content -LiteralPath $Path -Encoding UTF8
}

function Write-ProgressSnapshot {
    param(
        [string]$Stage = "movement generation",
        [datetime]$StartedAt = [datetime]::MinValue,
        [object[]]$RunningJobs,
        [int]$SuccessfulCount,
        [int]$UnsuccessfulCount,
        [int]$ProcessedCount,
        [int]$TotalCount,
        [int]$PendingCount,
        [switch]$DetailedLogs
    )

    $activeNames = @(
        $RunningJobs |
            ForEach-Object { Get-RunningJobExerciseNames -Job $_ } |
            Select-Object -Unique
    )
    $elapsedText = ""
    if ($StartedAt -ne [datetime]::MinValue) {
        $elapsedText = " after {0}." -f (Format-CompactElapsed -Elapsed ((Get-Date) - $StartedAt))
    }
    $remainingCount = [Math]::Max(0, $TotalCount - $ProcessedCount - $activeNames.Count)
    $status = "{0}/{1} movements ready" -f $SuccessfulCount, $TotalCount
    if ($UnsuccessfulCount -gt 0) {
        $status += ", $UnsuccessfulCount unresolved"
    }
    if ($remainingCount -gt 0) {
        $status += ", $remainingCount remaining"
    }
    $activityTexts = @(
        $RunningJobs |
            ForEach-Object { Get-StagedWaveActivityText -Job $_ -IncludeWorkerDetails } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($activityTexts.Count -gt 0) {
        $status += ". " + ($activityTexts -join "; ")
    } elseif ($activeNames.Count -gt 0) {
        $shownNames = @($activeNames | Select-Object -First 3)
        $nameText = $shownNames -join ", "
        if ($activeNames.Count -gt $shownNames.Count) {
            $nameText += ", and $($activeNames.Count - $shownNames.Count) more"
        }
        $status += ". Generating: $nameText"
    }
    Write-Host ($status + $elapsedText.TrimEnd(".") + ".")
    if ($DetailedLogs -and $activeNames.Count -gt 0) {
        Write-Host ("  active: {0}" -f ($activeNames -join ", "))
    }
    if (-not $DetailedLogs) {
        return
    }
    foreach ($job in $RunningJobs) {
        $isStagedWave = $job.PSObject.Properties.Name -contains "IsStagedWave" -and $job.IsStagedWave
        $logPath = if ($isStagedWave) {
            Join-Path $job.WaveWorkspace "wave.log"
        } else {
            $job.WorkItem.logPath
        }
        $latestLine = Get-LatestUsefulLogLine -Path $logPath -Detailed
        if ($latestLine) {
            $label = if ($isStagedWave) { "batch" } else { $job.WorkItem.exerciseName }
            Write-Host ("  {0}: {1}" -f $label, $latestLine)
        }
    }
}

$repoRoot = Get-RepoRoot
$script:MotionSourceIdentity = Get-MotionSourceIdentity -RepoRoot $repoRoot
Assert-MotionSourceIdentity `
    -Identity $script:MotionSourceIdentity `
    -AllowDirtyWorktree:$AllowDirtyWorktree
$script:MotionSourceIdentityFingerprint = @(
    [string]$script:MotionSourceIdentity.schemaVersion,
    [string]$script:MotionSourceIdentity.gitCommit,
    [string]$script:MotionSourceIdentity.gitStatusSha256,
    [string]$script:MotionSourceIdentity.gitTrackedDiffSha256,
    [string]$script:MotionSourceIdentity.gitUntrackedContentSha256,
    [string]$script:MotionSourceIdentity.gitSubmoduleWorktreeSha256
) -join ":"
$PythonCommand = Resolve-MotionPythonCommand $PythonCommand
switch ($SpeedProfile) {
    "fast" {
        if (-not $PSBoundParameters.ContainsKey("ResultsPerQuery")) { $ResultsPerQuery = 100 }
        if (-not $PSBoundParameters.ContainsKey("MaxCandidates")) { $MaxCandidates = 24 }
        if (-not $PSBoundParameters.ContainsKey("CandidateReviewBatchSize")) { $CandidateReviewBatchSize = 4 }
        if (-not $PSBoundParameters.ContainsKey("CandidateReviewTargetSuitableCount")) { $CandidateReviewTargetSuitableCount = 2 }
        if (-not $PSBoundParameters.ContainsKey("MaxCandidateReviewTargetSuitableCount")) { $MaxCandidateReviewTargetSuitableCount = $null }
        if (-not $PSBoundParameters.ContainsKey("VisionCandidatesPerExercise")) { $VisionCandidatesPerExercise = 12 }
        if (-not $PSBoundParameters.ContainsKey("VisionMaxChunksPerCandidate")) { $VisionMaxChunksPerCandidate = 2 }
        if (-not $PSBoundParameters.ContainsKey("PosePrefilterCandidatesPerExercise")) { $PosePrefilterCandidatesPerExercise = 24 }
        if (-not $PSBoundParameters.ContainsKey("FallbackCandidates")) { $FallbackCandidates = 6 }
        if (-not $PSBoundParameters.ContainsKey("MaxSourceWindowAttempts")) { $MaxSourceWindowAttempts = 0 }
        if (-not $PSBoundParameters.ContainsKey("MaxFinalOutputRejections")) { $MaxFinalOutputRejections = 0 }
        if (-not $PSBoundParameters.ContainsKey("NoExerciseNameRewrite")) { $NoExerciseNameRewrite = $true }
        if (-not $PSBoundParameters.ContainsKey("SemanticGateWithLlamaCpp") -and -not $PSBoundParameters.ContainsKey("SkipSemanticGate")) {
            $SemanticGateWithLlamaCpp = $true
        }
    }
    "max" {
        if (-not $PSBoundParameters.ContainsKey("MaxCandidates")) { $MaxCandidates = 6 }
        if (-not $PSBoundParameters.ContainsKey("CandidateReviewBatchSize")) { $CandidateReviewBatchSize = 4 }
        if (-not $PSBoundParameters.ContainsKey("CandidateReviewTargetSuitableCount")) { $CandidateReviewTargetSuitableCount = 2 }
        if (-not $PSBoundParameters.ContainsKey("MaxCandidateReviewTargetSuitableCount")) { $MaxCandidateReviewTargetSuitableCount = $null }
        if (-not $PSBoundParameters.ContainsKey("VisionCandidatesPerExercise")) { $VisionCandidatesPerExercise = 6 }
        if (-not $PSBoundParameters.ContainsKey("PosePrefilterCandidatesPerExercise")) { $PosePrefilterCandidatesPerExercise = 6 }
        if (-not $PSBoundParameters.ContainsKey("FallbackCandidates")) { $FallbackCandidates = 2 }
        if (-not $PSBoundParameters.ContainsKey("ReviewFrames")) { $ReviewFrames = 4 }
    }
}
if (
    -not $PSBoundParameters.ContainsKey("UseLlamaCppQueryPlanner") -and
    -not $PSBoundParameters.ContainsKey("SkipLlamaCppQueryPlanner") -and
    -not $PSBoundParameters.ContainsKey("UseDeepSeekQueryPlanner")
) {
    $UseLlamaCppQueryPlanner = $true
}
if ($SkipTwoScaleSourceValidation) {
    $TwoScaleSourceValidation = $false
} elseif (-not $PSBoundParameters.ContainsKey("TwoScaleSourceValidation")) {
    $TwoScaleSourceValidation = $true
}

function Set-CommandArgumentValue {
    param(
        [string[]]$Arguments,
        [string]$Name,
        [string]$Value
    )

    $result = @()
    $found = $false
    for ($index = 0; $index -lt $Arguments.Count; $index += 1) {
        if ($Arguments[$index] -eq $Name) {
            $result += @($Name, $Value)
            $found = $true
            $index += 1
            continue
        }
        $result += $Arguments[$index]
    }
    if (-not $found) {
        $result += @($Name, $Value)
    }
    return [string[]]$result
}
if ($DeferAfterFirstAttempt) {
    $CandidateReviewTargetSuitableCount = 1
    $MaxCandidateReviewTargetSuitableCount = 1
    $FallbackCandidates = 0
    $MaxFinalOutputRejections = 0
    # Keep discovery breadth (single suitable source target), but allow one
    # orientation-diverse reconstruction fallback in the same staged wave.
    $MaxReconstructionCandidateAttempts = 2
    $CandidateWorkers = 1
}
if ($PSBoundParameters.ContainsKey("LlamaCppCtxSize") -and -not $PSBoundParameters.ContainsKey("LlamaCppFitCtx")) {
    $LlamaCppFitCtx = $LlamaCppCtxSize
}
Ensure-LlamaCppParallelContext
$llamaParallelSlots = if ($null -ne $LlamaCppParallel) { [Math]::Max(1, [int]$LlamaCppParallel) } else { 1 }
$visionLlmWorkersExplicit = $PSBoundParameters.ContainsKey("VisionLlmWorkers")
if (-not $PSBoundParameters.ContainsKey("ReviewLlmWorkers")) {
    $ReviewLlmWorkers = [Math]::Max(1, $llamaParallelSlots)
}
if (-not $PSBoundParameters.ContainsKey("SegmentClassificationWorkers")) {
    $SegmentClassificationWorkers = [Math]::Max(1, $llamaParallelSlots)
}
if (-not $PSBoundParameters.ContainsKey("SemanticGateLlmWorkers")) {
    $SemanticGateLlmWorkers = [Math]::Max(1, $llamaParallelSlots)
}
if (-not $PSBoundParameters.ContainsKey("VisionDownloadWorkers")) {
    $VisionDownloadWorkers = [Math]::Max(8, [Math]::Min(16, $llamaParallelSlots * 2))
}
$resolvedWorkoutPlanJson = Resolve-StrictPath $WorkoutPlanJson
if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $EquipmentJson = Resolve-StrictPath $EquipmentJson
}
$recoveredExclusions = Add-UnboundExclusionArguments `
    -WorkspaceRoots $ExcludeCandidatesFromWorkspaceRoot `
    -CandidateJsonPaths $ExcludeYoutubeCandidatesJson `
    -VideoIds $ExcludeYoutubeVideoId `
    -Urls $ExcludeYoutubeUrl `
    -UnboundArguments $RemainingArguments
$ExcludeCandidatesFromWorkspaceRoot = $recoveredExclusions.workspaceRoots
$ExcludeYoutubeCandidatesJson = $recoveredExclusions.candidateJsonPaths
$ExcludeYoutubeVideoId = $recoveredExclusions.videoIds
$ExcludeYoutubeUrl = $recoveredExclusions.urls
$resolvedExcludeCandidatesFromWorkspaceRoot = Resolve-StrictPathList -PathValues $ExcludeCandidatesFromWorkspaceRoot
$resolvedExcludeYoutubeCandidatesJson = Resolve-StrictPathList -PathValues $ExcludeYoutubeCandidatesJson
$onlyExerciseSlugSet = ConvertTo-SlugSet -Values $OnlyExerciseSlug
$onlyExerciseIdSet = ConvertTo-StringSet -Values $OnlyExerciseId
$onlyExerciseNameSet = ConvertTo-StringSet -Values $OnlyExerciseName
$hasExerciseFilter = (
    $onlyExerciseSlugSet.Count -gt 0 -or
    $onlyExerciseIdSet.Count -gt 0 -or
    $onlyExerciseNameSet.Count -gt 0
)

# Resolve target definitions before creating workspace state or starting any
# GPU-backed service. The per-exercise plans below are emitted from this
# enriched list; sourcePlanPath and package export still point at the original.
$resolvedApprovedExerciseDefinitionsJson = $null
if (-not [string]::IsNullOrWhiteSpace($ApprovedExerciseDefinitionsJson)) {
    $resolvedApprovedExerciseDefinitionsJson = Resolve-StrictPath $ApprovedExerciseDefinitionsJson
}
$definitionPreflightDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("exercise-motion-definition-preflight-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $definitionPreflightDirectory | Out-Null
$definitionPreflightListPath = Join-Path $definitionPreflightDirectory "workout_plan_exercises.json"
$definitionPreflightEffectivePlanPath = Join-Path $definitionPreflightDirectory "effective_workout_plan.json"
$definitionPreflightReportPath = Join-Path $definitionPreflightDirectory "definition_readiness_report.json"
$listArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "list-workout-plan-exercises",
    "--workout-plan-json", $resolvedWorkoutPlanJson,
    "--definition-effective-plan-json", $definitionPreflightEffectivePlanPath,
    "--definition-readiness-report-json", $definitionPreflightReportPath,
    "--source-budget-workspace-root", ([System.IO.Path]::GetFullPath($WorkspaceRoot)),
    "--source-review-timeout-seconds", "$SourceReviewTimeoutSeconds",
    "--exercise-timeout-seconds", "$ExerciseTimeoutSeconds",
    "--max-source-window-attempts", "$MaxSourceWindowAttempts",
    "--out-json", $definitionPreflightListPath
)
if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $listArgs += @("--equipment-json", $EquipmentJson)
}
if ($IncludeDisabled) {
    $listArgs += "--include-disabled"
}
if ($resolvedApprovedExerciseDefinitionsJson) {
    $listArgs += @("--approved-exercise-definitions-json", $resolvedApprovedExerciseDefinitionsJson)
}
Invoke-PythonModule -Arguments $listArgs
$exerciseList = Get-Content -LiteralPath $definitionPreflightListPath -Raw | ConvertFrom-Json
if (-not $exerciseList.exercises -or $exerciseList.exercises.Count -eq 0) {
    throw "No exercises were found in the workout plan: $resolvedWorkoutPlanJson"
}

$selectedDefinitionExerciseCount = 0
$readyDefinitionExerciseCount = 0
$readySourceReviewBudgetExerciseCount = 0
$preflightSlugCounts = @{}
foreach ($exercise in $exerciseList.exercises) {
    $exerciseName = [string]($exercise.exerciseName ?? $exercise.name ?? $exercise.id ?? "exercise")
    $exerciseId = [string]($exercise.exerciseId ?? $exercise.id ?? (ConvertTo-Slug $exerciseName))
    $sourceExerciseName = [string]($exercise.sourceExerciseName ?? "")
    $equipmentQualifiedExerciseName = [string]($exercise.equipmentQualifiedExerciseName ?? "")
    $exerciseSlug = ConvertTo-Slug ([string]($exercise.slug ?? $exerciseId ?? $exerciseName))
    if ($preflightSlugCounts.ContainsKey($exerciseSlug)) {
        $preflightSlugCounts[$exerciseSlug] += 1
        $exerciseSlug = "$exerciseSlug-$($preflightSlugCounts[$exerciseSlug])"
    } else {
        $preflightSlugCounts[$exerciseSlug] = 1
    }
    $matchesFilter = -not $hasExerciseFilter
    if ($hasExerciseFilter) {
        $nameKeys = @($exerciseName, $sourceExerciseName, $equipmentQualifiedExerciseName) |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { $_.Trim().ToLowerInvariant() }
        $slugKeys = @($exerciseSlug)
        foreach ($slugName in @($sourceExerciseName, $equipmentQualifiedExerciseName)) {
            if (-not [string]::IsNullOrWhiteSpace($slugName)) { $slugKeys += ConvertTo-Slug $slugName }
        }
        $matchesFilter = $onlyExerciseIdSet.ContainsKey($exerciseId.Trim().ToLowerInvariant()) -or
            (@($nameKeys | Where-Object { $onlyExerciseNameSet.ContainsKey($_) }).Count -gt 0) -or
            (@($slugKeys | Where-Object { $onlyExerciseSlugSet.ContainsKey($_) }).Count -gt 0)
    }
    if (-not $matchesFilter) { continue }
    $selectedDefinitionExerciseCount += 1
    if ($exercise.definitionReadiness.status -eq "ready") {
        $readyDefinitionExerciseCount += 1
        if ($exercise.sourceReviewBudgetReadiness.ready -eq $true) {
            $readySourceReviewBudgetExerciseCount += 1
        }
    }
}
if ($selectedDefinitionExerciseCount -eq 0) {
    if ($hasExerciseFilter) {
        throw "No exercises matched the supplied OnlyExerciseSlug/OnlyExerciseId/OnlyExerciseName filters."
    }
    throw "No exercises were queued for movement generation."
}
$hasSelectedReadyDefinitionTargets = $readyDefinitionExerciseCount -gt 0
$hasSelectedReadySourceReviewTargets = $readySourceReviewBudgetExerciseCount -gt 0
$definitionReadinessReport = $exerciseList.definitionReadiness

if ($ExerciseWorkers -lt 1) {
    throw "ExerciseWorkers must be at least 1."
}
$posePrefilterEnabled = $PosePrefilter -or -not $SkipPosePrefilter
if ($posePrefilterEnabled -and $hasSelectedReadySourceReviewTargets) {
    $PosePrefilterDevice = Resolve-CudaPosePrefilterDevice $PosePrefilterDevice
}
$posePrefilterUsesGpu = $posePrefilterEnabled
$effectiveLlamaCppBackend = if ([string]::IsNullOrWhiteSpace($LlamaCppBackend)) { "gpu" } else { $LlamaCppBackend.Trim().ToLowerInvariant() }
$llamaCppDiscoveryUsesGpu = (
    ($effectiveLlamaCppBackend -ne "cpu") -and
    (
        -not $SkipVisionRanking -or
        ($SemanticGateWithLlamaCpp -or -not $SkipSemanticGate) -or
        ($UseLlamaCppQueryPlanner -and -not $SkipLlamaCppQueryPlanner -and -not $UseDeepSeekQueryPlanner)
    )
)
$gpuDiscoveryStages = @()
if ($posePrefilterUsesGpu) {
    $gpuDiscoveryStages += "yolo_pose_prefilter"
}
if ($llamaCppDiscoveryUsesGpu) {
    $gpuDiscoveryStages += "llama_cpp_discovery"
}
$discoveryUsesGpu = $gpuDiscoveryStages.Count -gt 0
$gpuLockSetting = "$env:EXERCISE_MOTION_GPU_LOCK".Trim().ToLowerInvariant()
$globalGpuLockEnabled = [string]::IsNullOrWhiteSpace($gpuLockSetting) -or $gpuLockSetting -notin @("0", "false", "off", "no")
$exclusiveGpuDevice = "$env:EXERCISE_MOTION_EXCLUSIVE_GPU_DEVICE".Trim()
$verifiedExclusiveGpuSplit = $false
if (
    $hasSelectedReadyDefinitionTargets -and $SharedLlamaServer -and $StagedWaveSize -gt 0 -and $globalGpuLockEnabled -and
    $exclusiveGpuDevice -match '^[1-9]\d*$'
) {
    $placementRows = @(& nvidia-smi --query-gpu=index,uuid --format=csv,noheader,nounits 2>$null)
    $verifiedExclusiveGpuSplit = Test-VerifiedExclusiveGpuSplitPlacement `
        -Device $exclusiveGpuDevice -GpuRows $placementRows
}
$effectiveGpuDiscoveryBakeOverlap = if (
    $SharedLlamaServer -and $StagedWaveSize -gt 0 -and
    ($MaxConcurrentStagedWaves -gt 1 -or $verifiedExclusiveGpuSplit) -and
    $GpuDiscoveryBakeOverlap -ne 'avoid'
) {
    # Shared discovery coordinates CUDA prefilter handoffs and counts VLM calls.
    # A verified exclusive lane also separates discovery/llama GPU 0 from
    # reconstruction GPU N, even when staged-wave concurrency remains one.
    'allow'
} elseif ($discoveryUsesGpu -and $globalGpuLockEnabled) {
    # The shared GPU lock serializes CUDA model residency across processes.
    # Scheduling both lanes together only makes one side wait while retaining
    # a resident llama.cpp session, which blocks the bake-side pose/source work.
    # Once a staged wave is ready, request a discovery checkpoint and let that
    # worker exit before launching the bake. CPU-only discovery can overlap.
    if ($GpuDiscoveryBakeOverlap -eq "allow") {
        Write-Warning "GPU discovery/bake overlap was requested, but the shared GPU lock is enabled. Serializing these stages avoids lock contention and model handoff stalls."
    }
    "avoid"
} elseif ($GpuDiscoveryBakeOverlap -eq "auto") {
    if ($discoveryUsesGpu) { "avoid" } else { "allow" }
} else {
    $GpuDiscoveryBakeOverlap
}
$avoidGpuDiscoveryBakeOverlap = $effectiveGpuDiscoveryBakeOverlap -eq "avoid"
$defaultDiscoveryWorkerCap = if ($posePrefilterUsesGpu) { 1 } else { 4 }
$resolvedDiscoveryWorkers = if ($null -ne $DiscoveryWorkers) { [int]$DiscoveryWorkers } else { [Math]::Max(1, [Math]::Min($defaultDiscoveryWorkerCap, $llamaParallelSlots)) }
$resolvedBakeWorkers = if ($null -ne $BakeWorkers) { [int]$BakeWorkers } else { 1 }
if ($resolvedDiscoveryWorkers -lt 1) {
    throw "DiscoveryWorkers must be at least 1."
}
if ($resolvedBakeWorkers -lt 1) {
    throw "BakeWorkers must be at least 1."
}
if ($PrefetchWorkers -lt 1) {
    throw "PrefetchWorkers must be at least 1."
}
if ($PrefetchQueueDepth -lt 1) {
    throw "PrefetchQueueDepth must be at least 1."
}
if ($StagedWaveSize -lt 0) {
    throw "StagedWaveSize must be 0 (disabled) or at least 1."
}
$stagedWavesEnabled = $StagedWaveSize -gt 0
if ($ProgressIntervalSeconds -lt 1) {
    throw "ProgressIntervalSeconds must be at least 1."
}
if ($CandidateReviewTargetSuitableCount -lt 1) {
    throw "CandidateReviewTargetSuitableCount must be at least 1."
}
if ($MaxSelectedResults -lt 1) {
    throw "MaxSelectedResults must be at least 1."
}
$resolvedMaxCandidateReviewTargetSuitableCount = if ($null -ne $MaxCandidateReviewTargetSuitableCount) {
    [Math]::Max([int]$MaxCandidateReviewTargetSuitableCount, $MaxSelectedResults)
} else {
    0
}
$initialTargetSuitableCount = [Math]::Max($CandidateReviewTargetSuitableCount, $MaxSelectedResults)
if ($resolvedMaxCandidateReviewTargetSuitableCount -gt 0 -and $resolvedMaxCandidateReviewTargetSuitableCount -lt $initialTargetSuitableCount) {
    throw "MaxCandidateReviewTargetSuitableCount must be greater than or equal to CandidateReviewTargetSuitableCount and MaxSelectedResults."
}

if ([string]::IsNullOrWhiteSpace($BodyModelRoot)) {
    $BodyModelRoot = Join-Path $repoRoot "third_party\GVHMR\inputs\checkpoints\body_models"
}

$resolvedBodyModelRoot = Resolve-StrictPath $BodyModelRoot

function Assert-StagedWaveWorkspaceIsQuiescent {
    param([string]$WorkspaceRoot)

    $queueRoot = Join-Path (Join-Path $WorkspaceRoot "staged-wave-services") "v1"
    if (-not (Test-Path -LiteralPath $queueRoot -PathType Container)) {
        return
    }

    Invoke-WithStagedWaveAdmissionLock -QueueRoot $queueRoot -Operation {
        $pendingPaths = @(
            Get-ChildItem -LiteralPath (Join-Path $queueRoot "requests") `
                -Filter "*.json" -File -ErrorAction SilentlyContinue |
                ForEach-Object { $_.FullName }
        )
        $processingPaths = @(
            Get-ChildItem -LiteralPath (Join-Path $queueRoot "processing") `
                -Filter "*.json" -File -ErrorAction SilentlyContinue |
                ForEach-Object { $_.FullName }
        )
        $ambiguousPaths = @(
            Get-ChildItem -LiteralPath (Join-Path $queueRoot "ambiguous") `
                -Filter "*.json" -File -ErrorAction SilentlyContinue |
                ForEach-Object { $_.FullName }
        )
        $service = Get-StagedBakeQueueServiceState -QueueRoot $queueRoot
        if (($processingPaths.Count -gt 0 -or $pendingPaths.Count -gt 0) -and $service.processState -eq "stopped") {
            # Recovery takes the worker lease and never executes queued generation.
            & $PythonCommand -m exercise_motion_pkg.staged_wave_service --queue-root $queueRoot --recover-only
            if ($LASTEXITCODE -ne 0) {
                throw "Staged-wave queue recovery failed; retained records were not cleared: $queueRoot"
            }
            $processingPaths = @(Get-ChildItem -LiteralPath (Join-Path $queueRoot "processing") -Filter "*.json" -File | ForEach-Object { $_.FullName })
            $pendingPaths = @(Get-ChildItem -LiteralPath (Join-Path $queueRoot "requests") -Filter "*.json" -File | ForEach-Object { $_.FullName })
            $ambiguousPaths = @(Get-ChildItem -LiteralPath (Join-Path $queueRoot "ambiguous") -Filter "*.json" -File | ForEach-Object { $_.FullName })
        }
        $workerState = $service.state
        $workerBusy = $false
        if ($service.matchingProcess) {
            $workerBusy = (
                -not $service.healthy -or
                [string]$workerState.status -ne "idle" -or
                -not [string]::IsNullOrWhiteSpace([string]$workerState.currentRequestId) -or
                -not [string]::IsNullOrWhiteSpace([string]$workerState.currentWaveId)
            )
        }

        if ($pendingPaths.Count -gt 0 -or $processingPaths.Count -gt 0 -or
            $ambiguousPaths.Count -gt 0 -or $workerBusy) {
            $evidence = @($pendingPaths) + @($processingPaths) + @($ambiguousPaths)
            if ($workerBusy -and $workerState) {
                $evidence += "worker pid=$($workerState.pid) status=$($workerState.status) request=$($workerState.currentRequestId) wave=$($workerState.currentWaveId)"
            }
            throw "Motion workspace '$WorkspaceRoot' has staged-wave work that is pending, active, ambiguous, or unverifiable. Resolve this queue before starting a new run: $($evidence -join '; ')"
        }
    }
}

function Acquire-MotionWorkspaceLease {
    param([string]$WorkspaceRoot)

    $lockPath = Join-Path $WorkspaceRoot ".motion_workspace.lock"
    $ownerPath = Join-Path $WorkspaceRoot ".motion_workspace.owner.json"
    try {
        $stream = [System.IO.FileStream]::new(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    } catch [System.IO.IOException] {
        $owner = "owner metadata unavailable"
        try {
            if (Test-Path -LiteralPath $ownerPath) {
                $owner = (Get-Content -LiteralPath $ownerPath -Raw -ErrorAction Stop).Trim()
            }
        } catch {
        }
        throw "Motion workspace '$WorkspaceRoot' is already owned by another run. Owner: $owner"
    }

    if (Test-Path -LiteralPath $ownerPath -PathType Leaf) {
        try {
            $previousOwner = Get-Content -LiteralPath $ownerPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            if ($null -eq $previousOwner -or
                $previousOwner -isnot [System.Management.Automation.PSCustomObject] -or
                [string]::IsNullOrWhiteSpace([string]$previousOwner.ownerToken)) {
                throw "Motion service session '$WorkspaceRoot' has incomplete previous owner evidence; refusing to replace it."
            }
            $previousRuntime = Get-ObjectProperty -Object $previousOwner -Name "runtimeOwner"
            if ($null -ne $previousRuntime) {
                $runtimeState = Get-MotionServiceRuntimeState -RuntimeOwner $previousRuntime
                if ($runtimeState -ne "stopped") {
                    $stream.Dispose()
                    throw "Motion service session '$WorkspaceRoot' is retained by a previous owner; runtime state is $runtimeState. Owner: $($previousOwner | ConvertTo-Json -Compress -Depth 8)"
                }
            }
        } catch {
            if ($null -ne $stream) { $stream.Dispose() }
            throw
        }
    }

    try {
        Assert-StagedWaveWorkspaceIsQuiescent -WorkspaceRoot $WorkspaceRoot
    } catch {
        $stream.Dispose()
        throw
    }

    $ownerToken = [guid]::NewGuid().ToString("N")
    $owner = [ordered]@{
        schemaVersion = 1
        pid = $PID
        stage = "run_exercise_motion_workout_plan"
        workspaceRoot = $WorkspaceRoot
        ownerToken = $ownerToken
        acquiredAtUtc = [DateTime]::UtcNow.ToString("o")
    }
    $ownerJson = $owner | ConvertTo-Json -Compress
    $ownerTempPath = "$ownerPath.$ownerToken.tmp"
    try {
        $lockBytes = [System.Text.Encoding]::UTF8.GetBytes($ownerJson)
        $stream.SetLength(0)
        $stream.Write($lockBytes, 0, $lockBytes.Length)
        $stream.Flush($true)
        [System.IO.File]::WriteAllText(
            $ownerTempPath,
            $ownerJson + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $ownerTempPath -Destination $ownerPath -Force
    } catch {
        $stream.Dispose()
        Remove-Item -LiteralPath $ownerTempPath -Force -ErrorAction SilentlyContinue
        throw
    }
    return [pscustomobject]@{
        stream = $stream
        ownerPath = $ownerPath
        ownerToken = $ownerToken
    }
}

function Release-MotionWorkspaceLease {
    param(
        [object]$Lease,
        [switch]$PreserveOwner
    )

    if ($null -eq $Lease) {
        return
    }
    try {
        if (Test-Path -LiteralPath $Lease.ownerPath) {
            $owner = Get-Content -LiteralPath $Lease.ownerPath -Raw -ErrorAction SilentlyContinue |
                ConvertFrom-ReconstructionJson -ErrorAction SilentlyContinue
            if ($owner -and "$($owner.ownerToken)" -eq "$($Lease.ownerToken)") {
                if (-not $PreserveOwner) {
                    $runtimeOwner = Get-ObjectProperty -Object $owner -Name "runtimeOwner"
                    if ($null -ne $runtimeOwner -and
                        (Get-MotionServiceRuntimeState -RuntimeOwner $runtimeOwner) -ne "stopped") {
                        Write-Warning "Preserving workspace lease evidence at '$($Lease.ownerPath)' because the owned service shutdown is unconfirmed."
                    } else {
                        Remove-Item -LiteralPath $Lease.ownerPath -Force -ErrorAction SilentlyContinue
                    }
                } else {
                    Write-Warning "Preserving workspace lease evidence at '$($Lease.ownerPath)' because shutdown was not confirmed."
                }
            }
        }
    } finally {
        if ($null -ne $Lease.stream) {
            $Lease.stream.Dispose()
        }
    }
}

function Acquire-MotionServiceSessionLease {
    param(
        [string]$SessionDirectory,
        [string]$Stage
    )

    $normalizedSession = [System.IO.Path]::GetFullPath($SessionDirectory).TrimEnd(
        [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    )
    $normalizedWorkspace = [System.IO.Path]::GetFullPath($resolvedWorkspaceRoot).TrimEnd(
        [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    )
    if ([string]::Equals($normalizedSession, $normalizedWorkspace, [StringComparison]::OrdinalIgnoreCase)) {
        return $null
    }
    if ($script:MotionServiceSessionLeases.ContainsKey($normalizedSession)) {
        $existingLease = $script:MotionServiceSessionLeases[$normalizedSession]
        $existingRuntimeState = Get-MotionServiceRuntimeState -RuntimeOwner $existingLease.runtimeOwner
        if ($existingRuntimeState -ne "stopped") {
            throw "Motion service session is already owned by this run and its service is not confirmed stopped (runtime state: $existingRuntimeState): $normalizedSession"
        }
        # Reuse the held OS lease for an in-run restart. Releasing and
        # reacquiring here would create a gap in which another process could
        # claim the session between two service generations.
        return $normalizedSession
    }
    $lease = Acquire-MotionWorkspaceLease -WorkspaceRoot $normalizedSession
    $lease | Add-Member -NotePropertyName "runtimeOwner" -NotePropertyValue $null -Force
    $script:MotionServiceSessionLeases[$normalizedSession] = $lease
    return $normalizedSession
}

function Release-MotionServiceSessionLease {
    param([string]$SessionDirectory)

    $lease = $null
    $releaseLease = $false
    if ([string]::IsNullOrWhiteSpace($SessionDirectory)) {
        # A service may deliberately share the top-level workspace directory;
        # the outer run lease owns the handle in that case.
        $lease = $script:MotionWorkspaceLease
    } elseif ($script:MotionServiceSessionLeases.ContainsKey($SessionDirectory)) {
        $lease = $script:MotionServiceSessionLeases[$SessionDirectory]
        $script:MotionServiceSessionLeases.Remove($SessionDirectory)
        $releaseLease = $true
    }
    if ($null -eq $lease) {
        return "stopped"
    }

    $runtimeOwner = $lease.runtimeOwner
    if ($null -eq $runtimeOwner -and (Test-Path -LiteralPath $lease.ownerPath -PathType Leaf)) {
        try {
            $owner = Get-Content -LiteralPath $lease.ownerPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            $runtimeOwner = Get-ObjectProperty -Object $owner -Name "runtimeOwner"
        } catch {
            $runtimeOwner = $null
        }
    }
    $runtimeState = Get-MotionServiceRuntimeState -RuntimeOwner $runtimeOwner
    if ($runtimeState -eq "stopped") {
        $ownerCleared = $true
        if ($null -ne $runtimeOwner) {
            try {
                Write-MotionWorkspaceLeaseOwner `
                    -Lease $lease `
                    -RuntimeOwner $runtimeOwner `
                    -ServiceState "stopped" `
                    -ClearRuntimeOwner
            } catch {
                $ownerCleared = $false
                Write-Warning "Could not clear stopped service ownership evidence for '$SessionDirectory': $($_.Exception.Message)"
            }
        }
        if ($releaseLease) {
            if ($ownerCleared) {
                Release-MotionWorkspaceLease -Lease $lease
            } else {
                # Keep any stale marker intact; the next owner can safely
                # confirm the recorded child is gone before replacing it.
                Release-MotionWorkspaceLease -Lease $lease -PreserveOwner
            }
        }
        return "stopped"
    }

    try {
        Write-MotionWorkspaceLeaseOwner `
            -Lease $lease `
            -RuntimeOwner $runtimeOwner `
            -ServiceState "shutdown_unconfirmed"
    } catch {
        Write-Warning "Could not persist shutdown evidence for '$SessionDirectory': $($_.Exception.Message)"
    }
    if ($releaseLease) {
        # Closing the OS handle is unavoidable when the run exits. Keep the
        # durable owner record so a later acquisition probes the child before
        # it can replace that record or start a second service.
        Release-MotionWorkspaceLease -Lease $lease -PreserveOwner
    }
    Write-Warning "Retaining service session '$SessionDirectory' because shutdown is unconfirmed (runtime state: $runtimeState)."
    return $runtimeState
}

New-Item -ItemType Directory -Force -Path $WorkspaceRoot | Out-Null
$resolvedWorkspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$script:MotionWorkspaceLease = Acquire-MotionWorkspaceLease -WorkspaceRoot $resolvedWorkspaceRoot
try {
$movementRunId = if ([string]::IsNullOrWhiteSpace($InvocationRunId)) { [guid]::NewGuid().ToString("N") } else { $InvocationRunId }
$movementRunStartedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
$script:MotionRunOutcome = "running"
$summaryPath = Join-Path $resolvedWorkspaceRoot "workout_motion_generation_summary.json"
$earlyRunTargetCount = [int]$selectedDefinitionExerciseCount
$exerciseListPath = Join-Path $resolvedWorkspaceRoot "workout_plan_exercises.json"
$definitionReadinessReportPath = Join-Path $resolvedWorkspaceRoot "definition_readiness_report.json"
$definitionEffectivePlanPath = Join-Path $resolvedWorkspaceRoot "effective_workout_plan.json"
Copy-Item -LiteralPath $definitionPreflightListPath -Destination $exerciseListPath -Force
Copy-Item -LiteralPath $definitionPreflightEffectivePlanPath -Destination $definitionEffectivePlanPath -Force
$definitionReadinessReport | Add-Member -NotePropertyName effectivePlanPath -NotePropertyValue $definitionEffectivePlanPath -Force
$definitionReadinessReport | Add-Member -NotePropertyName effectivePlanSha256 -NotePropertyValue (Get-FileHash -LiteralPath $definitionEffectivePlanPath -Algorithm SHA256).Hash -Force
$definitionReadinessReport | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $definitionReadinessReportPath -Encoding UTF8
$definitionPreflightReportPersisted = $true
$workoutPlanInputSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedWorkoutPlanJson).Hash
$effectiveWorkoutPlanInputSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $definitionEffectivePlanPath).Hash
$equipmentInputSha256 = if ([string]::IsNullOrWhiteSpace($EquipmentJson)) { "none" } else { (Get-FileHash -Algorithm SHA256 -LiteralPath $EquipmentJson).Hash }
$definitionsInputSha256 = if ($resolvedApprovedExerciseDefinitionsJson) { (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedApprovedExerciseDefinitionsJson).Hash } else { "none" }
$computedInputIdentityBytes = [System.Text.Encoding]::UTF8.GetBytes("$workoutPlanInputSha256`n$definitionsInputSha256`n$effectiveWorkoutPlanInputSha256`n$equipmentInputSha256")
$computedInputIdentitySha256 = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($computedInputIdentityBytes))
$inputIdentitySha256 = if ([string]::IsNullOrWhiteSpace($InputIdentitySha256)) { $computedInputIdentitySha256 } else { $InputIdentitySha256 }
$progressCheckpointPath = Join-Path $resolvedWorkspaceRoot "workout_motion_generation_checkpoint.json"
$script:StagedWaveServiceQueueRoot = Join-Path (Join-Path $resolvedWorkspaceRoot "staged-wave-services") "v1"
$script:MotionServiceSessionLeases = @{}
$sharedLlamaServerInstance = $null
$warmGvhmrWorkerInstance = $null

function Write-EarlyMotionRunOutcomeSummary {
    param([string]$Outcome)

    $existingSummary = $null
    if (Test-Path -LiteralPath $summaryPath) {
        try { $existingSummary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json -ErrorAction Stop } catch {}
    }
    if ((Test-Path -LiteralPath $summaryPath) -and (
        -not $existingSummary -or
        $existingSummary.runId -ne $movementRunId -or
        $existingSummary.inputIdentitySha256 -ne $inputIdentitySha256
    )) {
        $oldSummaryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $summaryPath).Hash.Substring(0, 12)
        $archiveStamp = (Get-Item -LiteralPath $summaryPath).LastWriteTimeUtc.ToString("yyyyMMddTHHmmssZ")
        $archivePath = "{0}.previous-{1}-{2}.json" -f $summaryPath, $archiveStamp, $oldSummaryHash
        $archiveIndex = 1
        while (Test-Path -LiteralPath $archivePath) {
            $archivePath = "{0}.previous-{1}-{2}-{3}.json" -f $summaryPath, $archiveStamp, $oldSummaryHash, $archiveIndex
            $archiveIndex += 1
        }
        Copy-Item -LiteralPath $summaryPath -Destination $archivePath
    }
    $nowUtc = (Get-Date).ToUniversalTime().ToString("o")
    $summary = [ordered]@{
        schemaVersion = 2
        runId = $movementRunId
        libraryRunId = if ([string]::IsNullOrWhiteSpace($LibraryRunId)) { $null } else { $LibraryRunId }
        outcome = $Outcome
        startedAtUtc = $movementRunStartedAtUtc
        completedAtUtc = if ($Outcome -eq "completed") { $nowUtc } else { $null }
        stoppedAtUtc = if ($Outcome -eq "stopped") { $nowUtc } else { $null }
        failedAtUtc = if ($Outcome -eq "failed") { $nowUtc } else { $null }
        generatedAt = $nowUtc
        inputIdentitySha256 = $inputIdentitySha256
        approvedDefinitionsSha256 = $definitionsInputSha256
        effectiveDefinitionPlanSha256 = $effectiveWorkoutPlanInputSha256
        motionSourceIdentity = $script:MotionSourceIdentity
        sourceWorkoutPlanPath = $resolvedWorkoutPlanJson
        workspaceRoot = $resolvedWorkspaceRoot
        totalExerciseCount = $earlyRunTargetCount
        terminalExerciseCount = 0
        successfulExerciseCount = 0
        unsuccessfulExerciseCount = 0
        pendingExerciseCount = $earlyRunTargetCount
        exercises = @()
    }
    $temporaryPath = "$summaryPath.$movementRunId.early.tmp"
    $summary | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -Force -LiteralPath $temporaryPath -Destination $summaryPath
}

Write-EarlyMotionRunOutcomeSummary -Outcome "running"
$script:SchedulerTimelinePath = Join-Path $resolvedWorkspaceRoot "scheduler_timeline.json"
$script:MotionSourceIdentityPath = Join-Path $resolvedWorkspaceRoot "motion_source_identity.json"
$priorSourceIdentity = $null
if (Test-Path -LiteralPath $script:MotionSourceIdentityPath) {
    try {
        $priorSourceIdentityEnvelope = Get-Content -LiteralPath $script:MotionSourceIdentityPath -Raw | ConvertFrom-Json
        if ($null -ne $priorSourceIdentityEnvelope.identity) {
            $priorSourceIdentity = $priorSourceIdentityEnvelope.identity
        } else {
            $priorSourceIdentity = $priorSourceIdentityEnvelope
        }
    } catch {
        $priorSourceIdentity = $null
    }
}
$script:MotionSourceIdentityMatchesPriorRun = $false
if ($null -ne $priorSourceIdentity) {
    $script:MotionSourceIdentityMatchesPriorRun = (
        [int]$priorSourceIdentity.schemaVersion -eq [int]$script:MotionSourceIdentity.schemaVersion -and
        "$($priorSourceIdentity.gitCommit)" -eq "$($script:MotionSourceIdentity.gitCommit)" -and
        "$($priorSourceIdentity.gitStatusSha256)" -eq "$($script:MotionSourceIdentity.gitStatusSha256)" -and
        "$($priorSourceIdentity.gitTrackedDiffSha256)" -eq "$($script:MotionSourceIdentity.gitTrackedDiffSha256)" -and
        "$($priorSourceIdentity.gitUntrackedContentSha256)" -eq "$($script:MotionSourceIdentity.gitUntrackedContentSha256)" -and
        "$($priorSourceIdentity.gitSubmoduleWorktreeSha256)" -eq "$($script:MotionSourceIdentity.gitSubmoduleWorktreeSha256)"
    )
}
$priorCheckpointPath = Join-Path $resolvedWorkspaceRoot "workout_motion_generation_checkpoint.json"
$priorSummaryPath = Join-Path $resolvedWorkspaceRoot "workout_motion_generation_summary.json"
$priorRunStateExists = (
    (Test-Path -LiteralPath $priorCheckpointPath) -or
    (Test-Path -LiteralPath $priorSummaryPath) -or
    (Test-Path -LiteralPath $script:MotionSourceIdentityPath)
)
if ($priorRunStateExists -and -not $script:MotionSourceIdentityMatchesPriorRun) {
    $DisableMotionProcessingResume = $true
    Write-Warning "Motion source identity changed; rechecking motion processing while retaining discovery and downloads with valid stage signatures."
}
$identityPayload = [ordered]@{
    capturedAt = (Get-Date).ToUniversalTime().ToString("o")
    identity = $script:MotionSourceIdentity
}
$identityTemporaryPath = "$($script:MotionSourceIdentityPath).tmp"
$identityPayload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $identityTemporaryPath -Encoding UTF8
Move-Item -Force -LiteralPath $identityTemporaryPath -Destination $script:MotionSourceIdentityPath
$preparedCandidatesBySlug = @{}
if (-not [string]::IsNullOrWhiteSpace($PreparedCandidatesManifest)) {
    $preparedCandidatesBySlug = Import-PreparedCandidatesManifest -ManifestPath (Resolve-StrictPath $PreparedCandidatesManifest)
    Write-Host ("Prepared candidates manifest: {0} exercise(s) with fixed sources; discovery is bypassed for them." -f $preparedCandidatesBySlug.Count)
}
$resolvedSourceOutcomeIndexJson = if ([System.IO.Path]::IsPathRooted($SourceOutcomeIndexJson)) {
    [System.IO.Path]::GetFullPath($SourceOutcomeIndexJson)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $SourceOutcomeIndexJson))
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedSourceOutcomeIndexJson) | Out-Null
# The persistent RECONSTRUCTION worker imports RECONSTRUCTION's demo/network directly, and the
# persistent GVHMR worker keeps preprocessing and prediction models resident.
$effectiveWarmGvhmrWorker = (
    $hasSelectedReadyDefinitionTargets -and
    $WarmGvhmrWorker -and
    -not $SkipWarmGvhmrWorker -and
    -not $RequireReconstructionCache
)
$resolvedGvhmrWorkerSessionDir = $null
$gvhmrWarmWorkerScriptPath = Join-Path $repoRoot "exercise_motion_pkg\gvhmr_warm_worker.py"
if ($effectiveWarmGvhmrWorker) {
    if (-not (Test-Path -LiteralPath $gvhmrWarmWorkerScriptPath)) {
        throw "Warm GVHMR worker script not found: $gvhmrWarmWorkerScriptPath"
    }
    $activeGvhmrWorkerSessionDir = if ([string]::IsNullOrWhiteSpace($GvhmrWorkerSessionDir)) {
        Join-Path $resolvedWorkspaceRoot "gvhmr-warm-worker"
    } else {
        $GvhmrWorkerSessionDir
    }
    New-Item -ItemType Directory -Force -Path $activeGvhmrWorkerSessionDir | Out-Null
    $resolvedGvhmrWorkerSessionDir = (Resolve-Path -LiteralPath $activeGvhmrWorkerSessionDir).Path
    # Claim and verify the previous service owner before publishing work to children.
    $null = Acquire-MotionServiceSessionLease `
        -SessionDirectory $resolvedGvhmrWorkerSessionDir `
        -Stage "GVHMR warm-worker service"
    foreach ($marker in @("ready.json", "heartbeat.json", "start_requested.json")) {
        Remove-Item -LiteralPath (Join-Path $resolvedGvhmrWorkerSessionDir $marker) -Force -ErrorAction SilentlyContinue
    }
    @{ status = "stopped"; stoppedByPid = $PID } | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $resolvedGvhmrWorkerSessionDir "stopped.json") -Encoding UTF8
}
# Shared llama.cpp server (SHARED_LLAMA_SERVER.md): one supervisor-owned
# vision server for waves, discovery, and contract prefetch. Wave processes
# join the quiesce protocol through the session dir; discovery attaches by
# health-poll (an in-flight discovery request killed by a quiesce self-heals
# through the client recovery path - publishing discovery counters is a
# follow-up). Disabled entirely when vision ranking is off.
$effectiveSharedLlamaServer = (
    $hasSelectedReadySourceReviewTargets -and
    $SharedLlamaServer -and
    -not $SkipVisionRanking
)
$sharedLlamaServerInstance = $null
$sharedLlamaServerRestartRequired = $false
# Overlapping staged waves need that shared server: two concurrent wave VLM
# phases each spawn a dedicated llama-server without it, which cannot
# co-reside on the GPU. Collapse the cap to 1 (serialized waves, today's
# behavior) when it is unavailable.
$effectiveMaxConcurrentStagedWaves = if ($MaxConcurrentStagedWaves -gt 1 -and -not $effectiveSharedLlamaServer) {
    Write-Warning "MaxConcurrentStagedWaves > 1 requires -SharedLlamaServer; staged waves stay serialized for this run."
    1
} else {
    [int]$MaxConcurrentStagedWaves
}
if ($stagedWavesEnabled -and $effectiveMaxConcurrentStagedWaves -gt 2) {
    Write-Warning "The persistent staged-wave service supports two active waves; MaxConcurrentStagedWaves is reduced to 2 for this run."
    $effectiveMaxConcurrentStagedWaves = 2
}
$resolvedSharedLlamaServerSessionDir = $null
if ($effectiveSharedLlamaServer) {
    $activeSharedLlamaSessionDir = if ([string]::IsNullOrWhiteSpace($SharedLlamaServerSessionDir)) {
        Join-Path $resolvedWorkspaceRoot "shared-llama-server"
    } else {
        $SharedLlamaServerSessionDir
    }
    New-Item -ItemType Directory -Force -Path $activeSharedLlamaSessionDir | Out-Null
    $resolvedSharedLlamaServerSessionDir = (Resolve-Path -LiteralPath $activeSharedLlamaSessionDir).Path
    # Every child process (waves, discovery jobs, contract prefetch) must
    # resolve the same session dir for the quiesce protocol to coordinate.
    $env:EXERCISE_MOTION_SHARED_LLAMA_SESSION_DIR = $resolvedSharedLlamaServerSessionDir
    # Start eagerly: contract prefetch runs BEFORE the drain loop and attaches
    # to this server; a lazy first start inside the loop would leave the
    # prefetch waiting on a server nobody has started yet. The drain loop's
    # health-check/lazy-restart logic then maintains this instance.
    $sharedLlamaServerInstance = Start-SharedLlamaServer -SessionDir $resolvedSharedLlamaServerSessionDir
}
$sharedPreviewCachePath = if ([string]::IsNullOrWhiteSpace($YouTubePreviewCacheDir)) {
    Join-Path (Join-Path $repoRoot "build\exercise_motion") "youtube-preview-cache"
} else {
    $YouTubePreviewCacheDir
}
New-Item -ItemType Directory -Force -Path $sharedPreviewCachePath | Out-Null
$sharedSourceCachePath = if ([string]::IsNullOrWhiteSpace($YouTubeSourceCacheDir)) {
    Join-Path (Join-Path $repoRoot "build\exercise_motion") "youtube-source-cache"
} else {
    $YouTubeSourceCacheDir
}
New-Item -ItemType Directory -Force -Path $sharedSourceCachePath | Out-Null
$exerciseMotionContractCachePath = Join-Path $resolvedWorkspaceRoot "exercise-motion-contract-cache"
New-Item -ItemType Directory -Force -Path $exerciseMotionContractCachePath | Out-Null
foreach ($preflightArtifactPath in @($definitionPreflightListPath, $definitionPreflightEffectivePlanPath, $definitionPreflightReportPath)) {
    Remove-Item -LiteralPath $preflightArtifactPath -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $definitionPreflightDirectory -Force -ErrorAction SilentlyContinue
$youtubeBaseArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "find-youtube-videos",
    "--results-per-query", "$ResultsPerQuery",
    "--youtube-search-timeout-seconds", "$YouTubeSearchTimeoutSeconds",
    "--max-candidates", "$MaxCandidates",
    "--candidate-review-batch-size", "$CandidateReviewBatchSize",
    "--candidate-review-target-suitable-count", "$CandidateReviewTargetSuitableCount",
    "--vision-candidates-per-exercise", "$VisionCandidatesPerExercise",
    "--vision-download-workers", "$VisionDownloadWorkers",
    "--exercise-motion-contract-cache-dir", $exerciseMotionContractCachePath,
    "--llama-cpp-base-url", $LlamaCppBaseUrl,
    "--llama-cpp-backend", $LlamaCppBackend,
    "--llama-cpp-temperature", "$LlamaCppTemperature",
    "--llama-cpp-server-startup-timeout-seconds", "$LlamaCppServerStartupTimeoutSeconds",
    "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds"
)
if ($null -ne $LlamaCppTopP) {
    $youtubeBaseArgs += @("--llama-cpp-top-p", "$LlamaCppTopP")
}
if ($null -ne $LlamaCppTopK) {
    $youtubeBaseArgs += @("--llama-cpp-top-k", "$LlamaCppTopK")
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppModel)) {
    $youtubeBaseArgs += @("--llama-cpp-model", $LlamaCppModel)
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppServerCommand)) {
    $youtubeBaseArgs += @("--llama-cpp-server-command", $LlamaCppServerCommand)
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppMmproj)) {
    $youtubeBaseArgs += @("--llama-cpp-mmproj", $LlamaCppMmproj)
}
$youtubeBaseArgs = Add-LlamaCppTextArgs -Arguments $youtubeBaseArgs
if ($VisionMaxChunksPerCandidate -gt 0) {
    $youtubeBaseArgs += @("--vision-max-chunks-per-candidate", "$VisionMaxChunksPerCandidate")
}
if ($NoExerciseNameRewrite) {
    $youtubeBaseArgs += "--no-exercise-name-rewrite"
}
if ($NoExerciseMotionContract) {
    $youtubeBaseArgs += "--no-exercise-motion-contract"
}
if (-not $SkipVisionRanking) {
    $youtubeBaseArgs += "--rank-with-vision"
}
if ($SemanticGateWithLlamaCpp -or -not $SkipSemanticGate) {
    $youtubeBaseArgs += @(
        "--semantic-gate-with-llama-cpp",
        "--semantic-gate-min-score", "$SemanticGateMinScore"
    )
    if ($null -ne $SemanticGateCandidatesPerExercise) {
        $youtubeBaseArgs += @("--semantic-gate-candidates-per-exercise", "$SemanticGateCandidatesPerExercise")
    }
    if ($null -ne $SemanticGateMaxCandidatesPerExercise) {
        $youtubeBaseArgs += @("--semantic-gate-max-candidates-per-exercise", "$SemanticGateMaxCandidatesPerExercise")
    }
    if ($null -ne $SemanticGateLlmWorkers) {
        $youtubeBaseArgs += @("--semantic-gate-llm-workers", "$SemanticGateLlmWorkers")
    }
}
if ($UseDeepSeekQueryPlanner) {
    $youtubeBaseArgs += @(
        "--use-deepseek-query-planner",
        "--deepseek-base-url", $DeepSeekBaseUrl,
        "--deepseek-model", $DeepSeekModel,
        "--deepseek-max-queries", "$DeepSeekMaxQueries"
    )
    if (-not [string]::IsNullOrWhiteSpace($DeepSeekApiKey)) {
        $youtubeBaseArgs += @("--deepseek-api-key", $DeepSeekApiKey)
    }
}
if ($UseLlamaCppQueryPlanner -and -not $SkipLlamaCppQueryPlanner -and -not $UseDeepSeekQueryPlanner) {
    $youtubeBaseArgs += "--use-llama-cpp-query-planner"
}
if ($null -ne $LlamaCppParallel) {
    $youtubeBaseArgs += @("--llama-cpp-parallel", "$LlamaCppParallel")
}
$youtubeBaseArgs = Add-LlamaCppTuningArgs -Arguments $youtubeBaseArgs
if ($effectiveSharedLlamaServer) {
    # Discovery and contract prefetch attach to the supervisor-owned shared
    # server; the session dir arrives via the inherited environment variable.
    $youtubeBaseArgs += "--llama-cpp-shared-server"
}
if ($null -ne $LlamaCppReasoningBudget) {
    $youtubeBaseArgs += @("--llama-cpp-reasoning-budget", "$LlamaCppReasoningBudget")
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppReasoningBudgetMessage)) {
    $youtubeBaseArgs += @("--llama-cpp-reasoning-budget-message", $LlamaCppReasoningBudgetMessage)
}
if ($KeepLlamaCppServer) {
    $youtubeBaseArgs += "--keep-llama-cpp-server"
}
if ($VisionFramesPerCandidate -gt 0) {
    $youtubeBaseArgs += @("--vision-frames-per-candidate", "$VisionFramesPerCandidate")
}
if ($PosePrefilter -or -not $SkipPosePrefilter) {
    $youtubeBaseArgs += @(
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
        $youtubeBaseArgs += @("--pose-prefilter-candidates-per-exercise", "$PosePrefilterCandidatesPerExercise")
    }
}

$workItems = @()
$usedSlugs = @{}
$exerciseIndex = 0
foreach ($exercise in $exerciseList.exercises) {
    Exit-IfMotionRunInterrupted
    $exerciseName = [string]($exercise.exerciseName ?? $exercise.name ?? $exercise.id ?? "exercise")
    $exerciseId = [string]($exercise.exerciseId ?? $exercise.id ?? (ConvertTo-Slug $exerciseName))
    $sourceExerciseName = [string]($exercise.sourceExerciseName ?? "")
    $equipmentQualifiedExerciseName = [string]($exercise.equipmentQualifiedExerciseName ?? "")
    $slugSource = [string]($exercise.slug ?? $exerciseId ?? $exerciseName)
    $exerciseSlug = ConvertTo-Slug $slugSource
    if ($usedSlugs.ContainsKey($exerciseSlug)) {
        $usedSlugs[$exerciseSlug] += 1
        $exerciseSlug = "$exerciseSlug-$($usedSlugs[$exerciseSlug])"
    } else {
        $usedSlugs[$exerciseSlug] = 1
    }
    if ($hasExerciseFilter) {
        $exerciseIdKey = $exerciseId.Trim().ToLowerInvariant()
        $exerciseNameKeys = @($exerciseName, $sourceExerciseName, $equipmentQualifiedExerciseName) |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { $_.Trim().ToLowerInvariant() }
        $exerciseSlugKeys = @($exerciseSlug)
        foreach ($slugAliasSource in @($sourceExerciseName, $equipmentQualifiedExerciseName)) {
            if (-not [string]::IsNullOrWhiteSpace($slugAliasSource)) {
                $exerciseSlugKeys += ConvertTo-Slug $slugAliasSource
            }
        }
        $exerciseSlugKeys = @($exerciseSlugKeys | Select-Object -Unique)
        $matchesExerciseName = $false
        foreach ($exerciseNameKey in @($exerciseNameKeys)) {
            if ($onlyExerciseNameSet.ContainsKey($exerciseNameKey)) {
                $matchesExerciseName = $true
                break
            }
        }
        $matchesExerciseSlug = $false
        foreach ($exerciseSlugKey in @($exerciseSlugKeys)) {
            if ($onlyExerciseSlugSet.ContainsKey($exerciseSlugKey)) {
                $matchesExerciseSlug = $true
                break
            }
        }
        if (
            -not $matchesExerciseSlug -and
            -not $onlyExerciseIdSet.ContainsKey($exerciseIdKey) -and
            -not $matchesExerciseName
        ) {
            continue
        }
    }
    $exerciseWorkspace = Join-Path $resolvedWorkspaceRoot $exerciseSlug
    $exercisePlanPath = Join-Path $exerciseWorkspace "exercise_plan.json"
    $exerciseCandidatesPath = Join-Path $exerciseWorkspace "youtube_candidates.json"
    $prefetchPath = Join-Path $exerciseWorkspace "youtube_candidate_prefetch.json"
    $exerciseDefinitionReadinessReportPath = Join-Path $exerciseWorkspace "definition_readiness_report.json"
    $sourceDownloadReportPath = Join-Path $exerciseWorkspace "youtube_source_prefetch.json"
    $fallbackSourceDownloadReportPath = Join-Path $exerciseWorkspace "youtube_source_fallback_prefetch.json"
    $primarySourceDownloadLogPath = Join-Path $exerciseWorkspace "source_download.primary.log"
    $fallbackSourceDownloadLogPath = Join-Path $exerciseWorkspace "source_download.fallback.log"
    $sourceCachePath = $sharedSourceCachePath
    $previewCachePath = $sharedPreviewCachePath
    $bakeWorkspace = Join-Path $exerciseWorkspace "bake"
    $logPath = Join-Path $exerciseWorkspace "bake.log"

    New-Item -ItemType Directory -Force -Path $exerciseWorkspace | Out-Null
    Initialize-ExerciseRunLog -Path $logPath -RunId $movementRunId
    New-OneExercisePlanJson -Exercise $exercise -OutPath $exercisePlanPath

    $discoveryArgs = @($youtubeBaseArgs)
    $discoveryArgs += @('--discovery-candidate-budget', "$DiscoveryCandidateBudget",
        '--discovery-time-budget-seconds', "$DiscoveryTimeBudgetSeconds")
    $discoveryArgs += @(
        "--workout-plan-json", $exercisePlanPath,
        "--definition-readiness-report-json", $exerciseDefinitionReadinessReportPath,
        "--out-json", $exerciseCandidatesPath,
        "--youtube-preview-cache-dir", $previewCachePath,
        "--source-outcome-index", $resolvedSourceOutcomeIndexJson
    )
    $exerciseExcludeCandidateJsonPaths = @($resolvedExcludeYoutubeCandidatesJson)
    $exerciseExcludeCandidateJsonPaths += Get-PreviousCandidateJsonPaths `
        -WorkspaceRoots $resolvedExcludeCandidatesFromWorkspaceRoot `
        -ExerciseSlug $exerciseSlug `
        -PreservePath $(if ($preparedCandidatesBySlug.ContainsKey($exerciseSlug)) { $exerciseCandidatesPath } else { $null })
    foreach ($excludeCandidatesJsonPath in @($exerciseExcludeCandidateJsonPaths | Select-Object -Unique)) {
        $discoveryArgs += @("--exclude-youtube-candidates-json", $excludeCandidatesJsonPath)
    }
    foreach ($excludeVideoId in @($ExcludeYoutubeVideoId)) {
        if (-not [string]::IsNullOrWhiteSpace($excludeVideoId)) {
            $discoveryArgs += @("--exclude-youtube-video-id", $excludeVideoId)
        }
    }
    foreach ($excludeUrl in @($ExcludeYoutubeUrl)) {
        if (-not [string]::IsNullOrWhiteSpace($excludeUrl)) {
            $discoveryArgs += @("--exclude-youtube-url", $excludeUrl)
        }
    }
    $prefetchArgs = Set-CommandArgumentValue -Arguments $discoveryArgs -Name "--out-json" -Value $prefetchPath
    $prefetchArgs = [string[]](@($prefetchArgs) + "--prefetch-only")
    $exercisePlanSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $exercisePlanPath).Hash.ToLowerInvariant()
    $equipmentSha256 = if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
        (Get-FileHash -Algorithm SHA256 -LiteralPath $EquipmentJson).Hash.ToLowerInvariant()
    } else {
        ""
    }
    $prefetchArgumentsSha256 = Get-ArgumentArraySha256 -Arguments $prefetchArgs
    $discoveryArgs = [string[]](@($discoveryArgs) + @("--prefetched-candidates-json", $prefetchPath))
    $primarySourceDownloadArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "prefetch-youtube-sources",
        "--candidates-json", $exerciseCandidatesPath,
        "--youtube-source-cache-dir", $sourceCachePath,
        "--max-candidates", "1",
        "--start-index", "0",
        "--workers", "1",
        "--out-json", $sourceDownloadReportPath
    )
    $fallbackSourceDownloadArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "prefetch-youtube-sources",
        "--candidates-json", $exerciseCandidatesPath,
        "--youtube-source-cache-dir", $sourceCachePath,
        "--max-candidates", "$([Math]::Max(1, $SourceDownloadCandidates - 1))",
        "--start-index", "1",
        "--workers", "1",
        "--out-json", $fallbackSourceDownloadReportPath
    )
    $primarySourceDownloadArgumentsSha256 = Get-ArgumentArraySha256 -Arguments $primarySourceDownloadArgs
    $fallbackSourceDownloadArgumentsSha256 = Get-ArgumentArraySha256 -Arguments $fallbackSourceDownloadArgs

    $bakeArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "bake-and-rank",
        "--candidates-json", $exerciseCandidatesPath,
        # Shared contract cache with discovery/contract prefetch so staged
        # waves reuse generated contracts instead of regenerating them.
        "--exercise-motion-contract-cache-dir", $exerciseMotionContractCachePath,
        "--fallback-candidates", "$FallbackCandidates",
        "--max-source-window-attempts", "$MaxSourceWindowAttempts",
        "--max-final-output-rejections", "$MaxFinalOutputRejections",
        "--max-reconstruction-candidate-attempts", "$MaxReconstructionCandidateAttempts",
        "--source-review-timeout-seconds", "$SourceReviewTimeoutSeconds",
        "--final-review-timeout-seconds", "$FinalReviewTimeoutSeconds",
        "--candidate-timeout-seconds", "$CandidateTimeoutSeconds",
        "--exercise-timeout-seconds", "$ExerciseTimeoutSeconds",
        "--max-selected-results", "$MaxSelectedResults",
        "--candidate-workers", "$CandidateWorkers",
        "--youtube-source-cache-dir", $sourceCachePath,
        "--youtube-preview-cache-dir", $previewCachePath,
        "--source-outcome-index", $resolvedSourceOutcomeIndexJson,
        "--workspace", $bakeWorkspace,
        "--body-model-root", $resolvedBodyModelRoot,
        "--reconstruction-timeout-seconds", "$ReconstructionTimeoutSeconds",
        "--segment-confidence-threshold", "$SegmentConfidenceThreshold",
        "--segment-padding-seconds", "$SegmentPaddingSeconds",
        "--segment-end-padding-seconds", "$SegmentEndPaddingSeconds",
        "--segment-min-seconds", "$SegmentMinSeconds",
        "--segment-max-seconds", "$SegmentMaxSeconds",
        "--segment-classification-workers", "$SegmentClassificationWorkers",
        "--review-frames", "$ReviewFrames",
        "--review-llm-workers", "$ReviewLlmWorkers",
        "--max-review-windows", "$MaxReviewWindows",
        "--min-selected-score", "$MinSelectedScore",
        "--final-output-validation-min-score", "$FinalOutputValidationMinScore",
        "--llama-cpp-base-url", $LlamaCppBaseUrl,
        "--llama-cpp-backend", $LlamaCppBackend,
        "--llama-cpp-temperature", "$LlamaCppTemperature",
        "--llama-cpp-server-startup-timeout-seconds", "$LlamaCppServerStartupTimeoutSeconds",
        "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds",
        "--artifact-retention", $ArtifactRetention
    )
    if ($null -ne $LlamaCppTopP) {
        $bakeArgs += @("--llama-cpp-top-p", "$LlamaCppTopP")
    }
    if ($ComparativeSegmentSelection) {
        $bakeArgs += "--comparative-segment-selection"
    }
    if ($null -ne $LlamaCppTopK) {
        $bakeArgs += @("--llama-cpp-top-k", "$LlamaCppTopK")
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppModel)) {
        $bakeArgs += @("--llama-cpp-model", $LlamaCppModel)
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppServerCommand)) {
        $bakeArgs += @("--llama-cpp-server-command", $LlamaCppServerCommand)
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppMmproj)) {
        $bakeArgs += @("--llama-cpp-mmproj", $LlamaCppMmproj)
    }
    $bakeArgs = Add-LlamaCppTextArgs -Arguments $bakeArgs
    if ($null -ne $LlamaCppParallel) {
        $bakeArgs += @("--llama-cpp-parallel", "$LlamaCppParallel")
    }
    $bakeArgs = Add-LlamaCppTuningArgs -Arguments $bakeArgs
    if ($FastProfile) {
        # Single baseline bake + no final VLM; refinement keeps the
        # source-guided vertical trajectory repair. Deterministic gates intact.
        $SkipAdaptivePreviewSettings = $true
        $RankPreviewVariants = $false
        $FinalOutputValidation = $false
        $SkipFinalOutputValidation = $true
    }
    if ($null -ne $LlamaCppReasoningBudget) {
        $bakeArgs += @("--llama-cpp-reasoning-budget", "$LlamaCppReasoningBudget")
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppReasoningBudgetMessage)) {
        $bakeArgs += @("--llama-cpp-reasoning-budget-message", $LlamaCppReasoningBudgetMessage)
    }
    if ($FinalOutputValidation -and -not $SkipFinalOutputValidation) {
        $bakeArgs += "--final-output-validation"
    }
    if ($SkipFinalOutputValidation) {
        $bakeArgs += "--skip-final-output-validation"
    }
    if ($TwoScaleSourceValidation) {
        $bakeArgs += "--two-scale-source-validation"
    }
    if ($NoExerciseMotionContract) {
        $bakeArgs += "--no-exercise-motion-contract"
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
    if ($null -ne $SegmentWindowSeconds) {
        $bakeArgs += @("--segment-window-seconds", "$SegmentWindowSeconds")
    }
    if ($null -ne $SegmentOverlapSeconds) {
        $bakeArgs += @("--segment-overlap-seconds", "$SegmentOverlapSeconds")
    }
    if ($null -ne $SegmentFramesPerWindow) {
        $bakeArgs += @("--segment-frames-per-window", "$SegmentFramesPerWindow")
    }
    $bakeArgs += @(
        "--use-reconstruction-docker",
        "--reconstruction-docker-image", $ReconstructionDockerImage,
        "--reconstruction-docker-gpus", $ReconstructionDockerGpus,
        "--reconstruction-docker-shm-size", $ReconstructionDockerShmSize
    )
    $bakeArgs += @("--motion-reconstructor", "gvhmr")
    if ($RequireReconstructionCache) {
        $bakeArgs += "--require-reconstruction-cache"
    }
    if ($FastProfile) {
        $bakeArgs += @("--structural-refinement-vertical-only")
    }
    if ($effectiveWarmGvhmrWorker) {
        $bakeArgs += @(
            "--warm-gvhmr-worker",
            "--gvhmr-worker-session-dir", $resolvedGvhmrWorkerSessionDir,
            "--gvhmr-worker-mount-root", $resolvedWorkspaceRoot,
            "--gvhmr-worker-timeout-seconds", "$GvhmrWorkerJobTimeoutSeconds"
        )
    }
    if ($effectiveSharedLlamaServer) {
        $bakeArgs += @(
            "--shared-llama-server",
            "--shared-llama-server-session-dir", $resolvedSharedLlamaServerSessionDir
        )
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
    if (-not $SkipPreReconstructionSourceValidation) {
        $bakeArgs += "--pre-reconstruction-source-validation"
    }
    if ($SkipPreReconstructionSourceValidation) {
        $bakeArgs += "--skip-pre-reconstruction-source-validation"
    }
    $workItems += [pscustomobject]@{
        index = $exerciseIndex
        exerciseId = $exerciseId
        exerciseName = $exerciseName
        exerciseSlug = $exerciseSlug
        definitionReadinessReportPath = $exerciseDefinitionReadinessReportPath
        definitionReadinessStatus = if ($exercise.definitionReadiness.status -eq "ready") { "ready" } else { "needs_definition_review" }
        definitionReadinessReason = if ($exercise.definitionReadiness.reason) { [string]$exercise.definitionReadiness.reason } else { "readiness_missing" }
        sourceReviewBudgetReadiness = $exercise.sourceReviewBudgetReadiness
        sourceReviewBudgetReady = ($exercise.sourceReviewBudgetReadiness.ready -eq $true)
        candidateCount = $null
        exerciseWorkspace = $exerciseWorkspace
        exercisePlanPath = $exercisePlanPath
        exerciseCandidatesPath = $exerciseCandidatesPath
        prefetchPath = $prefetchPath
        prefetchArgumentsSha256 = $prefetchArgumentsSha256
        discoveryArgumentsSha256 = ""
        exercisePlanSha256 = $exercisePlanSha256
        equipmentSha256 = $equipmentSha256
        sourceDownloadReportPath = $sourceDownloadReportPath
        fallbackSourceDownloadReportPath = $fallbackSourceDownloadReportPath
        primarySourceDownloadArgumentsSha256 = $primarySourceDownloadArgumentsSha256
        fallbackSourceDownloadArgumentsSha256 = $fallbackSourceDownloadArgumentsSha256
        primarySourceDownloadLogPath = $primarySourceDownloadLogPath
        fallbackSourceDownloadLogPath = $fallbackSourceDownloadLogPath
        hasFallbackSourceDownloads = $SourceDownloadCandidates -gt 1
        sourceCachePath = $sourceCachePath
        previewCachePath = $previewCachePath
        excludeCandidateJsonPaths = [string[]]($exerciseExcludeCandidateJsonPaths | Select-Object -Unique)
        bakeWorkspace = $bakeWorkspace
        logPath = $logPath
        candidateReviewTargetSuitableCount = $initialTargetSuitableCount
        maxCandidateReviewTargetSuitableCount = $resolvedMaxCandidateReviewTargetSuitableCount
        maxSelectedResults = $MaxSelectedResults
        maxCandidates = $MaxCandidates
        visionCandidatesPerExercise = $VisionCandidatesPerExercise
        discoverySeconds = 0.0
        prefetchSeconds = 0.0
        prefetchReused = $false
        discoveryReused = $false
        primarySourceDownloadReused = $false
        fallbackSourceDownloadReused = $false
        bakeReused = $false
        motionProcessingResumed = $false
        preparedCandidates = $false
        sourceDownloadSeconds = 0.0
        bakeCommandSeconds = 0.0
        discoveryAttemptCount = 0
        bakeAttemptCount = 0
        attempts = @()
        discoveryArgs = [string[]]$discoveryArgs
        prefetchArgs = [string[]]$prefetchArgs
        primarySourceDownloadArgs = [string[]]$primarySourceDownloadArgs
        fallbackSourceDownloadArgs = [string[]]$fallbackSourceDownloadArgs
        bakeArgs = [string[]]$bakeArgs
    }
    $exerciseIndex += 1
}

if ($workItems.Count -eq 0) {
    if ($hasExerciseFilter) {
        throw "No exercises matched the supplied OnlyExerciseSlug/OnlyExerciseId/OnlyExerciseName filters."
    }
    throw "No exercises were queued for movement generation."
}
$activeDiscoveryWorkerBudget = [Math]::Max(1, [Math]::Min($resolvedDiscoveryWorkers, $workItems.Count))
$resolvedDiscoveryVisionLlmWorkers = if ($visionLlmWorkersExplicit) {
    [Math]::Max(1, [int]$VisionLlmWorkers)
} else {
    [Math]::Max(1, [int][Math]::Floor($llamaParallelSlots / $activeDiscoveryWorkerBudget))
}
if (-not $visionLlmWorkersExplicit) {
    $VisionLlmWorkers = $resolvedDiscoveryVisionLlmWorkers
}
foreach ($workItem in $workItems) {
    $workItem.discoveryArgs = [string[]](@($workItem.discoveryArgs) + @("--vision-llm-workers", "$resolvedDiscoveryVisionLlmWorkers"))
    $workItem.discoveryArgumentsSha256 = Get-ArgumentArraySha256 -Arguments $workItem.discoveryArgs
}

Write-Host ("Inference: {0} parallel slots | batch {1} | microbatch {2} | total context {3}" -f $llamaParallelSlots, $LlamaCppBatchSize, $LlamaCppUBatchSize, $LlamaCppCtxSize)
$contractPrefetchSummary = [ordered]@{
    enabled = $false
    reportPath = $null
    elapsedSeconds = 0.0
    counts = $null
}
$contractPrefetchReport = $null
if ($NoExerciseMotionContract) {
    # SHA-256 of the canonical JSON identity `null`, matching Python's
    # source_contract_clearance_sha256(None).
    $nullContractSha256 = "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c0198921a72e7"
    foreach ($workItem in $workItems) {
        $workItem | Add-Member -NotePropertyName currentContractSha256 -NotePropertyValue $nullContractSha256 -Force
    }
}
if (-not $NoExerciseMotionContract -and -not $SkipVisionRanking -and -not $SkipExerciseMotionContractPrefetch) {
    $contractPrefetchReportPath = Join-Path $resolvedWorkspaceRoot "exercise_motion_contract_prefetch_report.json"
    $retainedContractWorkItems = @()
    $newContractWorkItems = @()
    foreach ($workItem in $workItems) {
        if ($workItem.definitionReadinessStatus -ne "ready") { continue }
        if ($ReuseExistingSelected -and $null -ne (Get-SelectedOutputArtifacts -WorkItem $workItem)) {
            $retainedContractWorkItems += $workItem
        } elseif ($workItem.sourceReviewBudgetReady) {
            $newContractWorkItems += $workItem
        }
    }
    if ($StagedWaveSize -gt 0 -and $newContractWorkItems.Count -gt $StagedWaveSize) {
        $newContractWorkItems = @($newContractWorkItems | Select-Object -First $StagedWaveSize)
    }
    $contractPrefetchWorkItems = @(
        @($retainedContractWorkItems) + @($newContractWorkItems) |
            Group-Object { [string]$_.index } |
            ForEach-Object { $_.Group[0] }
    )
    if ($contractPrefetchWorkItems.Count -gt 0) {
        $contractPrefetchArgs = [string[]](@(
            $youtubeBaseArgs
            "--workout-plan-json", $definitionEffectivePlanPath,
            "--out-json", $contractPrefetchReportPath,
            "--contract-prefetch-only",
            "--contract-prefetch-workers", "$llamaParallelSlots"
        ))
        if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
            $contractPrefetchArgs = [string[]](@($contractPrefetchArgs) + @("--equipment-json", $EquipmentJson))
        }
        $contractReadinessReportPath = Join-Path $resolvedWorkspaceRoot "contract_prefetch_definition_readiness_report.json"
        $contractPrefetchArgs += @("--definition-readiness-report-json", $contractReadinessReportPath)
        foreach ($workItem in $contractPrefetchWorkItems) {
            $contractPrefetchArgs = [string[]](@($contractPrefetchArgs) + @("--only-exercise-id", $workItem.exerciseId))
        }
        Write-Host ("Preparing contracts for {0} retained selection(s) and the first {1} new exercise(s) before reuse." -f $retainedContractWorkItems.Count, $newContractWorkItems.Count)
        $contractPrefetchStarted = Get-Date
        Invoke-PythonModule -Arguments $contractPrefetchArgs
        $contractPrefetchReport = Get-Content -LiteralPath $contractPrefetchReportPath -Raw | ConvertFrom-ReconstructionJson
        foreach ($result in @($contractPrefetchReport.exercises)) {
            $matchingItem = $workItems | Where-Object { [string]$_.exerciseId -eq [string]$result.exerciseId } | Select-Object -First 1
            if ($matchingItem -and $result.status -in @("generated", "reused") -and
                -not [string]::IsNullOrWhiteSpace([string]$result.sourceSelectionContractSha256)) {
                $matchingItem | Add-Member -NotePropertyName currentContractSha256 -NotePropertyValue ([string]$result.sourceSelectionContractSha256) -Force
            }
        }
        Write-Host ("Contracts ready: {0} reused, {1} generated, {2} failed" -f $contractPrefetchReport.counts.reused, $contractPrefetchReport.counts.generated, $contractPrefetchReport.counts.failed)
        $contractPrefetchSummary = [ordered]@{
            enabled = $true
            reportPath = $contractPrefetchReportPath
            elapsedSeconds = [Math]::Round(((Get-Date) - $contractPrefetchStarted).TotalSeconds, 3)
            counts = $contractPrefetchReport.counts
        }
    }
}
$existingSelectedSummaryByIndex = @{}
$existingSelectedSummaryChecked = @{}
if ($ReuseExistingSelected) {
    $policyReauditSlugs = [string[]]@(
        $workItems |
            Where-Object { $_.definitionReadinessStatus -eq "ready" -and (Test-SelectionNeedsPolicyReaudit -WorkItem $_) } |
            ForEach-Object { "$($_.exerciseSlug)" }
    )
    if ($policyReauditSlugs.Count -gt 0) {
        Invoke-SelectionPolicyReaudit -ExerciseSlugs $policyReauditSlugs
    }
    foreach ($workItem in $workItems) {
        $indexKey = [string]$workItem.index
        Exit-IfMotionRunInterrupted
        $existingSelectedSummaryChecked[$indexKey] = $true
        $existingSummary = Get-ExistingSelectedSummary -WorkItem $workItem
        if ($existingSummary) {
            $existingSelectedSummaryByIndex[$indexKey] = $existingSummary
        }
    }
}
$summaryByIndex = @{}
$script:LastIncrementalMobilePackageSuccessfulCount = -1
$script:NextIncrementalMobilePackageAttemptAt = [datetime]::MinValue

function Update-IncrementalMobilePackage {
    param([int]$SuccessfulCount)

    if (Test-MotionRunCancelRequested) { return }
    if ([string]::IsNullOrWhiteSpace($IncrementalMobilePackageOutputJson)) {
        return
    }
    if ($SuccessfulCount -eq $script:LastIncrementalMobilePackageSuccessfulCount) {
        return
    }
    if ((Get-Date) -lt $script:NextIncrementalMobilePackageAttemptAt) {
        return
    }

    $mobilePackageBuilder = Join-Path $PSScriptRoot "build_workout_plan_movement_package.ps1"
    $resolvedIncrementalOutputJson = [System.IO.Path]::GetFullPath($IncrementalMobilePackageOutputJson)
    $builderOutput = @(
        & pwsh -NoProfile -File $mobilePackageBuilder `
            -WorkoutPlanPackageJson $resolvedWorkoutPlanJson `
            -MotionSummaryJson $progressCheckpointPath `
            -OutputJson $resolvedIncrementalOutputJson `
            -StrictIdMatch `
            -AllowEmpty 2>&1
    )
    $builderExitCode = $LASTEXITCODE
    if (Test-MotionRunCancelRequested) { return }
    $exportConfirmed = @($builderOutput | Where-Object { "$_" -like "wrote $resolvedIncrementalOutputJson with *" }).Count -gt 0
    if ($builderExitCode -ne 0 -or -not $exportConfirmed -or
        -not (Test-Path -LiteralPath $resolvedIncrementalOutputJson -PathType Leaf)) {
        $script:NextIncrementalMobilePackageAttemptAt = (Get-Date).AddSeconds(30)
        $builderError = ($builderOutput | ForEach-Object { "$_" }) -join " "
        Write-Warning "Could not refresh the mobile import package; it will be retried. $builderError"
        return
    }

    $script:LastIncrementalMobilePackageSuccessfulCount = $SuccessfulCount
    $script:NextIncrementalMobilePackageAttemptAt = [datetime]::MinValue
    Write-Host ("Mobile package updated: {0} approved movement(s) at {1}" -f $SuccessfulCount, $resolvedIncrementalOutputJson)
}

function Write-JsonAtomically {
    param([string]$Path, [object]$Value, [int]$Depth = 64)
    $temporaryPath = "$Path.$movementRunId.tmp"
    $Value | ConvertTo-Json -Depth $Depth | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -Force -LiteralPath $temporaryPath -Destination $Path
}

function Write-ProgressCheckpoint {
    $checkpointItems = @(
        $summaryByIndex.Keys |
            Sort-Object |
            ForEach-Object { $summaryByIndex[$_] }
    )
    $successfulItems = @($checkpointItems | Where-Object { "$($_.status)" -eq "completed" })
    $unsuccessfulItems = @($checkpointItems | Where-Object { "$($_.status)" -ne "completed" })
    $checkpoint = [ordered]@{
        schemaVersion = 2
        runId = $movementRunId
        libraryRunId = if ([string]::IsNullOrWhiteSpace($LibraryRunId)) { $null } else { $LibraryRunId }
        startedAtUtc = $movementRunStartedAtUtc
        outcome = $script:MotionRunOutcome
        inputIdentitySha256 = $inputIdentitySha256
        approvedDefinitionsSha256 = $definitionsInputSha256
        effectiveDefinitionPlanSha256 = $effectiveWorkoutPlanInputSha256
        updatedAt = (Get-Date).ToUniversalTime().ToString("o")
        sourceWorkoutPlanPath = $resolvedWorkoutPlanJson
        workspaceRoot = $resolvedWorkspaceRoot
        motionSourceIdentity = $script:MotionSourceIdentity
        totalExerciseCount = $workItems.Count
        terminalExerciseCount = $checkpointItems.Count
        successfulExerciseCount = $successfulItems.Count
        unsuccessfulExerciseCount = $unsuccessfulItems.Count
        pendingExerciseCount = [Math]::Max(0, $workItems.Count - $checkpointItems.Count)
        pipeline = [ordered]@{
            pendingPrefetchCount = if (Get-Variable -Name pendingPrefetchItems -ErrorAction SilentlyContinue) { $pendingPrefetchItems.Count } else { 0 }
            pendingReviewCount = if (Get-Variable -Name pendingDiscoveryItems -ErrorAction SilentlyContinue) { $pendingDiscoveryItems.Count } else { 0 }
            pendingSourceDownloadCount = if (Get-Variable -Name pendingSourceDownloadItems -ErrorAction SilentlyContinue) { $pendingSourceDownloadItems.Count } else { 0 }
            pendingFallbackSourceDownloadCount = if (Get-Variable -Name pendingFallbackSourceDownloadItems -ErrorAction SilentlyContinue) { $pendingFallbackSourceDownloadItems.Count } else { 0 }
            pendingBakeCount = if (Get-Variable -Name pendingBakeItems -ErrorAction SilentlyContinue) {
                $pendingBakeItems.Count +
                    $(if (Get-Variable -Name pendingLegacyBakeItems -ErrorAction SilentlyContinue) { $pendingLegacyBakeItems.Count } else { 0 }) +
                    $(if (Get-Variable -Name pendingCompletionItems -ErrorAction SilentlyContinue) { $pendingCompletionItems.Count } else { 0 })
            } else { 0 }
            activePrefetchCount = if (Get-Variable -Name prefetchRunningJobs -ErrorAction SilentlyContinue) { $prefetchRunningJobs.Count } else { 0 }
            activeReviewCount = if (Get-Variable -Name discoveryRunningJobs -ErrorAction SilentlyContinue) { $discoveryRunningJobs.Count } else { 0 }
            activeSourceDownloadCount = if (Get-Variable -Name sourceDownloadRunningJobs -ErrorAction SilentlyContinue) { $sourceDownloadRunningJobs.Count } else { 0 }
            activeBakeCount = if (Get-Variable -Name bakeRunningJobs -ErrorAction SilentlyContinue) { $bakeRunningJobs.Count } else { 0 }
        }
        exercises = $checkpointItems
    }
    $temporaryCheckpointPath = "$progressCheckpointPath.tmp"
    $checkpoint | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $temporaryCheckpointPath -Encoding UTF8
    # A concurrent reader can hold the destination briefly; a single
    # Move-Item -Force has crashed whole runs with "Cannot create a file when
    # that file already exists" under that race. The checkpoint is advisory
    # progress state: retry, fall back to a copy, never fail the run over it.
    $checkpointSwapSucceeded = $false
    foreach ($swapAttempt in 1..5) {
        try {
            Move-Item -Force -LiteralPath $temporaryCheckpointPath -Destination $progressCheckpointPath -ErrorAction Stop
            $checkpointSwapSucceeded = $true
            break
        } catch {
            Start-Sleep -Milliseconds (50 * $swapAttempt)
        }
    }
    if (-not $checkpointSwapSucceeded) {
        try {
            Copy-Item -Force -LiteralPath $temporaryCheckpointPath -Destination $progressCheckpointPath -ErrorAction Stop
            Remove-Item -LiteralPath $temporaryCheckpointPath -Force -ErrorAction SilentlyContinue
            $checkpointSwapSucceeded = $true
        } catch {
            Write-Warning "Progress checkpoint swap failed after retries; keeping the previous checkpoint."
        }
    }
    Update-IncrementalMobilePackage -SuccessfulCount $successfulItems.Count
}

function Write-RunOutcomeArtifacts {
    param([string]$Outcome)
    if (-not (Get-Command Write-ProgressCheckpoint -ErrorAction SilentlyContinue)) { return }
    $script:MotionRunOutcome = $Outcome
    Write-ProgressCheckpoint
    $existingSummary = $null
    if (Test-Path -LiteralPath $summaryPath) {
        try { $existingSummary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json -ErrorAction Stop } catch {}
    }
    $items = @($summaryByIndex.Keys | Sort-Object | ForEach-Object { $summaryByIndex[$_] })
    $successes = @($items | Where-Object status -eq "completed").Count
    if ($existingSummary -and $existingSummary.runId -eq $movementRunId) {
        $existingSummary.exercises = $items
        $existingSummary.totalExerciseCount = $workItems.Count
        $existingSummary.terminalExerciseCount = $items.Count
        $existingSummary.successfulExerciseCount = $successes
        $existingSummary.unsuccessfulExerciseCount = $items.Count - $successes
        $existingSummary.pendingExerciseCount = [Math]::Max(0, $workItems.Count - $items.Count)
        $existingSummary.outcome = $Outcome
        $outcomeAtUtc = (Get-Date).ToUniversalTime().ToString("o")
        $existingSummary.completedAtUtc = if ($Outcome -eq "completed") { $outcomeAtUtc } else { $null }
        $existingSummary.stoppedAtUtc = if ($Outcome -eq "stopped") { $outcomeAtUtc } else { $null }
        $existingSummary.failedAtUtc = if ($Outcome -eq "failed") { $outcomeAtUtc } else { $null }
        Write-JsonAtomically -Path $summaryPath -Value $existingSummary
        return
    }
    if ($existingSummary) {
        $oldSummaryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $summaryPath).Hash.Substring(0, 12)
        $archiveBase = "{0}.previous-{1}-{2}.json" -f $summaryPath, (Get-Item -LiteralPath $summaryPath).LastWriteTimeUtc.ToString("yyyyMMddTHHmmssZ"), $oldSummaryHash
        $archivePath = $archiveBase
        $archiveIndex = 1
        while (Test-Path -LiteralPath $archivePath) {
            $archivePath = "{0}.previous-{1}-{2}-{3}.json" -f $summaryPath, (Get-Item -LiteralPath $summaryPath).LastWriteTimeUtc.ToString("yyyyMMddTHHmmssZ"), $oldSummaryHash, $archiveIndex
            $archiveIndex += 1
        }
        Copy-Item -LiteralPath $summaryPath -Destination $archivePath
    }
    $partial = [ordered]@{
        schemaVersion = 2
        runId = $movementRunId
        libraryRunId = if ([string]::IsNullOrWhiteSpace($LibraryRunId)) { $null } else { $LibraryRunId }
        outcome = $Outcome
        startedAtUtc = $movementRunStartedAtUtc
        completedAtUtc = if ($Outcome -eq "completed") { (Get-Date).ToUniversalTime().ToString("o") } else { $null }
        stoppedAtUtc = if ($Outcome -eq "stopped") { (Get-Date).ToUniversalTime().ToString("o") } else { $null }
        failedAtUtc = if ($Outcome -eq "failed") { (Get-Date).ToUniversalTime().ToString("o") } else { $null }
        generatedAt = (Get-Date).ToUniversalTime().ToString("o")
        inputIdentitySha256 = $inputIdentitySha256
        approvedDefinitionsSha256 = $definitionsInputSha256
        effectiveDefinitionPlanSha256 = $effectiveWorkoutPlanInputSha256
        sourceWorkoutPlanPath = $resolvedWorkoutPlanJson
        workspaceRoot = $resolvedWorkspaceRoot
        totalExerciseCount = $workItems.Count
        terminalExerciseCount = $items.Count
        successfulExerciseCount = $successes
        unsuccessfulExerciseCount = $items.Count - $successes
        pendingExerciseCount = [Math]::Max(0, $workItems.Count - $items.Count)
        exercises = $items
    }
    Write-JsonAtomically -Path $summaryPath -Value $partial
}
$completedCount = 0
$pendingPrefetchItems = [System.Collections.Queue]::new()
$pendingDiscoveryItems = [System.Collections.Queue]::new()
$pendingSourceDownloadItems = [System.Collections.Queue]::new()
$pendingFallbackSourceDownloadItems = [System.Collections.Queue]::new()
$pendingBakeItems = [System.Collections.Queue]::new()
$pendingLegacyBakeItems = [System.Collections.Queue]::new()
$pendingCompletionItems = [System.Collections.Queue]::new()
foreach ($workItem in $workItems) {
    $indexKey = [string]$workItem.index
    Exit-IfMotionRunInterrupted
    if ($workItem.definitionReadinessStatus -eq "needs_definition_review") {
        Add-SchedulerTimelineItemEvent -WorkItem $workItem -FinalStatus "failed"
        $reason = if ([string]::IsNullOrWhiteSpace($workItem.definitionReadinessReason)) {
            "Target action definition is unresolved."
        } else { $workItem.definitionReadinessReason }
        $summaryByIndex[$workItem.index] = New-TerminalExerciseSummary -WorkItem $workItem -Status "needs_definition_review" -ErrorMessage $reason -Stage "exercise_definition" -ExitCode 0
        $completedCount += 1
        Write-Host ("Needs definition review: {0} - clarify the target action before source selection." -f $workItem.exerciseName)
        continue
    }
    $existingSummary = if ($ReuseExistingSelected -and $existingSelectedSummaryChecked.ContainsKey($indexKey)) {
        $existingSelectedSummaryByIndex[$indexKey]
    } elseif ($ReuseExistingSelected) {
        Get-ExistingSelectedSummary -WorkItem $workItem
    } else {
        $null
    }
    if ($existingSummary) {
        $summaryByIndex[$workItem.index] = $existingSummary
        $completedCount += 1
        continue
    }
    # Prepared candidates bypass discovery, prefetch, and source downloads
    # entirely: install the fixed source list and enqueue straight into bake.
    if ($preparedCandidatesBySlug.ContainsKey($workItem.exerciseSlug)) {
        if (-not (Test-Path -LiteralPath $workItem.exercisePlanPath)) {
            throw "Prepared candidates require the exercise plan to be seeded in the workspace: $($workItem.exercisePlanPath)"
        }
        Copy-Item -LiteralPath $preparedCandidatesBySlug[$workItem.exerciseSlug].candidatesJson -Destination $workItem.exerciseCandidatesPath -Force
        $workItem.preparedCandidates = $true
        $workItem.primarySourceDownloadReused = $true
        "[$(Get-Date -Format o)] installed prepared candidates; skipping discovery and source download" | Add-Content -LiteralPath $workItem.logPath -Encoding UTF8
        Add-SchedulerTimelineItemEvent -WorkItem $workItem -ReadyReason "prepared_candidates" -MarkEnqueued
        $pendingBakeItems.Enqueue($workItem)
        Write-Host ("Prepared candidates for {0}; enqueueing movement generation." -f $workItem.exerciseName)
        continue
    }
    # Incomplete fits keep discovery advancement disabled, but skip cold
    # rediscovery so retained RECONSTRUCTION/bake can finish this pass.
    if ($script:MotionSourceIdentityMatchesPriorRun -and
        -not $DisableStageResume -and
        -not $DisableMotionProcessingResume -and
        (Test-MotionProcessingResumeReady -WorkItem $workItem)) {
        $workItem.motionProcessingResumed = $true
        $workItem.primarySourceDownloadReused = $true
        "[$(Get-Date -Format o)] resumed incomplete motion processing; skipping rediscovery" | Add-Content -LiteralPath $workItem.logPath -Encoding UTF8
        Add-SchedulerTimelineItemEvent -WorkItem $workItem -ReadyReason "motion_processing_resume" -MarkEnqueued
        $pendingBakeItems.Enqueue($workItem)
        Write-Host ("Resuming {0} at incomplete motion processing." -f $workItem.exerciseName)
        continue
    }
    if (-not $DisableStageResume -and -not $DisableMotionProcessingResume -and
        (Test-BakeStageReady -WorkItem $workItem)) {
        $workItem.bakeReused = $true
        "[$(Get-Date -Format o)] reused completed movement bake; resuming selected-output materialization" | Add-Content -LiteralPath $workItem.logPath -Encoding UTF8
        Add-SchedulerTimelineItemEvent -WorkItem $workItem -ReadyReason "bake_stage_resume"
        $pendingCompletionItems.Enqueue($workItem)
        Write-Host ("Resuming {0} at selected-output materialization." -f $workItem.exerciseName)
        continue
    }
    $resumeCandidates = $null
    if (-not $DisableStageResume -and (Test-Path -LiteralPath $workItem.exerciseCandidatesPath)) {
        try {
            $resumeCandidates = Get-Content -LiteralPath $workItem.exerciseCandidatesPath -Raw | ConvertFrom-ReconstructionJson
        } catch { }
    }
    if (-not $DisableStageResume -and (Test-DiscoveryStageReady -WorkItem $workItem -Payload $resumeCandidates)) {
        $workItem.discoveryReused = $true
        $candidateCounts = Get-CandidateManifestCounts -Path $workItem.exerciseCandidatesPath -Payload $resumeCandidates
        $workItem.candidateCount = $candidateCounts.candidateCount
        $definitionReviewReason = Get-DefinitionReviewReason -Payload $resumeCandidates
        if ($null -ne $definitionReviewReason) {
            Add-SchedulerTimelineItemEvent -WorkItem $workItem -FinalStatus "failed"
            $summaryByIndex[$workItem.index] = New-TerminalExerciseSummary -WorkItem $workItem -Status "needs_definition_review" -ErrorMessage $definitionReviewReason -Stage "exercise_definition" -ExitCode 0
            $completedCount += 1
            Write-Host ("Needs definition review: {0} - clarify the target action before source selection." -f $workItem.exerciseName)
            Write-ProgressCheckpoint
            continue
        }
        $workItem.hasFallbackSourceDownloads = (
            $workItem.hasFallbackSourceDownloads -and
            $candidateCounts.recommendedCount -gt 1
        )
        "[$(Get-Date -Format o)] reused completed source discovery" | Add-Content -LiteralPath $workItem.logPath -Encoding UTF8

        if (Test-SourceDownloadStageReady -WorkItem $workItem -Kind "primary") {
            $workItem.primarySourceDownloadReused = $true
            "[$(Get-Date -Format o)] reused completed primary source downloads" | Add-Content -LiteralPath $workItem.logPath -Encoding UTF8
            Add-SchedulerTimelineItemEvent -WorkItem $workItem -ReadyReason "discovery_resume" -MarkEnqueued
            $pendingBakeItems.Enqueue($workItem)
            if ($workItem.hasFallbackSourceDownloads) {
                if (Test-SourceDownloadStageReady -WorkItem $workItem -Kind "fallback") {
                    $workItem.fallbackSourceDownloadReused = $true
                    "[$(Get-Date -Format o)] reused completed fallback source downloads" | Add-Content -LiteralPath $workItem.logPath -Encoding UTF8
                } else {
                    $pendingFallbackSourceDownloadItems.Enqueue($workItem)
                }
            }
            Write-Host ("Resuming {0} at movement generation." -f $workItem.exerciseName)
        } else {
            $pendingSourceDownloadItems.Enqueue($workItem)
            Write-Host ("Resuming {0} at source download." -f $workItem.exerciseName)
        }
        continue
    }
    if (-not $workItem.sourceReviewBudgetReady) {
        $budgetReason = [string]$workItem.sourceReviewBudgetReadiness.stopReason
        if ([string]::IsNullOrWhiteSpace($budgetReason)) { $budgetReason = "source_turn_budget_unavailable" }
        $message = "Source review budget is exhausted ($budgetReason); retained source/reconstruction work remains resumable, but no new discovery was started."
        Add-SchedulerTimelineItemEvent -WorkItem $workItem -FinalStatus "failed"
        $summaryByIndex[$workItem.index] = New-TerminalExerciseSummary -WorkItem $workItem -Status "needs_source_review" -ErrorMessage $message -Stage "source_review" -ExitCode 0
        $completedCount += 1
        Write-Host ("Needs source review: {0} - {1}" -f $workItem.exerciseName, $budgetReason)
        Write-ProgressCheckpoint
        continue
    }
    if ($CpuPrefetchDuringBake) {
        if (-not $DisableStageResume -and (Test-CandidatePrefetchReady -WorkItem $workItem)) {
            $workItem.prefetchReused = $true
            "[$(Get-Date -Format o)] reused unchanged CPU/network candidate prefetch" | Add-Content -LiteralPath $workItem.logPath -Encoding UTF8
            $pendingDiscoveryItems.Enqueue($workItem)
        } else {
            $pendingPrefetchItems.Enqueue($workItem)
        }
    } else {
        $pendingDiscoveryItems.Enqueue($workItem)
    }
}
Optimize-PendingBakeQueue -Queue $pendingBakeItems
Write-ProgressCheckpoint
Write-RunOutcomeArtifacts -Outcome "running"

$overallStartedAt = Get-Date
$runningStagedWaveHighWater = 0
if ($pendingPrefetchItems.Count -gt 0 -or $pendingDiscoveryItems.Count -gt 0 -or $pendingSourceDownloadItems.Count -gt 0 -or $pendingFallbackSourceDownloadItems.Count -gt 0 -or $pendingBakeItems.Count -gt 0 -or $pendingLegacyBakeItems.Count -gt 0 -or $pendingCompletionItems.Count -gt 0) {
    $prefetchRunningJobs = @()
    $discoveryRunningJobs = @()
    $sourceDownloadRunningJobs = @()
    $bakeRunningJobs = @()
    $discoveryCompletedCount = 0
    $bakeCompletedCount = 0
    $bakeTotalCount = $pendingBakeItems.Count
    $stagedWaveIndex = 0
    # Absolute cadence from run start (slot 0, 1, 2, ...) so reports stay on
    # ProgressIntervalSeconds boundaries instead of drifting after each late poll.
    $lastProgressSlot = -1
    $warmGvhmrWorkerInstance = $null
    $script:GvhmrWorkerStartedOnce = $false
    $schedulerCompleted = $false
    $reusedCount = $completedCount
    if ($reusedCount -gt 0) {
        Write-Host "Generating movements for $($workItems.Count) exercises. $reusedCount already have a selected movement, $($workItems.Count - $reusedCount) remaining."
    } else {
        Write-Host "Generating movements for $($workItems.Count) exercises."
    }
    try {
        while (
            $pendingPrefetchItems.Count -gt 0 -or
            $prefetchRunningJobs.Count -gt 0 -or
            $pendingDiscoveryItems.Count -gt 0 -or
            $discoveryRunningJobs.Count -gt 0 -or
            $pendingSourceDownloadItems.Count -gt 0 -or
            $pendingFallbackSourceDownloadItems.Count -gt 0 -or
            $sourceDownloadRunningJobs.Count -gt 0 -or
            $pendingBakeItems.Count -gt 0 -or
            $pendingLegacyBakeItems.Count -gt 0 -or
            $pendingCompletionItems.Count -gt 0 -or
            $bakeRunningJobs.Count -gt 0
        ) {
            if (Test-MotionRunCancelRequested) {
                break
            }
            if ($null -ne $warmGvhmrWorkerInstance) {
                $workerRunning = (& docker inspect -f "{{.State.Running}}" $warmGvhmrWorkerInstance.containerName 2>$null)
                if ($LASTEXITCODE -ne 0 -or "$workerRunning".Trim().ToLowerInvariant() -ne "true") {
                    if ($bakeRunningJobs.Count -gt 0) {
                        Write-Host "Motion extractor stopped for the expected GPU model handoff; it will be restarted before the next extraction."
                    } else {
                        Write-Warning "Motion extractor exited while idle; it will be restarted before the next extraction."
                    }
                    $warmGvhmrWorkerInstance = $null
                }
            }
            if ($effectiveSharedLlamaServer) {
                if ($null -ne $sharedLlamaServerInstance) {
                    # A quiescing client stops the server process itself; the
                    # supervisor just tends the heartbeat and notices death.
                    $serverRuntimeState = Get-MotionServiceRuntimeState `
                        -RuntimeOwner $sharedLlamaServerInstance.runtimeOwner
                    if ($serverRuntimeState -eq "stopped") {
                        $sharedLlamaServerRestartRequired = $true
                        if ($bakeRunningJobs.Count -gt 0) {
                            Write-Host "Shared llama.cpp server stopped for an exclusive GPU phase; restart is deferred until that phase ends."
                        }
                        $sharedLlamaServerInstance = $null
                    } elseif ($serverRuntimeState -eq "running") {
                        Update-SharedLlamaServerHeartbeat -SessionDir $resolvedSharedLlamaServerSessionDir
                    } else {
                        throw "Shared llama.cpp server process identity is unverified; refusing to restart or assume it is healthy: $resolvedSharedLlamaServerSessionDir"
                    }
                }
                if ($null -eq $sharedLlamaServerInstance) {
                    $bakeRestartCounts = Get-SharedLlamaBakeRestartCounts -RunningJobs $bakeRunningJobs
                }
                if (
                    $null -eq $sharedLlamaServerInstance -and
                    (Test-SharedLlamaServerRestartAdmission `
                        -RestartRequired $sharedLlamaServerRestartRequired `
                        -StartRequested (Test-Path -LiteralPath (Join-Path $resolvedSharedLlamaServerSessionDir "start_requested.json")) `
                        -ReadyMarkerExists (Test-Path -LiteralPath (Join-Path $resolvedSharedLlamaServerSessionDir "ready.json")) `
                        -LiveExclusiveHandoffActive (Test-SharedLlamaExclusiveHandoffActive -SessionDir $resolvedSharedLlamaServerSessionDir) `
                        -SafeBakeRunningJobCount $bakeRestartCounts.safeBakeRunningJobCount `
                        -UnsafeBakeRunningJobCount $bakeRestartCounts.unsafeBakeRunningJobCount `
                        -PrefetchRunningJobCount $prefetchRunningJobs.Count `
                        -PendingPrefetchCount $pendingPrefetchItems.Count `
                        -DiscoveryRunningJobCount $discoveryRunningJobs.Count `
                        -PendingDiscoveryCount $pendingDiscoveryItems.Count `
                        -PendingLegacyBakeCount $pendingLegacyBakeItems.Count)
                ) {
                    # Restart after an observed exit even when ready.json is
                    # stale. Staged-wave checkpoints admit startup only after
                    # RECONSTRUCTION has released the GPU; unknown phases remain blocked.
                    # Start-SharedLlamaServer clears stale markers.
                    $sharedLlamaServerInstance = Start-SharedLlamaServer -SessionDir $resolvedSharedLlamaServerSessionDir
                    if ($null -ne $sharedLlamaServerInstance) {
                        $sharedLlamaServerRestartRequired = $false
                    }
                }
            }
            while (
                $pendingPrefetchItems.Count -gt 0 -and
                $prefetchRunningJobs.Count -lt $PrefetchWorkers -and
                (@($pendingDiscoveryItems | Where-Object { -not $_.prefetchReused }).Count + $prefetchRunningJobs.Count) -lt $PrefetchQueueDepth
            ) {
                $prefetchRunningJobs += Start-CandidatePrefetchJob -WorkItem ($pendingPrefetchItems.Dequeue())
                Write-ProgressCheckpoint
            }

            # Keep the extractor resident while a staged batch is still filling
            # from the ready queue; stopping here forced a cold model reload
            # during the admission wait even though reconstruction work remained.
            if (
                $null -ne $warmGvhmrWorkerInstance -and
                $pendingBakeItems.Count -eq 0 -and
                $pendingLegacyBakeItems.Count -eq 0 -and
                $bakeRunningJobs.Count -eq 0
            ) {
                Stop-GvhmrWarmWorker -Worker $warmGvhmrWorkerInstance
                $warmGvhmrWorkerInstance = $null
            }

            $discoveryAndDownloadDrained = (
                $pendingDiscoveryItems.Count -eq 0 -and
                $discoveryRunningJobs.Count -eq 0 -and
                $pendingSourceDownloadItems.Count -eq 0 -and
                $pendingFallbackSourceDownloadItems.Count -eq 0 -and
                $sourceDownloadRunningJobs.Count -eq 0
            )
            $stagedWaveAdmission = Test-StagedWaveOverlapAdmission `
                -BakeRunningJobs $bakeRunningJobs `
                -PendingLegacyBakeItemCount $pendingLegacyBakeItems.Count `
                -MaxConcurrentStagedWaves $effectiveMaxConcurrentStagedWaves
            if ($stagedWaveAdmission.runningStagedWaveCount -gt $runningStagedWaveHighWater) {
                $runningStagedWaveHighWater = $stagedWaveAdmission.runningStagedWaveCount
            }
            # StagedWaveSize caps each handoff; the first ready item can start
            # while discovery and CPU-only source downloads continue.
            $stagedWaveReady = $stagedWavesEnabled -and $pendingBakeItems.Count -gt 0
            $shouldYieldDiscoveryForStagedWave = (
                $stagedWaveReady -and
                $stagedWaveAdmission.admitted -and
                $avoidGpuDiscoveryBakeOverlap
            )
            if ($shouldYieldDiscoveryForStagedWave) {
                foreach ($discoveryJob in $discoveryRunningJobs) {
                    $yieldRequestPath = Join-Path (Split-Path -Parent $discoveryJob.WorkItem.exerciseCandidatesPath) 'discovery_yield.request'
                    if (-not (Test-Path -LiteralPath $yieldRequestPath)) {
                        [System.IO.File]::WriteAllText($yieldRequestPath, 'Reconstruction ready; save completed reviews and yield.')
                        Write-Host ("Discovery yield requested: {0} - reconstruction is ready." -f $discoveryJob.WorkItem.exerciseName)
                    }
                }
            }
            # Do not launch work that the ready-wave yield above will immediately pause.
            $canLaunchDiscovery = -not $shouldYieldDiscoveryForStagedWave -and -not (
                $avoidGpuDiscoveryBakeOverlap -and
                ($bakeRunningJobs.Count -gt 0 -or $pendingLegacyBakeItems.Count -gt 0)
            )
            while ($canLaunchDiscovery -and $pendingDiscoveryItems.Count -gt 0 -and $discoveryRunningJobs.Count -lt $resolvedDiscoveryWorkers) {
                $discoveryRunningJobs += Start-InitialDiscoveryJob -WorkItem ($pendingDiscoveryItems.Dequeue())
                Write-ProgressCheckpoint
            }

            while ($pendingSourceDownloadItems.Count -gt 0 -and $sourceDownloadRunningJobs.Count -lt $SourceDownloadWorkers) {
                $primaryDownloadItem = $pendingSourceDownloadItems.Dequeue()
                $sourceDownloadRunningJobs += Start-SourceDownloadJob -WorkItem $primaryDownloadItem -Arguments $primaryDownloadItem.primarySourceDownloadArgs -Kind "primary"
                Write-ProgressCheckpoint
            }
            while ($pendingFallbackSourceDownloadItems.Count -gt 0 -and $sourceDownloadRunningJobs.Count -lt $SourceDownloadWorkers) {
                $fallbackDownloadItem = $pendingFallbackSourceDownloadItems.Dequeue()
                $sourceDownloadRunningJobs += Start-SourceDownloadJob -WorkItem $fallbackDownloadItem -Arguments $fallbackDownloadItem.fallbackSourceDownloadArgs -Kind "fallback"
                Write-ProgressCheckpoint
            }

            $canLaunchBake = -not (
                $avoidGpuDiscoveryBakeOverlap -and
                $discoveryRunningJobs.Count -gt 0
            )

            # Wave-overlap admission replaces the old serialized
            # "no bake jobs at all" requirement: a new staged wave may start
            # while every running wave is in its CPU-only cpu_preparation
            # phase, below the overlap cap, and with no full GPU-capable
            # pipeline (legacy fallback bake) queued or running. Trivial
            # completion jobs no longer block the next wave; they run in
            # their own bounded lane below. The discovery mutual exclusion
            # ($canLaunchBake) and wave readiness conditions are unchanged.
            $canStartStagedWave = (
                $stagedWavesEnabled -and
                $canLaunchBake -and
                $stagedWaveAdmission.admitted -and
                $pendingBakeItems.Count -gt 0 -and
                ($stagedWaveReady -or $discoveryAndDownloadDrained)
            )

            # Completion jobs are in-process PowerShell bookkeeping (no child
            # python process, no GPU), so they get their own bounded lane of
            # $resolvedBakeWorkers instead of competing with waves for the
            # bake-worker budget: counting them against $bakeRunningJobs (the
            # old gate) would starve them for the whole overlap window
            # whenever a wave is running. The lane keeps spawning bounded.
            $runningCompletionJobCount = Get-FlaggedJobCount -Jobs $bakeRunningJobs -FlagPropertyName "IsStagedCompletion"
            while ($pendingCompletionItems.Count -gt 0 -and $runningCompletionJobCount -lt $resolvedBakeWorkers) {
                $bakeRunningJobs += Start-StagedResultCompletionJob -WorkItem ($pendingCompletionItems.Dequeue())
                $runningCompletionJobCount += 1
                Write-ProgressCheckpoint
            }

            $lazyWarmWorkerSessionDir = $resolvedGvhmrWorkerSessionDir
            $lazyWarmWorkerScriptPath = $gvhmrWarmWorkerScriptPath
            $lazyWarmWorkerEffective = $effectiveWarmGvhmrWorker
            $lazyWorkerRequested = $lazyWarmWorkerEffective -and $bakeRunningJobs.Count -gt 0 -and (
                Test-Path -LiteralPath (Join-Path $lazyWarmWorkerSessionDir 'start_requested.json')
            )
            # A warm CUDA worker may load models during startup. Only start it
            # after its requesting Python stage has acquired the shared GPU
            # lease; speculative starts from the pending queue bypass that
            # admission boundary.
            if ($canLaunchBake -and $lazyWorkerRequested -and $null -eq $warmGvhmrWorkerInstance -and $lazyWarmWorkerEffective) {
                $warmGvhmrWorkerInstance = Start-GvhmrWarmWorker `
                    -SessionDir $lazyWarmWorkerSessionDir `
                    -MountRoot $resolvedWorkspaceRoot `
                    -WorkerScriptPath $lazyWarmWorkerScriptPath
                Remove-Item -LiteralPath (Join-Path $lazyWarmWorkerSessionDir 'start_requested.json') -Force -ErrorAction SilentlyContinue
            }

            if ($canStartStagedWave) {
                $stagedWaveAdmissionReason = if ($stagedWaveAdmission.runningStagedWaveCount -gt 0) {
                    "overlap_admission"
                } elseif ($stagedWaveReady -and $pendingBakeItems.Count -ge $StagedWaveSize) {
                    "full_wave_ready"
                } elseif ($stagedWaveReady) {
                    "ready_item_available"
                } elseif ($stagedWaveIndex -eq 0 -and @($pendingBakeItems | Where-Object {
                    $_.primarySourceDownloadReused -or $_.motionProcessingResumed
                }).Count -gt 0) {
                    "first_wave_reused_inputs"
                } else {
                    "discovery_drained"
                }
                Optimize-PendingBakeQueue -Queue $pendingBakeItems
                $waveItems = @()
                while ($pendingBakeItems.Count -gt 0 -and $waveItems.Count -lt $StagedWaveSize) {
                    $waveItem = $pendingBakeItems.Dequeue()
                    $waveItem.PSObject.Properties.Remove('PendingBakePriority')
                    $waveItems += $waveItem
                }
                $stagedWaveIndex += 1
                $stagedWaveJob = Start-StagedBakeWaveJob -WorkItems $waveItems -WaveIndex $stagedWaveIndex
                $bakeRunningJobs += $stagedWaveJob
                $stagedWaveAdmittedAtUtc = Get-SchedulerTimelineTimestamp
                Add-SchedulerTimelineWaveEvent `
                    -WaveId $stagedWaveJob.WaveId `
                    -AdmissionReason $stagedWaveAdmissionReason `
                    -ItemCount $waveItems.Count `
                    -ConcurrentWaveCountAtAdmission $stagedWaveAdmission.runningStagedWaveCount `
                    -Timestamp $stagedWaveAdmittedAtUtc
                foreach ($waveItem in $waveItems) {
                    Add-SchedulerTimelineItemEvent -WorkItem $waveItem -WaveId $stagedWaveJob.WaveId -MarkAdmitted -Timestamp $stagedWaveAdmittedAtUtc
                }
                Write-ProgressCheckpoint
            }

            # Staged fallbacks can re-enter GPU-backed discovery. Run these
            # jobs literally one at a time so independent llama.cpp/YOLO
            # subprocesses cannot wait on each other's server or GPU lock.
            while ($canLaunchBake -and $pendingLegacyBakeItems.Count -gt 0 -and $bakeRunningJobs.Count -eq 0) {
                $legacyItem = $pendingLegacyBakeItems.Dequeue()
                # This item already ran in the staged wave. Skip the exact
                # terminal windows so the individual fallback can only do new
            # work and then expand discovery if none remain.
                $useExistingForLegacyPass = -not (
                    $legacyItem.PSObject.Properties.Name -contains "individualRetryPassCount" -and
                    [int]$legacyItem.individualRetryPassCount -gt 0
                )
                $bakeRunningJobs += Start-BakeJob `
                    -WorkItem $legacyItem `
                    -UseExistingCandidatesForFirstAttempt $useExistingForLegacyPass `
                    -ReusePreviousTerminalResults $true
                Write-ProgressCheckpoint
            }

            while (-not $stagedWavesEnabled -and $canLaunchBake -and $pendingBakeItems.Count -gt 0 -and $bakeRunningJobs.Count -lt $resolvedBakeWorkers) {
                $bakeRunningJobs += Start-BakeJob `
                    -WorkItem ($pendingBakeItems.Dequeue()) `
                    -UseExistingCandidatesForFirstAttempt $true `
                    -ReusePreviousTerminalResults $ReuseExistingSelected
                Write-ProgressCheckpoint
            }

            $runningJobs = @($prefetchRunningJobs + $discoveryRunningJobs + $sourceDownloadRunningJobs + $bakeRunningJobs)
            if ($runningJobs.Count -eq 0) {
                continue
            }

            Receive-StagedWaveReadyItems -RunningJobs $bakeRunningJobs -CompletionQueue $pendingCompletionItems
            Write-StagedWaveProgressUpdates -RunningJobs $runningJobs
            if ($DetailedProgressLogs) {
                Write-LiveLogUpdates -RunningJobs $runningJobs
            }
            $now = Get-Date
            $progressInterval = [Math]::Max(1, [int]$ProgressIntervalSeconds)
            $progressSlot = [int][Math]::Floor(($now - $overallStartedAt).TotalSeconds / $progressInterval)
            if ($progressSlot -gt $lastProgressSlot) {
                $successfulCount = @($summaryByIndex.Values | Where-Object { "$($_.status)" -eq "completed" }).Count
                $unsuccessfulCount = @($summaryByIndex.Values | Where-Object { "$($_.status)" -ne "completed" }).Count
                Write-Host ("Queues: {0} prep | {1} review | {2} ready | {3} batch" -f $pendingPrefetchItems.Count, $pendingDiscoveryItems.Count, $pendingBakeItems.Count, $bakeRunningJobs.Count)
                foreach ($reviewJob in $discoveryRunningJobs) {
                    $reviewProgressPath = Join-Path (Split-Path -Parent $reviewJob.WorkItem.exerciseCandidatesPath) "youtube_discovery_progress.jsonl"
                    try {
                        $latestReview = Get-Content -LiteralPath $reviewProgressPath -Tail 1 -ErrorAction Stop | ConvertFrom-Json
                        if ($latestReview.event -eq 'candidate_review_batch_completed') {
                            Write-Host ("Reviewing: {0} | {1}/{2} new candidates this turn | {3} suitable" -f $reviewJob.WorkItem.exerciseName, $latestReview.turnReviewedCandidateCount, $DiscoveryCandidateBudget, $latestReview.suitableCandidateCount)
                        }
                    } catch { Write-Verbose "Review progress is not available yet." }
                }
                Write-ProgressSnapshot -Stage "Pipeline" -StartedAt $overallStartedAt -RunningJobs $runningJobs -SuccessfulCount $successfulCount -UnsuccessfulCount $unsuccessfulCount -ProcessedCount $completedCount -TotalCount $workItems.Count -PendingCount ($pendingPrefetchItems.Count + $pendingDiscoveryItems.Count + $pendingSourceDownloadItems.Count + $pendingFallbackSourceDownloadItems.Count + $pendingBakeItems.Count + $pendingLegacyBakeItems.Count + $pendingCompletionItems.Count) -DetailedLogs:$DetailedProgressLogs
                $lastProgressSlot = $progressSlot
            }

            $secondsUntilNextProgress = (($lastProgressSlot + 1) * $progressInterval) - ((Get-Date) - $overallStartedAt).TotalSeconds
            $jobWaitSeconds = 2
            if ($secondsUntilNextProgress -lt $jobWaitSeconds) {
                $jobWaitSeconds = [Math]::Max(0, [int][Math]::Ceiling($secondsUntilNextProgress))
            }
            # Harvest all terminal jobs; -Any alone starves waves behind replenished upstream jobs.
            $finishedJobs = @($runningJobs | Where-Object { $_.State -in @('Completed', 'Failed', 'Stopped') })
            if ($finishedJobs.Count -eq 0) {
                Wait-Job -Job $runningJobs -Any -Timeout $jobWaitSeconds | Out-Null
                $finishedJobs = @($runningJobs | Where-Object { $_.State -in @('Completed', 'Failed', 'Stopped') })
            }
            if (Test-MotionRunCancelRequested) {
                break
            }
            if ($finishedJobs.Count -eq 0) {
                continue
            }

            $prefetchJobIds = @($prefetchRunningJobs | ForEach-Object { $_.Id })
            $discoveryJobIds = @($discoveryRunningJobs | ForEach-Object { $_.Id })
            $sourceDownloadJobIds = @($sourceDownloadRunningJobs | ForEach-Object { $_.Id })
            $bakeJobIds = @($bakeRunningJobs | ForEach-Object { $_.Id })
            foreach ($job in $finishedJobs) {
                Exit-IfMotionRunInterrupted
                if ($prefetchJobIds -contains $job.Id) {
                    $workItem = $job.WorkItem
                    $jobResult = $null
                    $errorMessage = $null
                    try {
                        $received = @(Receive-Job -Job $job -Wait -ErrorAction Stop)
                        if ($received.Count -gt 0) {
                            $jobResult = $received[-1]
                        }
                    } catch {
                        $errorMessage = $_.Exception.Message
                    } finally {
                        Remove-Job -Job $job -Force
                    }
                    $prefetchSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $jobResult -Name "prefetchSeconds")
                    if ($null -ne $prefetchSeconds) {
                        $workItem.prefetchSeconds = Add-OptionalSeconds -Current $workItem.prefetchSeconds -Value $prefetchSeconds
                    }
                    if (-not $jobResult -or $jobResult.exitCode -ne 0) {
                        $exitCode = if ($jobResult) { $jobResult.exitCode } else { "unknown" }
                        if ([string]::IsNullOrWhiteSpace($errorMessage)) {
                            $errorMessage = "python candidate prefetch command failed with exit code $exitCode. See log: $($workItem.logPath)"
                        }
                        Write-Warning "Candidate prefetch failed for $($workItem.exerciseName); continuing through normal discovery. $errorMessage"
                        $pendingDiscoveryItems.Enqueue($workItem)
                    } else {
                        $pendingDiscoveryItems.Enqueue($workItem)
                    }
                } elseif ($discoveryJobIds -contains $job.Id) {
                    $workItem = $job.WorkItem
                    $jobResult = $null
                    $status = "completed"
                    $errorMessage = $null
                    try {
                        $received = @(Receive-Job -Job $job -Wait -ErrorAction Stop)
                        if ($received.Count -gt 0) {
                            $jobResult = $received[-1]
                        }
                    } catch {
                        $status = "failed"
                        $errorMessage = $_.Exception.Message
                    } finally {
                        Remove-Job -Job $job -Force
                    }

                    if ($status -eq "completed" -and (-not $jobResult -or $jobResult.exitCode -ne 0)) {
                        $status = "failed"
                        $exitCode = if ($jobResult) { $jobResult.exitCode } else { "unknown" }
                        $errorMessage = "python initial discovery command failed with exit code $exitCode. See log: $($workItem.logPath)"
                    }

                    $discoverySeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $jobResult -Name "discoverySeconds")
                    if ($null -eq $discoverySeconds) {
                        $discoverySeconds = 0.0
                    }
                    $workItem.discoverySeconds = Add-OptionalSeconds -Current $workItem.discoverySeconds -Value $discoverySeconds
                    $initialDiscoveryAttempts = @(Get-ObjectProperty -Object $jobResult -Name "attempts")
                    $workItem.discoveryAttemptCount = [int]$workItem.discoveryAttemptCount + [Math]::Max(1, $initialDiscoveryAttempts.Count)
                    $workItem.candidateCount = Get-ObjectProperty -Object $jobResult -Name "candidateCount"
                    if ($initialDiscoveryAttempts.Count -gt 0) {
                        $workItem.attempts += $initialDiscoveryAttempts
                    } else {
                        $workItem.attempts += [ordered]@{
                            attemptIndex = 1
                            stage = "initial_discovery"
                            exitCode = if ($jobResult) { $jobResult.exitCode } else { $null }
                            targetSuitableCount = if ($jobResult) { $jobResult.targetSuitableCount } else { $workItem.candidateReviewTargetSuitableCount }
                            candidateCount = if ($jobResult) { $jobResult.candidateCount } else { 0 }
                            recommendedCount = if ($jobResult) { $jobResult.recommendedCount } else { 0 }
                            elapsedSeconds = $discoverySeconds
                        }
                    }

                    if ($status -eq "failed") {
                        Write-Host ("Could not find a source for {0}. See {1}" -f $workItem.exerciseName, $workItem.logPath)
                        $discoveryExitCode = if ($jobResult) { $jobResult.exitCode } else { "unknown" }
                        $summaryByIndex[$workItem.index] = New-TerminalExerciseSummary -WorkItem $workItem -Status "failed" -ErrorMessage $errorMessage -Stage "initial_discovery" -ExitCode $discoveryExitCode
                        $completedCount += 1
                        Write-ProgressCheckpoint
                    } elseif ($jobResult -and -not [string]::IsNullOrWhiteSpace([string]$jobResult.definitionReviewReason)) {
                        Add-SchedulerTimelineItemEvent -WorkItem $workItem -FinalStatus "failed"
                        $summaryByIndex[$workItem.index] = New-TerminalExerciseSummary -WorkItem $workItem -Status "needs_definition_review" -ErrorMessage ([string]$jobResult.definitionReviewReason) -Stage "exercise_definition" -ExitCode 0
                        $completedCount += 1
                        Write-Host ("Needs definition review: {0} - clarify the target action before source selection." -f $workItem.exerciseName)
                        Write-ProgressCheckpoint
                    } else {
                        $recommendedCount = [int](Get-ObjectProperty -Object $jobResult -Name "recommendedCount")
                        $workItem.hasFallbackSourceDownloads = (
                            $workItem.hasFallbackSourceDownloads -and
                            $recommendedCount -gt 1
                        )
                        if ($recommendedCount -eq 0 -and (Resume-YieldedDiscovery -WorkItem $workItem -PendingQueue $pendingDiscoveryItems)) {
                            Write-Host ("Paused: {0} - discovery will resume after reconstruction with its remaining allowance." -f $workItem.exerciseName)
                            Write-ProgressCheckpoint
                            continue
                        } elseif ($recommendedCount -eq 0 -and (
                            $DiscoveryCandidateBudget -gt 0 -or
                            $DiscoveryTimeBudgetSeconds -gt 0 -or
                            [int](Get-ObjectProperty -Object $workItem -Name 'sourceDiscoveryRetryCount') -gt 0
                        )) {
                            Write-Host ("Deferred: {0} - no suitable source in this discovery turn; saved reviews will be reused." -f $workItem.exerciseName)
                            $summaryByIndex[$workItem.index] = New-TerminalExerciseSummary -WorkItem $workItem -Status "no_selection" -ErrorMessage "No suitable source within this discovery turn." -Stage "initial_discovery" -ExitCode 0
                            $completedCount += 1
                            Write-ProgressCheckpoint
                        } else {
                            $pendingSourceDownloadItems.Enqueue($workItem)
                            $bakeTotalCount += 1
                        }
                    }
                    $discoveryCompletedCount += 1
                } elseif ($sourceDownloadJobIds -contains $job.Id) {
                    $workItem = $job.WorkItem
                    $downloadKind = $job.DownloadKind
                    $jobResult = $null
                    try {
                        $received = @(Receive-Job -Job $job -Wait -ErrorAction Stop)
                        if ($received.Count -gt 0) {
                            $jobResult = $received[-1]
                        }
                    } catch {
                        Write-Warning "Full-source prefetch job failed for $($workItem.exerciseName); bake will retry missing sources. $($_.Exception.Message)"
                    } finally {
                        Remove-Job -Job $job -Force
                    }
                    $sourceDownloadSeconds = Get-OptionalDouble -Value (Get-ObjectProperty -Object $jobResult -Name "sourceDownloadSeconds")
                    if ($null -ne $sourceDownloadSeconds) {
                        $workItem.sourceDownloadSeconds = Add-OptionalSeconds -Current $workItem.sourceDownloadSeconds -Value $sourceDownloadSeconds
                    }
                    if (-not $jobResult -or $jobResult.exitCode -ne 0) {
                        Write-Warning "Full-source prefetch did not complete for $($workItem.exerciseName); continuing with bake fallback downloads."
                    }
                    if ($downloadKind -eq "primary") {
                        Add-SchedulerTimelineItemEvent -WorkItem $workItem -ReadyReason "discovered" -MarkEnqueued
                        $pendingBakeItems.Enqueue($workItem)
                        if ($workItem.hasFallbackSourceDownloads) {
                            $pendingFallbackSourceDownloadItems.Enqueue($workItem)
                        }
                    }
                } elseif ($bakeJobIds -contains $job.Id) {
                    if ($job.PSObject.Properties.Name -contains "IsStagedWave" -and $job.IsStagedWave) {
                        $waveResult = $null
                        try {
                            $received = @(Receive-Job -Job $job -Wait -ErrorAction Stop)
                            if ($received.Count -gt 0) {
                                $waveResult = $received[-1]
                            }
                        } catch {
                            Write-Warning "Staged movement wave waiter failed; checking its retained service response. $($_.Exception.Message)"
                        } finally {
                            Remove-Job -Job $job -Force
                        }
                        if (-not $waveResult) {
                            # Recover a terminal response if the PowerShell
                            # waiter itself failed after the service completed.
                            # If ownership cannot be resolved, do not let the
                            # legacy lane replay a request that may still be
                            # using the same exercise workspace.
                            $requestIdForRecovery = Get-ObjectProperty -Object $job -Name "RequestId"
                            $recoveryResultPath = if ($requestIdForRecovery) {
                                Join-Path (Join-Path $script:StagedWaveServiceQueueRoot "results") "$requestIdForRecovery.json"
                            } else { $null }
                            $consumedResultPath = if ($requestIdForRecovery) {
                                Join-Path (Join-Path $script:StagedWaveServiceQueueRoot "consumed") "$requestIdForRecovery.json"
                            } else { $null }
                            if ($recoveryResultPath -and -not (Test-Path -LiteralPath $recoveryResultPath) -and
                                (Test-Path -LiteralPath $consumedResultPath)) {
                                $recoveryResultPath = $consumedResultPath
                            }
                            $recoveryError = "Staged-wave waiter ended without a terminal response. Inspect the retained request and wave workspace before retrying."
                            if ($recoveryResultPath -and (Test-Path -LiteralPath $recoveryResultPath)) {
                                try {
                                    $serviceResult = Get-Content -LiteralPath $recoveryResultPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
                                    if ($serviceResult.requestId -eq $requestIdForRecovery -and $serviceResult.waveId -eq $job.WaveId) {
                                        $recoveredReport = $null
                                        $recoveredExitCode = [int]$serviceResult.exitCode
                                        $recoveredStatus = [string]$serviceResult.status
                                        if ($recoveredExitCode -eq 0) {
                                            $recoveredReportPath = Join-Path $job.WaveWorkspace "staged_wave_report.json"
                                            if (Test-Path -LiteralPath $recoveredReportPath) {
                                                $recoveredReport = Get-Content -LiteralPath $recoveredReportPath -Raw -ErrorAction Stop | ConvertFrom-ReconstructionJson -ErrorAction Stop
                                                if ($recoveredReport.waveId -ne $job.WaveId) {
                                                    $recoveredReport = $null
                                                    $recoveredStatus = $StagedWaveAmbiguousRecoveryStatus
                                                    $recoveredExitCode = $StagedWaveAmbiguousRecoveryExitCode
                                                    $recoveryError = "Recovered staged report has an unexpected wave identity. Inspect the retained wave workspace before retrying."
                                                }
                                            } else {
                                                $recoveredStatus = $StagedWaveAmbiguousRecoveryStatus
                                                $recoveredExitCode = $StagedWaveAmbiguousRecoveryExitCode
                                                $recoveryError = "Staged-wave service completed without a report file. Inspect the retained wave workspace before retrying."
                                            }
                                        } elseif ($recoveredStatus -eq $StagedWaveAmbiguousRecoveryStatus) {
                                            $recoveredExitCode = $StagedWaveAmbiguousRecoveryExitCode
                                        }
                                        $waveResult = [pscustomobject]@{
                                            exitCode = $recoveredExitCode
                                            stage = "staged_wave"
                                            elapsedSeconds = 0.0
                                            reportPath = Join-Path $job.WaveWorkspace "staged_wave_report.json"
                                            report = $recoveredReport
                                            serviceStatus = $recoveredStatus
                                            logPath = Join-Path $job.WaveWorkspace "wave.log"
                                            error = if ($serviceResult.error) { [string]$serviceResult.error } else { $recoveryError }
                                        }
                                        try {
                                            if ($recoveryResultPath -ne $consumedResultPath) {
                                                $consumedDirectory = Join-Path $script:StagedWaveServiceQueueRoot "consumed"
                                                New-Item -ItemType Directory -Force -Path $consumedDirectory | Out-Null
                                                Move-Item -LiteralPath $recoveryResultPath -Destination $consumedResultPath -ErrorAction Stop
                                            }
                                        } catch {}
                                    }
                                } catch {
                                    $recoveryError = "Staged-wave response could not be recovered: $($_.Exception.Message). Inspect the retained request and wave workspace before retrying."
                                }
                            }
                            if (-not $waveResult) {
                                $waveResult = [pscustomobject]@{
                                    exitCode = $StagedWaveAmbiguousRecoveryExitCode
                                    stage = "staged_wave"
                                    elapsedSeconds = 0.0
                                    reportPath = Join-Path $job.WaveWorkspace "staged_wave_report.json"
                                    report = $null
                                    serviceStatus = $StagedWaveAmbiguousRecoveryStatus
                                    logPath = Join-Path $job.WaveWorkspace "wave.log"
                                    error = $recoveryError
                                }
                            }
                        }
                        $waveAmbiguousRecovery = (Get-ObjectProperty -Object $waveResult -Name "serviceStatus") -eq $StagedWaveAmbiguousRecoveryStatus
                        # A successful staged coordinator stops the resident
                        # RECONSTRUCTION worker before loading the final-validation VLM.
                        # On an early failure, stop it here before retrying -
                        # unless an overlapping staged batch is still running
                        # and may be mid-generation on that same worker; the
                        # sibling's own quiesce (or the exclusive retry lane
                        # once the pipeline drains) stops it instead. Keep
                        # the supervisor handle in that case so the drain
                        # loop's health check and idle stop still own the
                        # container rather than orphaning it.
                        $siblingStagedWaveRunning = @($bakeRunningJobs | Where-Object {
                            $_.Id -ne $job.Id -and
                            $_.PSObject.Properties.Name -contains "IsStagedWave" -and $_.IsStagedWave
                        }).Count -gt 0
                        if (-not $waveAmbiguousRecovery -and (-not $waveResult -or $waveResult.exitCode -ne 0)) {
                            if ($siblingStagedWaveRunning) {
                                Write-Host "Motion extractor left for the overlapping staged batch; that batch stops it before its validation phase."
                            } else {
                                Stop-GvhmrWarmWorker -Worker $warmGvhmrWorkerInstance
                            }
                        }
                        if (-not $siblingStagedWaveRunning -and -not $waveAmbiguousRecovery) {
                            $warmGvhmrWorkerInstance = $null
                        }
                        if ($waveResult -and $waveResult.exitCode -eq 75) {
                            Write-Host "Movement generation stopped: insufficient free storage. Free space and resume."
                            exit 75
                        }
                        $waveStates = @{}
                        if ($waveAmbiguousRecovery) {
                            foreach ($waveItem in @($job.WorkItems)) {
                                $waveStates["$($waveItem.exerciseId)"] = @{
                                    retryDisposition = "operator_inspection"
                                    recoveryError = $waveResult.error
                                }
                            }
                        } elseif ($waveResult -and $waveResult.report -and $waveResult.report.items) {
                            foreach ($waveState in @($waveResult.report.items)) {
                                $waveStates["$($waveState.exerciseId)"] = $waveState
                            }
                        }
                        foreach ($waveItem in @($job.WorkItems)) {
                            if ($job.PSObject.Properties.Name -contains 'CompletedExerciseIds' -and
                                $job.CompletedExerciseIds.ContainsKey("$($waveItem.exerciseId)")) { continue }
                            $waveState = $waveStates["$($waveItem.exerciseId)"]
                            # A dispatched staged wave is one real bake attempt
                            # even when it exits without returning an item state.
                            $waveItem.bakeAttemptCount = [int]$waveItem.bakeAttemptCount + 1
                            $reuseStagedResult = (
                                $waveResult -and
                                $waveResult.exitCode -eq 0 -and
                                $waveState -and
                                "$($waveState.status)" -eq "completed"
                            )
                            if ($waveState -and $waveState.retryDisposition -eq "operator_inspection") {
                                Add-SchedulerTimelineItemEvent -WorkItem $waveItem -FinalStatus "failed"
                                $workspaceForInspection = if ($job.WaveWorkspace) { $job.WaveWorkspace } else { $waveItem.bakeWorkspace }
                                $inspectionMessage = "Staged-wave completion is ambiguous after service recovery. Inspect retained workspace '$workspaceForInspection' before resuming; this exercise was not retried automatically. $($waveState.recoveryError)"
                                $summaryByIndex[$waveItem.index] = New-TerminalExerciseSummary `
                                    -WorkItem $waveItem `
                                    -Status "needs_operator_inspection" `
                                    -ErrorMessage $inspectionMessage `
                                    -Stage "staged_wave_recovery" `
                                    -ExitCode $StagedWaveAmbiguousRecoveryExitCode
                                $completedCount += 1
                                $bakeCompletedCount += 1
                                Write-Host ("Needs inspection: {0}. {1}" -f $waveItem.exerciseName, $inspectionMessage)
                            } elseif ($reuseStagedResult) {
                                Add-StagedWaveTimelineOutcome -WorkItem $waveItem -WaveState $waveState
                                $pendingCompletionItems.Enqueue($waveItem)
                            } elseif ($waveState -and (Get-ObjectProperty -Object $waveState -Name 'retryDisposition') -eq 'retry_processing') {
                                Add-SchedulerTimelineItemEvent -WorkItem $waveItem -FinalStatus "failed"
                                $summaryByIndex[$waveItem.index] = New-TerminalExerciseSummary -WorkItem $waveItem -Status "needs_motion_processing" -ErrorMessage "Local motion or support processing remains unresolved; resume with the retained approved source and reconstruction." -Stage "motion_processing" -ExitCode 0
                                $completedCount += 1
                                $bakeCompletedCount += 1
                                Write-Host ("Needs local processing: {0} - approved source and reconstruction retained for resume." -f $waveItem.exerciseName)
                            } elseif ($waveState -and @(
                                (Get-ObjectProperty -Object (Get-ObjectProperty -Object $waveState -Name 'finalValidation') -Name 'candidateDiagnostics') |
                                    ForEach-Object { $_.reasons }
                            ) -contains 'source_support_contact_evidence_unavailable') {
                                Add-SchedulerTimelineItemEvent -WorkItem $waveItem -FinalStatus "failed"
                                $supportSummary = New-TerminalExerciseSummary -WorkItem $waveItem -Status "needs_motion_processing" -ErrorMessage "Final support-contact validation failed: source_support_contact_evidence_unavailable. Retain the approved source and reconstruction for local support-evidence repair." -Stage "final_output_validation" -ExitCode 0
                                $reconstructionAttempts = @((Get-ObjectProperty -Object (Get-ObjectProperty -Object $waveState -Name 'reconstruction') -Name 'attempts'))
                                $finalValidation = Get-ObjectProperty -Object $waveState -Name 'finalValidation'
                                $diagnostics = @(Get-ObjectProperty -Object $finalValidation -Name 'candidateDiagnostics')
                                $supportSummary.timings.stagedWaveId = [string]$job.WaveId
                                $supportSummary.timings.stagedWaveElapsedSeconds = [Math]::Round([double]$waveResult.elapsedSeconds, 3)
                                $supportSummary.timings.sourceAttemptCount = @((Get-ObjectProperty -Object (Get-ObjectProperty -Object $waveState -Name 'source') -Name 'attempts')).Count
                                $supportSummary.timings.reconstructionGeneratedCount = @($reconstructionAttempts | Where-Object { $_.status -eq 'prepared' -and $_.cacheStatus -eq 'generated' }).Count
                                $supportSummary.timings.reconstructionSeconds = [Math]::Round((@($reconstructionAttempts | ForEach-Object { [double]$_.elapsedSeconds } | Measure-Object -Sum).Sum), 3)
                                $supportSummary.timings.finalValidationSeconds = [Math]::Round([double]$finalValidation.elapsedSeconds, 3)
                                $supportSummary.timings.finalValidationDiagnosticSeconds = [Math]::Round((@($diagnostics | ForEach-Object { [double]$_.timings.totalSeconds } | Measure-Object -Sum).Sum), 3)
                                $supportSummary.finalValidationRejectionReasons = @($diagnostics | ForEach-Object { $_.reasons } | Select-Object -Unique)
                                $summaryByIndex[$waveItem.index] = $supportSummary
                                $completedCount += 1
                                $bakeCompletedCount += 1
                                Write-Host ("Needs local support-evidence repair: {0}; approved source and reconstruction retained." -f $waveItem.exerciseName)
                            } elseif ($waveState -and (Get-ObjectProperty -Object $waveState -Name 'retryDisposition') -eq 'retry_review') {
                                Add-SchedulerTimelineItemEvent -WorkItem $waveItem -FinalStatus "failed"
                                $summaryByIndex[$waveItem.index] = New-TerminalExerciseSummary -WorkItem $waveItem -Status "needs_source_review" -ErrorMessage "Review evidence remains incomplete after a bounded retry; cached source and motion retained." -Stage "source_review" -ExitCode 0
                                $completedCount += 1
                                $bakeCompletedCount += 1
                                Write-Host ("Needs review: {0} - review evidence incomplete; resume cached review work." -f $waveItem.exerciseName)
                            } elseif ($waveState -and (Get-ObjectProperty -Object $waveState -Name 'retryDisposition') -eq 'needs_definition_review') {
                                Add-SchedulerTimelineItemEvent -WorkItem $waveItem -FinalStatus "failed"
                                $definitionAttempts = @($waveState.source.attempts | Where-Object { $_.status -eq 'needs_definition_review' })
                                $definitionReason = @($definitionAttempts | ForEach-Object { $_.reason }) -join '; '
                                $summaryByIndex[$waveItem.index] = New-TerminalExerciseSummary -WorkItem $waveItem -Status "needs_definition_review" -ErrorMessage $definitionReason -Stage "exercise_definition" -ExitCode 0
                                $completedCount += 1
                                $bakeCompletedCount += 1
                                Write-Host ("Needs definition review: {0} - clarify the target action before source selection." -f $waveItem.exerciseName)
                            } elseif ($waveState -and (Get-ObjectProperty -Object $waveState -Name 'retryDisposition') -eq 'repair_contract') {
                                Add-SchedulerTimelineItemEvent -WorkItem $waveItem -FinalStatus "failed"
                                $contractErrors = @($waveState.source.attempts | Where-Object { $_.status -eq 'blocked_contract' } | ForEach-Object { $_.error })
                                $summaryByIndex[$waveItem.index] = New-TerminalExerciseSummary -WorkItem $waveItem -Status "no_selection" -ErrorMessage ($contractErrors -join '; ') -Stage "exercise_contract_invalid" -ExitCode 0
                                $completedCount += 1
                                $bakeCompletedCount += 1
                                Write-Host ("Deferred: {0} - contract regeneration failed: {1}. No source retry until the next contract pass." -f $waveItem.exerciseName, ($contractErrors -join '; '))
                            } elseif ($waveState -and (
                                (Get-ObjectProperty -Object $waveState -Name 'retryDisposition') -eq 'continue_source' -or
                                $waveState.source.failureReason -eq 'source_turn_deferred'
                            )) {
                                Add-SchedulerTimelineItemEvent -WorkItem $waveItem -ReadyReason "source_turn_deferred" -MarkEnqueued
                                $pendingBakeItems.Enqueue($waveItem)
                                Write-Host ("Continuing source review: {0} - remaining approved-source attempts resume from the saved candidate cursor." -f $waveItem.exerciseName)
                            } elseif ($waveState -and (Get-ObjectProperty -Object $waveState -Name 'retryDisposition') -eq 'next_source') {
                                $nextCandidateKey = Get-ObjectProperty -Object $waveState.source -Name 'nextCandidateKey'
                                if (-not [string]::IsNullOrWhiteSpace([string]$nextCandidateKey)) {
                                    $attemptedKeys = @(
                                        @($waveState.source.priorAttemptedCandidateKeys) +
                                        @($waveState.source.attempts | ForEach-Object { $_.candidateKey })
                                    ) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -Unique
                                    $attemptedVideoIds = @(
                                        @($waveState.source.priorAttemptedVideoIds) +
                                        @($waveState.source.attempts | ForEach-Object { $_.videoId })
                                    ) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -Unique
                                    $sourceTurnResume = [ordered]@{
                                        sourceSelectionPolicyVersion = Resolve-WaveSourceSelectionPolicyVersion -Source $waveState.source
                                        nextCandidateKey = [string]$nextCandidateKey
                                        attemptedCandidateKeys = @($attemptedKeys)
                                        attemptedVideoIds = @($attemptedVideoIds)
                                    }
                                    $resumePath = Join-Path $waveItem.bakeWorkspace 'source_turn_resume.json'
                                    New-Item -ItemType Directory -Path (Split-Path -Parent $resumePath) -Force | Out-Null
                                    [System.IO.File]::WriteAllText(
                                        $resumePath,
                                        ($sourceTurnResume | ConvertTo-Json -Depth 8),
                                        [System.Text.UTF8Encoding]::new($false)
                                    )
                                    Add-SchedulerTimelineItemEvent -WorkItem $waveItem -ReadyReason "next_source_candidate" -MarkEnqueued
                                    $pendingBakeItems.Enqueue($waveItem)
                                    Write-Host ("Continuing source review: {0} - failed candidate/window skipped; next retained candidate resumes from its cursor." -f $waveItem.exerciseName)
                                } elseif (Set-BoundedSourceRecoveryDiscovery -WorkItem $waveItem -WaveState $waveState -CandidateBudget $DiscoveryCandidateBudget) {
                                    Add-SchedulerTimelineItemEvent -WorkItem $waveItem -ReadyReason "bounded_source_discovery_retry" -MarkEnqueued
                                    $pendingDiscoveryItems.Enqueue($waveItem)
                                    Write-Host ("Returning {0} to one bounded discovery turn; exact attempted windows will be skipped while alternate windows remain eligible." -f $waveItem.exerciseName)
                                } else {
                                    Add-SchedulerTimelineItemEvent -WorkItem $waveItem -FinalStatus "failed"
                                    $summaryByIndex[$waveItem.index] = New-TerminalExerciseSummary -WorkItem $waveItem -Status "no_selection" -ErrorMessage "Retained source candidates and the single bounded discovery recovery turn were exhausted." -Stage "source_or_motion_quality" -ExitCode 0
                                    $completedCount += 1
                                    $bakeCompletedCount += 1
                                    Write-Host ("Deferred: {0} - bounded source recovery exhausted." -f $waveItem.exerciseName)
                                }
                            } else {
                                $pendingLegacyBakeItems.Enqueue($waveItem)
                            }
                        }
                        if ($waveAmbiguousRecovery) {
                            Write-Warning "Staged-wave completion is ambiguous; affected exercises were routed for operator inspection without retry. $($waveResult.error) Retained wave workspace: $($job.WaveWorkspace)"
                        } elseif (-not $waveResult -or $waveResult.exitCode -ne 0) {
                            $waveLog = if ($waveResult) { $waveResult.logPath } else { "the staged-wave log" }
                            $waveExitCode = if ($waveResult) { "$($waveResult.exitCode)" } else { "unavailable" }
                            $waveError = if ($waveResult) { "$($waveResult.error)" } else { "waiter returned no result" }
                            Write-Warning "Staged movement wave did not finish cleanly (exit code $waveExitCode); retrying its exercises individually. Details: $waveLog. $waveError"
                        }
                        Write-ProgressCheckpoint
                    } else {
                        $bakeSummary = Complete-BakeJob -Job $job
                        if ("$($bakeSummary.status)" -eq "retry_pending") {
                            # Put the exercise at the back of the queue after one
                            # unsuccessful candidate. This preserves evidence-
                            # exhaustion semantics without allowing one hard
                            # exercise to starve every other staged fallback.
                            $retryWorkItem = $bakeSummary.workItem
                            if ($retryWorkItem.preparedCandidates) {
                                $summaryByIndex[$retryWorkItem.index] = New-TerminalExerciseSummary -WorkItem $retryWorkItem -Status "no_selection" -ErrorMessage "Prepared candidate did not produce a validated movement; fixed-source replay is exhausted." -Stage "bake" -ExitCode 0
                                $completedCount += 1
                                $bakeCompletedCount += 1
                                Add-SchedulerTimelineItemEvent -WorkItem $retryWorkItem -FinalStatus "failed"
                                Write-Host ("Fixed-source replay exhausted for {0}; live discovery is disabled for prepared candidates." -f $retryWorkItem.exerciseName)
                                Write-ProgressCheckpoint
                                continue
                            }
                            $retryPassCount = if ($retryWorkItem.PSObject.Properties.Name -contains "individualRetryPassCount") {
                                [int]$retryWorkItem.individualRetryPassCount + 1
                            } else {
                                1
                            }
                            $retryWorkItem | Add-Member -NotePropertyName individualRetryPassCount -NotePropertyValue $retryPassCount -Force
                            if ($DiscoveryCandidateBudget -gt 0 -or $DiscoveryTimeBudgetSeconds -gt 0) {
                                $summaryByIndex[$retryWorkItem.index] = New-TerminalExerciseSummary -WorkItem $retryWorkItem -Status "no_selection" -ErrorMessage "Candidate did not produce a validated movement; deferred to the next library round." -Stage "bake" -ExitCode 0
                                $completedCount += 1
                                $bakeCompletedCount += 1
                                Write-Host ("Deferred: {0} - candidate did not produce a validated movement." -f $retryWorkItem.exerciseName)
                            } else {
                                $pendingLegacyBakeItems.Enqueue($retryWorkItem)
                            }
                        } else {
                            $summaryByIndex[$job.WorkItem.index] = $bakeSummary
                            $completedCount += 1
                            $bakeCompletedCount += 1
                            if ("$($bakeSummary.status)" -eq "completed") {
                                Add-SchedulerTimelineItemEvent -WorkItem $job.WorkItem -MarkAccepted -FinalStatus "materialized"
                            } elseif ("$($bakeSummary.status)" -eq "needs_manual_review") {
                                Add-SchedulerTimelineItemEvent -WorkItem $job.WorkItem -FinalStatus "needs_manual_review"
                            } else {
                                Add-SchedulerTimelineItemEvent -WorkItem $job.WorkItem -FinalStatus "failed"
                            }
                        }
                        Write-ProgressCheckpoint
                    }
                }
            }
            $finishedJobIds = @($finishedJobs | ForEach-Object { $_.Id })
            $prefetchRunningJobs = @($prefetchRunningJobs | Where-Object { $_.Id -notin $finishedJobIds })
            $discoveryRunningJobs = @($discoveryRunningJobs | Where-Object { $_.Id -notin $finishedJobIds })
            $sourceDownloadRunningJobs = @($sourceDownloadRunningJobs | Where-Object { $_.Id -notin $finishedJobIds })
            $bakeRunningJobs = @($bakeRunningJobs | Where-Object { $_.Id -notin $finishedJobIds })
            Write-ProgressCheckpoint
        }
        if (-not (Test-MotionRunCancelRequested)) {
            $schedulerCompleted = $true
        }
    } finally {
        $stagedWaveShutdownConfirmed = $true
        if (Test-MotionRunCancelRequested) {
            Write-Host "Stopping background jobs and the motion extractor..." -ForegroundColor Yellow
            foreach ($job in @($prefetchRunningJobs + $discoveryRunningJobs + $sourceDownloadRunningJobs + $bakeRunningJobs)) {
                if ($null -ne $job) {
                    Stop-Job -Job $job -ErrorAction SilentlyContinue
                    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
                }
            }
            $stagedWaveShutdownConfirmed = [bool](Stop-StagedBakeQueueService -Cancel)
        } elseif (-not $schedulerCompleted) {
            # Fatal errors and `exit` paths both run this finally. Cancel any
            # active wave before releasing the model services it may depend on.
            $stagedWaveShutdownConfirmed = [bool](Stop-StagedBakeQueueService -RunFailure)
        }
        if ($stagedWaveShutdownConfirmed) {
            $null = Stop-MotionModelServicesAfterStagedWorker `
                -StagedWaveShutdownConfirmed $stagedWaveShutdownConfirmed `
                -WarmGvhmrWorker $warmGvhmrWorkerInstance `
                -SharedLlamaServer $sharedLlamaServerInstance
            $warmGvhmrWorkerInstance = $null
            $sharedLlamaServerInstance = $null
        } else {
            $script:MotionServiceShutdownUnconfirmed = $true
            $remainingService = Get-StagedBakeQueueServiceState -QueueRoot $script:StagedWaveServiceQueueRoot
            if ($remainingService.matchingProcess) {
                $runtimeOwner = [ordered]@{
                    kind = "process"
                    pid = [int]$remainingService.state.pid
                    processIdentity = [int64]$remainingService.state.processIdentity
                    service = "staged_wave_service"
                }
            } else {
                # Preserve same-workspace exclusion even when the worker's
                # process identity cannot be read; a later owner must fail
                # closed until it can resolve the retained service state.
                $runtimeOwner = [ordered]@{
                    kind = "unknown"
                    service = "staged_wave_service"
                }
            }
            Write-MotionWorkspaceLeaseOwner `
                -Lease $script:MotionWorkspaceLease `
                -RuntimeOwner $runtimeOwner `
                -ServiceState "staged_wave_shutdown_unconfirmed"
            Write-Warning "The staged-wave worker did not stop; keeping shared model services alive and preserving workspace ownership evidence."
        }
    }
}

if (Test-MotionRunCancelRequested) {
    exit 130
}

$summaryItems = @()
for ($index = 0; $index -lt $workItems.Count; $index += 1) {
    $summaryItems += $summaryByIndex[$index]
}

$summary = [ordered]@{
    schemaVersion = 2
    runId = $movementRunId
    libraryRunId = if ([string]::IsNullOrWhiteSpace($LibraryRunId)) { $null } else { $LibraryRunId }
    outcome = "running"
    startedAtUtc = $movementRunStartedAtUtc
    completedAtUtc = $null
    stoppedAtUtc = $null
    failedAtUtc = $null
    inputIdentitySha256 = $inputIdentitySha256
    approvedDefinitionsSha256 = $definitionsInputSha256
    effectiveDefinitionPlanSha256 = $effectiveWorkoutPlanInputSha256
    generatedAt = (Get-Date).ToUniversalTime().ToString("o")
    motionSourceIdentity = $script:MotionSourceIdentity
    stageResumeDisabledForSourceIdentityMismatch = $false
    motionProcessingResumeDisabledForSourceIdentityMismatch = ($priorRunStateExists -and -not $script:MotionSourceIdentityMatchesPriorRun)
    motionProcessingResumeDisabled = [bool]$DisableMotionProcessingResume
    sourceWorkoutPlanPath = $resolvedWorkoutPlanJson
    equipmentJsonPath = if ([string]::IsNullOrWhiteSpace($EquipmentJson)) { $null } else { $EquipmentJson }
    workspaceRoot = $resolvedWorkspaceRoot
    sourceOutcomeIndexPath = $resolvedSourceOutcomeIndexJson
    excludeCandidatesFromWorkspaceRoots = $resolvedExcludeCandidatesFromWorkspaceRoot
    excludeYoutubeCandidateJsonPaths = $resolvedExcludeYoutubeCandidatesJson
    excludeYoutubeVideoIds = @($ExcludeYoutubeVideoId | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    excludeYoutubeUrls = @($ExcludeYoutubeUrl | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    exerciseListJsonPath = $exerciseListPath
    processingOrder = "pipelined_discovery_source_download_and_bake"
    stagedWaveWorkerMode = if (-not $stagedWavesEnabled) { "disabled" } elseif ($effectiveMaxConcurrentStagedWaves -gt 1) { "workspace_scoped_persistent_cpu_overlap_queue" } else { "workspace_scoped_persistent_serial_queue" }
    speedProfile = $SpeedProfile
    exerciseWorkers = $ExerciseWorkers
    discoveryWorkers = $resolvedDiscoveryWorkers
    bakeWorkers = $resolvedBakeWorkers
    stagedWaveSize = $StagedWaveSize
    stagedWavesEnabled = $stagedWavesEnabled
    maxConcurrentStagedWaves = $effectiveMaxConcurrentStagedWaves
    runningStagedWaveCountHighWater = $runningStagedWaveHighWater
    candidateWorkers = $CandidateWorkers
    maxReconstructionCandidateAttempts = $MaxReconstructionCandidateAttempts
    exerciseMotionContractPrefetch = $contractPrefetchSummary
    parallelism = [ordered]@{
        cpuPrefetchDuringBake = [bool]$CpuPrefetchDuringBake
    prefetchWorkers = $PrefetchWorkers
    prefetchQueueDepth = $PrefetchQueueDepth
    sourceDownloadWorkers = $SourceDownloadWorkers
    sourceDownloadCandidates = $SourceDownloadCandidates
        llamaCppParallel = $LlamaCppParallel
        llamaCppThreadsHttp = $LlamaCppThreadsHttp
        activeDiscoveryWorkerBudget = $activeDiscoveryWorkerBudget
        visionDownloadWorkers = $VisionDownloadWorkers
        discoveryVisionLlmWorkers = $resolvedDiscoveryVisionLlmWorkers
        requestedVisionLlmWorkers = if ($visionLlmWorkersExplicit) { $VisionLlmWorkers } else { $null }
        posePrefilterWorkers = $PosePrefilterWorkers
        semanticGateLlmWorkers = $SemanticGateLlmWorkers
        segmentClassificationWorkers = $SegmentClassificationWorkers
        reviewLlmWorkers = $ReviewLlmWorkers
        gpuDiscoveryStages = $gpuDiscoveryStages
        globalGpuLockEnabled = $globalGpuLockEnabled
        gpuDiscoveryBakeOverlap = $effectiveGpuDiscoveryBakeOverlap
        defaultDiscoveryWorkerCap = $defaultDiscoveryWorkerCap
    }
    llamaCppRuntime = [ordered]@{
        visualModel = $LlamaCppModel
        visualMmproj = $LlamaCppMmproj
        mtpModel = if ([string]::IsNullOrWhiteSpace($LlamaCppMtpModel)) { $null } else { $LlamaCppMtpModel }
        specDraftNMax = $LlamaCppSpecDraftNMax
        textModel = $TextLlamaCppModel
        textMmproj = if ([string]::IsNullOrWhiteSpace($TextLlamaCppMmproj)) { $null } else { $TextLlamaCppMmproj }
        ctxSize = $LlamaCppCtxSize
        fitCtx = $LlamaCppFitCtx
        batchSize = $LlamaCppBatchSize
        ubatchSize = $LlamaCppUBatchSize
        imageMinTokens = $LlamaCppImageMinTokens
        imageMaxTokens = $LlamaCppImageMaxTokens
        mtmdBatchMaxTokens = $LlamaCppMtmdBatchMaxTokens
    }
    sharedLlamaServerEnabled = $effectiveSharedLlamaServer
    sharedLlamaServerSessionDir = $resolvedSharedLlamaServerSessionDir
    warmGvhmrWorkerEnabled = $effectiveWarmGvhmrWorker
    gvhmrWorkerSessionDir = $resolvedGvhmrWorkerSessionDir
    gvhmrWorkerMountRoot = if ($effectiveWarmGvhmrWorker) { $resolvedWorkspaceRoot } else { $null }
    effectiveCandidateBudget = [ordered]@{
        maxCandidates = $MaxCandidates
        candidateReviewBatchSize = $CandidateReviewBatchSize
        candidateReviewTargetSuitableCount = $CandidateReviewTargetSuitableCount
        maxCandidateReviewTargetSuitableCount = $resolvedMaxCandidateReviewTargetSuitableCount
        visionCandidatesPerExercise = $VisionCandidatesPerExercise
        posePrefilterCandidatesPerExercise = $PosePrefilterCandidatesPerExercise
        fallbackCandidates = $FallbackCandidates
        maxFinalOutputRejections = $MaxFinalOutputRejections
    }
    maxSelectedResults = $MaxSelectedResults
    totalExerciseCount = $workItems.Count
    terminalExerciseCount = $summaryItems.Count
    successfulExerciseCount = @($summaryItems | Where-Object status -eq "completed").Count
    unsuccessfulExerciseCount = @($summaryItems | Where-Object status -ne "completed").Count
    pendingExerciseCount = [Math]::Max(0, $workItems.Count - $summaryItems.Count)
    exercises = $summaryItems
}
Write-JsonAtomically -Path $summaryPath -Value $summary

Write-Host "Workout plan JSON: $resolvedWorkoutPlanJson"
Write-Host "Workout-plan exercises JSON: $exerciseListPath"
Write-Host "Summary JSON: $summaryPath"

if (-not [string]::IsNullOrWhiteSpace($MobilePackageOutputJson)) {
    $incompleteExercises = @(
        $summaryItems | Where-Object {
            $_.status -ne "completed" -or
            [string]::IsNullOrWhiteSpace([string]$_.selectedWearSkeletonPath) -or
            -not (Test-Path -LiteralPath ([string]$_.selectedWearSkeletonPath))
        }
    )
    if ($incompleteExercises.Count -gt 0) {
        $incompleteExerciseNames = @(
            $incompleteExercises | ForEach-Object { $_.exerciseName }
        ) -join ", "
        throw "Mobile package was not created because these requested exercises are incomplete: $incompleteExerciseNames"
    }

    $mobilePackageBuilder = Join-Path $PSScriptRoot "build_workout_plan_movement_package.ps1"
    if (-not (Test-Path -LiteralPath $mobilePackageBuilder)) {
        throw "Mobile package builder not found: $mobilePackageBuilder"
    }
    $resolvedRequestedMobilePackageOutputJson = [System.IO.Path]::GetFullPath($MobilePackageOutputJson)
    & $mobilePackageBuilder `
        -WorkoutPlanPackageJson $resolvedWorkoutPlanJson `
        -MotionSummaryJson $summaryPath `
        -OutputJson $resolvedRequestedMobilePackageOutputJson `
        -StrictIdMatch
    if ($LASTEXITCODE -ne 0) {
        throw "Mobile package builder failed with exit code $LASTEXITCODE."
    }
    $resolvedMobilePackageOutputJson = (Resolve-Path -LiteralPath $resolvedRequestedMobilePackageOutputJson).Path
    Write-Host "Mobile workout-plan package: $resolvedMobilePackageOutputJson"
}
$script:MotionRunOutcome = "completed"
} finally {
    if (-not $script:MotionServiceShutdownUnconfirmed) {
        $stagedWorkerStopped = Stop-StagedBakeQueueService -Cancel
        if ($stagedWorkerStopped) {
            $null = Stop-MotionModelServicesAfterStagedWorker `
                -StagedWaveShutdownConfirmed $true `
                -WarmGvhmrWorker $warmGvhmrWorkerInstance `
                -SharedLlamaServer $sharedLlamaServerInstance
        } else {
            $script:MotionServiceShutdownUnconfirmed = $true
        }
    }
    foreach ($sessionDirectory in @($script:MotionServiceSessionLeases.Keys)) {
        $runtimeState = Release-MotionServiceSessionLease -SessionDirectory $sessionDirectory
        if ($runtimeState -ne "stopped") {
            $script:MotionServiceShutdownUnconfirmed = $true
        }
    }
    $finalOutcome = if (Test-MotionRunCancelRequested) { "stopped" } elseif ($script:MotionRunOutcome -eq "completed") { "completed" } else { "failed" }
    try {
        if (Get-Command Write-RunOutcomeArtifacts -ErrorAction SilentlyContinue) {
            Write-RunOutcomeArtifacts -Outcome $finalOutcome
        } else {
            Write-EarlyMotionRunOutcomeSummary -Outcome $finalOutcome
        }
    } catch { Write-Warning "Could not persist final motion-run status: $($_.Exception.Message)" }
    Release-MotionWorkspaceLease -Lease $script:MotionWorkspaceLease
    $script:MotionWorkspaceLease = $null
    if (Test-MotionRunCancelRequested) {
        if ($script:MotionServiceShutdownUnconfirmed) {
            Write-Warning "Motion run cancellation finished, but worker shutdown is unconfirmed; retained ownership evidence requires inspection."
        } else {
            Write-Host "Motion run stopped." -ForegroundColor Yellow
        }
    }
}
