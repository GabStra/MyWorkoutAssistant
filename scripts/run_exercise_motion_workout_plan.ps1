[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkoutPlanJson,

    [string]$EquipmentJson,
    [string]$WorkspaceRoot = "build/exercise_motion/workout-plan",
    [ValidateSet("quality", "fast", "max")]
    [string]$SpeedProfile = "fast",
    [string[]]$OnlyExerciseSlug = @(),
    [string[]]$OnlyExerciseId = @(),
    [string[]]$OnlyExerciseName = @(),
    [string[]]$ExcludeCandidatesFromWorkspaceRoot = @(),
    [string[]]$ExcludeYoutubeCandidatesJson = @(),
    [string[]]$ExcludeYoutubeVideoId = @(),
    [string[]]$ExcludeYoutubeUrl = @(),
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [string]$YouTubeCookiesPath,
    [string]$YouTubePreviewCacheDir,
    [string]$PythonCommand = "",
    [int]$ResultsPerQuery = 100,
    [int]$MaxCandidates = 12,
    [int]$CandidateReviewBatchSize = 12,
    [int]$CandidateReviewTargetSuitableCount = 2,
    [Nullable[int]]$MaxCandidateReviewTargetSuitableCount = 6,
    [switch]$UseLlamaCppQueryPlanner,
    [switch]$SkipLlamaCppQueryPlanner,
    [switch]$UseDeepSeekQueryPlanner,
    [string]$DeepSeekApiKey,
    [string]$DeepSeekBaseUrl = "https://api.deepseek.com",
    [string]$DeepSeekModel = "deepseek-v4-flash",
    [int]$DeepSeekMaxQueries = 4,
    [int]$VisionCandidatesPerExercise = 12,
    [int]$VisionFramesPerCandidate = 6,
    [int]$VisionMaxChunksPerCandidate = 0,
    [int]$VisionDownloadWorkers = 8,
    [int]$VisionLlmWorkers = 4,
    [switch]$NoExerciseNameRewrite,
    [switch]$NoExerciseMotionContract,
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
    [ValidateSet("auto", "allow", "avoid")]
    [string]$GpuDiscoveryBakeOverlap = "auto",
    [int]$FallbackCandidates = 12,
    [int]$MaxSourceWindowAttempts = 5,
    [int]$MaxFinalOutputRejections = 6,
    [double]$SourceReviewTimeoutSeconds = 90.0,
    [double]$FinalReviewTimeoutSeconds = 120.0,
    [double]$CandidateTimeoutSeconds = 0.0,
    [double]$ExerciseTimeoutSeconds = 0.0,
    [int]$MaxSelectedResults = 1,
    [int]$CandidateWorkers = 1,
    [switch]$ReuseExistingSelected,
    [switch]$IncludeDisabled,
    [switch]$NoWhamDocker,
    [string]$WhamDockerImage = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "16g",
    [bool]$WarmWhamWorker = $false,
    [switch]$SkipWarmWhamWorker,
    [string]$WhamWorkerSessionDir,
    [double]$WhamWorkerStartupTimeoutSeconds = 600.0,
    [double]$WhamWorkerJobTimeoutSeconds = 0.0,
    [double]$WhamTimeoutSeconds = 0.0,
    [switch]$FullWhamCameraSlam,
    [switch]$SkipSmplify,
    [switch]$RunSmplify,
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
    [switch]$SkipPreWhamSourceValidation,
    [int]$SegmentClassificationWorkers = 3,
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
    [double]$FinalOutputValidationMinScore = 0.90,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [string]$LlamaCppModel = "C:\Users\gabri\Downloads\Qwen3-VL-8B-Instruct-UD-Q6_K_XL.gguf",
    [string]$LlamaCppServerCommand = "C:\Users\gabri\Downloads\llama-b9936-bin-win-cuda-12.4-x64\llama-server.exe",
    [string]$LlamaCppMmproj = "C:\Users\gabri\Downloads\mmproj-BF16(3).gguf",
    [string]$TextLlamaCppModel = "C:\Users\gabri\Downloads\gemma-4-12B-it-heretic-QAT-UD-Q4_K_XL.gguf",
    [AllowEmptyString()]
    [string]$TextLlamaCppMmproj = "",
    [string]$LlamaCppBackend = "gpu",
    [double]$LlamaCppTemperature = 1.0,
    [Nullable[double]]$LlamaCppTopP = 0.95,
    [Nullable[int]]$LlamaCppTopK = 64,
    [Nullable[int]]$LlamaCppCtxSize = 8192,
    [Nullable[int]]$LlamaCppBatchSize = 256,
    [Nullable[int]]$LlamaCppUBatchSize = 512,
    [string]$LlamaCppFlashAttn = "on",
    [string]$LlamaCppCacheTypeK = "q8_0",
    [string]$LlamaCppCacheTypeV = "q8_0",
    [Nullable[int]]$LlamaCppParallel = 1,
    [Nullable[int]]$LlamaCppThreadsHttp,
    [Nullable[int]]$LlamaCppCacheReuse,
    [string]$LlamaCppFit = "on",
    [Nullable[int]]$LlamaCppFitCtx = 8192,
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
    [double]$LlamaCppRequestTimeoutSeconds = 240.0,
    [ValidateSet("debug", "full")]
    [string]$ArtifactRetention = "full",
    [int]$ProgressIntervalSeconds = 90,
    [switch]$DetailedProgressLogs,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArguments = @()
)

$ErrorActionPreference = "Stop"
$script:LastProgressDetailByLogPath = @{}

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

function Add-LlamaCppTextArgs {
    param([string[]]$Arguments)
    $result = @($Arguments)
    if (-not [string]::IsNullOrWhiteSpace($TextLlamaCppModel)) {
        $result += @("--text-llama-cpp-model", $TextLlamaCppModel)
    }
    if (-not [string]::IsNullOrWhiteSpace($TextLlamaCppMmproj)) {
        $result += @("--text-llama-cpp-mmproj", $TextLlamaCppMmproj)
    }
    return $result
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
    $minContextPerSlot = 4096
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
        [string]$ExerciseSlug
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
    if ($LASTEXITCODE -ne 0) {
        throw "python command failed with exit code $LASTEXITCODE."
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
    param([string]$Path)
    $counts = [ordered]@{
        candidateCount = 0
        recommendedCount = 0
    }
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $counts
    }
    try {
        $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
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
        whamRunSeconds = 0.0
        whamDockerLockWaitSeconds = 0.0
        previewBakeSeconds = 0.0
        whamGeneratedCount = 0
        whamReusedCount = 0
        whamExplicitCount = 0
        whamNotUsedCount = 0
        warmWhamWorkerJobCount = 0
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
        $whamTiming = Get-ObjectProperty -Object $generationTimings -Name "wham"
        if ((Get-ObjectProperty -Object $whamTiming -Name "warmWorker") -eq $true) {
            $summary.warmWhamWorkerJobCount += 1
        }
        $summary.whamRunSeconds = Add-OptionalSeconds -Current $summary.whamRunSeconds -Value (Get-ObjectProperty -Object $whamTiming -Name "elapsedSeconds")
        $summary.whamDockerLockWaitSeconds = Add-OptionalSeconds -Current $summary.whamDockerLockWaitSeconds -Value (Get-ObjectProperty -Object $whamTiming -Name "dockerLockWaitSeconds")
        $whamCacheStatus = [string](Get-ObjectProperty -Object $candidate -Name "whamCacheStatus")
        if ([string]::IsNullOrWhiteSpace($whamCacheStatus)) {
            $whamCacheStatus = [string](Get-ObjectProperty -Object $whamTiming -Name "cacheStatus")
        }
        switch -Regex ($whamCacheStatus) {
            "^generated" { $summary.whamGeneratedCount += 1; break }
            "^reused" { $summary.whamReusedCount += 1; break }
            "^explicit" { $summary.whamExplicitCount += 1; break }
            "^not_used" { $summary.whamNotUsedCount += 1; break }
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
            discoverySeconds = [Math]::Round([double]$WorkItem.discoverySeconds, 3)
            bakeCommandSeconds = [Math]::Round([double]$WorkItem.bakeCommandSeconds, 3)
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
    foreach ($propertyName in @("sourceExerciseName", "equipmentQualifiedExerciseName", "exerciseNameRewrite")) {
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
    param([object]$Options)

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
    $previewOptions["cameraYawDegrees"] = 45.0
    $previewOptions["cameraPitchDegrees"] = 30.0
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

function Start-WhamWarmWorker {
    param(
        [string]$SessionDir,
        [string]$MountRoot,
        [string]$WorkerScriptPath
    )

    New-Item -ItemType Directory -Force -Path $SessionDir | Out-Null
    foreach ($child in @("jobs", "running", "results", "job_logs")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $SessionDir $child) | Out-Null
    }
    foreach ($staleFile in @("ready.json", "startup_error.json", "stop", "stopped.json")) {
        $path = Join-Path $SessionDir $staleFile
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }

    $containerName = "mwa-wham-worker-$([guid]::NewGuid().ToString('N'))"
    $dockerArgs = @("run", "-d", "--rm", "--name", $containerName)
    if (-not [string]::IsNullOrWhiteSpace($WhamDockerGpus)) {
        $dockerArgs += @("--gpus", $WhamDockerGpus)
    }
    if (-not [string]::IsNullOrWhiteSpace($WhamDockerShmSize)) {
        $dockerArgs += @("--shm-size", $WhamDockerShmSize)
    }
    $dockerArgs += @(
        "-v", "$($resolvedWhamRepoPath):/code",
        "-v", "$($MountRoot):/workspace",
        "-v", "$($SessionDir):/worker_state",
        "-v", "$($WorkerScriptPath):/worker/wham_warm_worker.py:ro",
        "-w", "/code",
        $WhamDockerImage,
        "python", "-u", "/worker/wham_warm_worker.py",
        "--state-dir", "/worker_state"
    )

    Write-Host "Starting warm WHAM worker container '$containerName'."
    $containerId = (& docker @dockerArgs 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start warm WHAM worker container: $containerId"
    }
    $containerId = ([string]$containerId).Trim()
    $readyPath = Join-Path $SessionDir "ready.json"
    $startupErrorPath = Join-Path $SessionDir "startup_error.json"
    $deadline = (Get-Date).AddSeconds($WhamWorkerStartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $readyPath) {
            $ready = Get-Content -LiteralPath $readyPath -Raw | ConvertFrom-Json
            Write-Host ("Warm WHAM worker ready in {0}s. GPU: {1}" -f $ready.loadSeconds, $ready.gpuName)
            return [pscustomobject]@{
                containerName = $containerName
                containerId = $containerId
                sessionDir = $SessionDir
                mountRoot = $MountRoot
                readyPath = $readyPath
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
            throw "Warm WHAM worker failed during startup: $errorPayload"
        }
        $running = (& docker inspect -f "{{.State.Running}}" $containerName 2>$null)
        if ($LASTEXITCODE -ne 0 -or "$running".Trim().ToLowerInvariant() -ne "true") {
            $logs = (& docker logs $containerName 2>&1)
            throw "Warm WHAM worker container exited before ready. Logs: $logs"
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
    throw "Timed out waiting for warm WHAM worker startup after $WhamWorkerStartupTimeoutSeconds seconds."
}

function Stop-WhamWarmWorker {
    param([object]$Worker)
    if ($null -eq $Worker) {
        return
    }
    try {
        "stop" | Set-Content -LiteralPath (Join-Path $Worker.sessionDir "stop") -Encoding UTF8
    } catch {
    }
    try {
        & docker stop --time 10 $Worker.containerName | Out-Null
    } catch {
        Write-Warning "Failed to stop warm WHAM worker container '$($Worker.containerName)': $($_.Exception.Message)"
    }
}

function Remove-ExerciseIntermediateArtifacts {
    param([object]$WorkItem)

    if ($ArtifactRetention -eq "full") {
        return
    }

    foreach ($path in @($WorkItem.bakeWorkspace)) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
    foreach ($path in @($WorkItem.exercisePlanPath, $WorkItem.exerciseCandidatesPath)) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}

function Get-ExistingSelectedSummary {
    param([object]$WorkItem)

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

    $previewFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_selected_preview.webm" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    $inputFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_selected_input.mp4" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    $inputWebmFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_selected_input.webm" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    $previewHtmlFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_selected_preview.html" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    $interactivePreviewHtmlFiles = @(Get-ChildItem -LiteralPath $selectedOutputDir -Filter "$($selectedFilePrefix)*_interactive_preview.html" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    $debugDir = Join-Path $selectedOutputDir "debug"
    $candidateDebugPath = Join-Path $debugDir "youtube_candidates.full.json"
    $candidateDecisionsPath = Join-Path $debugDir "candidate_decisions.jsonl"

    $selection = $null
    try {
        $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-Json
    } catch {
        $selection = $null
    }
    $manifestSelected = if ($selection -and $selection.selected) { $selection.selected } else { $null }
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

    Write-Host "[reused] $($WorkItem.exerciseName) -> $selectedOutputDir"

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

function Start-InitialDiscoveryJob {
    param([object]$WorkItem)

    Write-Host "[start] discovery: $($WorkItem.exerciseName)"
    $job = Start-Job -Name "discover-$($WorkItem.exerciseSlug)" -ScriptBlock {
        param(
            [string]$PythonCommand,
            [string[]]$DiscoveryArguments,
            [string]$LogPath,
            [string]$CandidatesPath,
            [int]$InitialTargetSuitableCount,
            [int]$MaxTargetSuitableCount,
            [int]$BaseMaxCandidates,
            [int]$BaseVisionCandidates
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
                    $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
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
        "[$(Get-Date -Format o)] movement generation started" | Set-Content -LiteralPath $LogPath -Encoding UTF8
        $targetSuitableCount = [Math]::Max(1, $InitialTargetSuitableCount)
        $attemptMaxCandidates = [Math]::Max($BaseMaxCandidates, $targetSuitableCount)
        $attemptVisionCandidates = [Math]::Max($BaseVisionCandidates, $targetSuitableCount)
        $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $DiscoveryArguments -Name "--candidate-review-target-suitable-count" -Value "$targetSuitableCount"
        $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--max-candidates" -Value "$attemptMaxCandidates"
        $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--vision-candidates-per-exercise" -Value "$attemptVisionCandidates"

        "[$(Get-Date -Format o)] initial discovery attempt 1 started; target suitable candidates $targetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        & $PythonCommand @attemptDiscoveryArgs *>> $LogPath
        $exitCode = $LASTEXITCODE
        $stopwatch.Stop()
        $counts = Get-CandidateCounts -Path $CandidatesPath
        "[$(Get-Date -Format o)] initial discovery attempt 1 finished with exit code $exitCode; recommended $($counts.recommendedCount), candidates $($counts.candidateCount), elapsed $([Math]::Round($stopwatch.Elapsed.TotalSeconds, 3))s" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        [pscustomobject]@{
            exitCode = $exitCode
            stage = "initial_discovery"
            logPath = $LogPath
            candidateCount = $counts.candidateCount
            recommendedCount = $counts.recommendedCount
            discoverySeconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
            attemptIndex = 1
            targetSuitableCount = $targetSuitableCount
        }
    } -ArgumentList $PythonCommand, ([string[]]$WorkItem.discoveryArgs), $WorkItem.logPath, $WorkItem.exerciseCandidatesPath, $WorkItem.candidateReviewTargetSuitableCount, $WorkItem.maxCandidateReviewTargetSuitableCount, $WorkItem.maxCandidates, $WorkItem.visionCandidatesPerExercise
    $job | Add-Member -MemberType NoteProperty -Name WorkItem -Value $WorkItem
    return $job
}

function Start-BakeJob {
    param(
        [object]$WorkItem,
        [bool]$UseExistingCandidatesForFirstAttempt = $true
    )

    Write-Host "[start] bake: $($WorkItem.exerciseName)"
    $job = Start-Job -Name $WorkItem.exerciseSlug -ScriptBlock {
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
            [bool]$UseExistingCandidatesForFirstAttempt
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
                $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
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

        function Get-SelectedResultCount {
            param([string]$Workspace)
            $selectionPath = Join-Path $Workspace "selection_manifest.json"
            if (-not (Test-Path -LiteralPath $selectionPath)) {
                return 0
            }
            try {
                $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-Json
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
                $snapshotPath = Join-Path $snapshotDir ("youtube_candidates.attempt-{0:D2}.json" -f $AttemptIndex)
                Copy-Item -LiteralPath $Path -Destination $snapshotPath -Force
                return $snapshotPath
            } catch {
                "[$(Get-Date -Format o)] failed to snapshot attempt $AttemptIndex candidates for retry exclusion: $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                return $null
            }
        }

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
        if (Test-Path -LiteralPath $LogPath) {
            "[$(Get-Date -Format o)] bake stage started" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        } else {
            "[$(Get-Date -Format o)] movement generation started" | Set-Content -LiteralPath $LogPath -Encoding UTF8
            "[$(Get-Date -Format o)] bake stage started" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        }
        $targetSuitableCount = [Math]::Max(1, $InitialTargetSuitableCount)
        $attemptIndex = 1
        $previousAttemptCandidateJsonPaths = @()
        $useExistingCandidates = $UseExistingCandidatesForFirstAttempt -and (Test-Path -LiteralPath $CandidatesPath)
        $discoverySecondsTotal = 0.0
        $bakeSecondsTotal = 0.0
        $discoveryAttemptCount = 0
        $bakeAttemptCount = 0
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
                $attemptMaxCandidates = [Math]::Max($BaseMaxCandidates, $targetSuitableCount)
                $attemptVisionCandidates = [Math]::Max($BaseVisionCandidates, $targetSuitableCount)
                $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $DiscoveryArguments -Name "--candidate-review-target-suitable-count" -Value "$targetSuitableCount"
                $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--max-candidates" -Value "$attemptMaxCandidates"
                $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--vision-candidates-per-exercise" -Value "$attemptVisionCandidates"
                foreach ($previousAttemptCandidateJsonPath in @($previousAttemptCandidateJsonPaths | Select-Object -Unique)) {
                    if (Test-Path -LiteralPath $previousAttemptCandidateJsonPath) {
                        $attemptDiscoveryArgs += @("--exclude-youtube-candidates-json", $previousAttemptCandidateJsonPath)
                    }
                }

                "[$(Get-Date -Format o)] discovery attempt $attemptIndex started; target suitable candidates $targetSuitableCount/$MaxTargetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                $discoveryStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
                & $PythonCommand @attemptDiscoveryArgs *>> $LogPath
                $discoveryExitCode = $LASTEXITCODE
                $discoveryStopwatch.Stop()
                $discoverySeconds = [Math]::Round($discoveryStopwatch.Elapsed.TotalSeconds, 3)
                $discoverySecondsTotal = [Math]::Round(($discoverySecondsTotal + $discoverySeconds), 3)
                $discoveryAttemptCount += 1
                $recommendedCount = Get-RecommendedCandidateCount -Path $CandidatesPath
                $attempts += [ordered]@{
                    attemptIndex = $attemptIndex
                    stage = "discovery"
                    exitCode = $discoveryExitCode
                    targetSuitableCount = $targetSuitableCount
                    recommendedCount = $recommendedCount
                    elapsedSeconds = $discoverySeconds
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

                if (Test-Path -LiteralPath $CandidatesPath) {
                    $attemptCandidateSnapshotPath = Save-AttemptCandidateSnapshot -Path $CandidatesPath -AttemptIndex $attemptIndex
                    if (-not [string]::IsNullOrWhiteSpace($attemptCandidateSnapshotPath)) {
                        $previousAttemptCandidateJsonPaths += $attemptCandidateSnapshotPath
                    }
                }
            }
            if ($recommendedCount -le 0) {
                if ($targetSuitableCount -ge $MaxTargetSuitableCount) {
                    [pscustomobject]@{
                        exitCode = 0
                        stage = "discovery_no_recommended"
                        logPath = $LogPath
                        discoverySeconds = $discoverySecondsTotal
                        bakeSeconds = $bakeSecondsTotal
                        discoveryAttemptCount = $discoveryAttemptCount
                        bakeAttemptCount = $bakeAttemptCount
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
            if ($bakeAttemptCount -gt 0) {
                $attemptBakeArguments += "--reuse-previous-terminal-results"
            }
            & $PythonCommand @attemptBakeArguments *>> $LogPath
            $bakeExitCode = $LASTEXITCODE
            $bakeStopwatch.Stop()
            $bakeSeconds = [Math]::Round($bakeStopwatch.Elapsed.TotalSeconds, 3)
            $bakeSecondsTotal = [Math]::Round(($bakeSecondsTotal + $bakeSeconds), 3)
            $bakeAttemptCount += 1

            $selectedResultCount = Get-SelectedResultCount -Workspace $BakeWorkspace
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
                if ($selectedResultCount -lt $MaxSelectedResults -and $targetSuitableCount -lt $MaxTargetSuitableCount) {
                    $targetSuitableCount = [Math]::Min($MaxTargetSuitableCount, $targetSuitableCount + 1)
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
                [pscustomobject]@{
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
                return
            }
            if ($bakeExitCode -ne 0) {
                "[$(Get-Date -Format o)] bake returned exit code $bakeExitCode after writing a no-selection manifest; expanding review target if possible" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            }

            if ($targetSuitableCount -ge $MaxTargetSuitableCount) {
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

            $targetSuitableCount = [Math]::Min($MaxTargetSuitableCount, $targetSuitableCount + 1)
            $attemptIndex += 1
            "[$(Get-Date -Format o)] no selected Wear skeleton; expanding review target to $targetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        }
    } -ArgumentList $PythonCommand, ([string[]]$WorkItem.discoveryArgs), ([string[]]$WorkItem.bakeArgs), $WorkItem.logPath, $WorkItem.exerciseCandidatesPath, $WorkItem.bakeWorkspace, $WorkItem.candidateReviewTargetSuitableCount, $WorkItem.maxCandidateReviewTargetSuitableCount, $WorkItem.maxCandidates, $WorkItem.visionCandidatesPerExercise, $WorkItem.maxSelectedResults, $UseExistingCandidatesForFirstAttempt
    $job | Add-Member -MemberType NoteProperty -Name WorkItem -Value $WorkItem
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

    if ($status -eq "completed" -and (-not $jobResult -or $jobResult.exitCode -ne 0)) {
        $status = "failed"
        $exitCode = if ($jobResult) { $jobResult.exitCode } else { "unknown" }
        $stage = if ($jobResult -and $jobResult.stage) { $jobResult.stage } else { "unknown" }
        $failureStage = $stage
        $errorMessage = "python $stage command failed with exit code $exitCode. See log: $($workItem.logPath)"
    }

    $selectionPath = Join-Path $workItem.bakeWorkspace "selection_manifest.json"
    $selection = $null
    if (Test-Path -LiteralPath $selectionPath) {
        $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-Json
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
        if ($manualReviewFallback) {
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
            $exerciseCandidateManifest = Get-Content -LiteralPath $workItem.exerciseCandidatesPath -Raw | ConvertFrom-Json
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
            -Options (Get-ObjectProperty -Object $manualReviewFallback -Name "settingsOptions")
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
            $optionInteractivePreviewSourcePath = Get-ObjectProperty -Object $option -Name "sourcePreviewHtmlPath"
            $optionInteractivePreviewPath = Copy-SelectedFile `
                -SourcePath $optionInteractivePreviewSourcePath `
                -DestinationDirectory $selectedOutputDir `
                -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_interactive_preview.html"
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
            $optionSettingsOptionsJson = ConvertTo-SelectedPreviewOptionsJson -Options $optionSettingsOptions
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
            $selectedResultOutputs += [ordered]@{
                optionIndex = $optionIndex
                label = if ($option.PSObject.Properties.Name -contains "manualSelectionLabel") { $option.manualSelectionLabel } else { "Option $optionIndex" }
                selectedWearSkeletonPath = $optionWearSkeletonPath
                selectedPreviewVideoPath = $optionPreviewVideoPath
                selectedPreviewHtmlPath = $optionPreviewHtmlPath
                selectedInteractivePreviewHtmlPath = $optionInteractivePreviewPath
                selectedSourceVideoPath = $optionInputVideoPath
                selectedSourceVideoWebmPath = $optionInputVideoWebmPath
                selectedSourceVideoOriginalPath = $optionInputVideoSourcePath
                selectedSourceVideoMissing = $optionInputVideoMissing
                selectionScore = if ($option.PSObject.Properties.Name -contains "selectionScore") { $option.selectionScore } else { $null }
                candidateTitle = if ($option.PSObject.Properties.Name -contains "candidateTitle") { $option.candidateTitle } else { $null }
            }
            if ($optionIndex -eq 1) {
                $selectedWearSkeletonPath = $optionWearSkeletonPath
                $selectedPreviewVideoPath = $optionPreviewVideoPath
                $selectedInteractivePreviewHtmlPath = $optionInteractivePreviewPath
                $selectedInputVideoPath = $optionInputVideoPath
                $selectedInputVideoWebmPath = $optionInputVideoWebmPath
                $selectedInputVideoSourcePath = $optionInputVideoSourcePath
                $selectedInputVideoMissing = $optionInputVideoMissing
            }
            $optionIndex += 1
        }
        if ($status -eq "completed") {
            Remove-ExerciseIntermediateArtifacts -WorkItem $workItem
        }
    }

    if ($status -eq "completed") {
        $optionText = if ($selectedResultOutputs.Count -gt 1) { " ($($selectedResultOutputs.Count) options)" } else { "" }
        Write-Host "[$status] $($workItem.exerciseName) -> $selectedOutputDir$optionText"
    } else {
        $stageText = if (-not [string]::IsNullOrWhiteSpace($failureStage)) { " [$failureStage]" } else { "" }
        $reasonText = if (-not [string]::IsNullOrWhiteSpace($errorMessage)) { " - $errorMessage" } else { "" }
        Write-Host "[$status] $($workItem.exerciseName)$stageText (log: $($workItem.logPath))$reasonText"
    }

    return [ordered]@{
        exerciseId = $workItem.exerciseId
        exerciseName = $workItem.exerciseName
        status = $status
        error = $errorMessage
        stage = if ($status -eq "failed" -and -not [string]::IsNullOrWhiteSpace($failureStage)) { $failureStage } elseif ($status -eq "no_selection") { "bake_no_selection" } elseif ($status -eq "needs_manual_review") { "manual_review" } else { $null }
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
            discoverySeconds = [Math]::Round(($initialDiscoverySeconds + $retryDiscoverySeconds), 3)
            initialDiscoverySeconds = [Math]::Round($initialDiscoverySeconds, 3)
            retryDiscoverySeconds = [Math]::Round($retryDiscoverySeconds, 3)
            bakeCommandSeconds = [Math]::Round($bakeCommandSeconds, 3)
            discoveryAttempts = ([int]$workItem.discoveryAttemptCount + [int](Get-ObjectProperty -Object $jobResult -Name "discoveryAttemptCount"))
            bakeAttempts = [int](Get-ObjectProperty -Object $jobResult -Name "bakeAttemptCount")
            selection = $selectionTimingSummary
        }
    }
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
    $usefulPatterns = @(
        "initial discovery attempt",
        "bake stage started",
        "using pre-discovered candidates",
        "discovery attempt",
        "bake attempt",
        "selected \d+/\d+ result",
        "no recommended candidates",
        "no selected Wear skeleton",
        "finished with exit code",
        "returned exit code",
        "failed",
        "Traceback",
        "Exception",
        "ERROR"
    )
    for ($index = $lines.Count - 1; $index -ge 0; $index -= 1) {
        $line = [string]$lines[$index]
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            $trimmed = $line.Trim()
            if ($Detailed) {
                return $trimmed
            }
            foreach ($pattern in $usefulPatterns) {
                if ($trimmed -match $pattern) {
                    return $trimmed
                }
            }
        }
    }
    return $null
}

function Write-ProgressSnapshot {
    param(
        [string]$Stage = "movement generation",
        [datetime]$StartedAt = [datetime]::MinValue,
        [object[]]$RunningJobs,
        [int]$CompletedCount,
        [int]$TotalCount,
        [int]$PendingCount,
        [switch]$DetailedLogs
    )

    $activeNames = @($RunningJobs | ForEach-Object { $_.WorkItem.exerciseName })
    $elapsedText = ""
    if ($StartedAt -ne [datetime]::MinValue) {
        $elapsedText = " elapsed {0:c}," -f ((Get-Date) - $StartedAt)
    }
    Write-Host ("{0}:{1} {2}/{3} done, {4} running, {5} queued." -f $Stage, $elapsedText, $CompletedCount, $TotalCount, $RunningJobs.Count, $PendingCount)
    if ($DetailedLogs -and $activeNames.Count -gt 0) {
        Write-Host ("  active: {0}" -f ($activeNames -join ", "))
    }
    foreach ($job in $RunningJobs) {
        $latestLine = Get-LatestUsefulLogLine -Path $job.WorkItem.logPath -Detailed:$DetailedLogs
        if (-not $latestLine) {
            continue
        }
        if (-not $DetailedLogs) {
            $detailKey = $job.WorkItem.logPath
            if ($script:LastProgressDetailByLogPath.ContainsKey($detailKey) -and $script:LastProgressDetailByLogPath[$detailKey] -eq $latestLine) {
                continue
            }
            $script:LastProgressDetailByLogPath[$detailKey] = $latestLine
        }
        if ($DetailedLogs) {
            Write-Host ("  {0}: {1}" -f $job.WorkItem.exerciseName, $latestLine)
        } else {
            Write-Host ("  changed: {0}: {1}" -f $job.WorkItem.exerciseName, $latestLine)
        }
    }
}

$repoRoot = Get-RepoRoot
$PythonCommand = Resolve-MotionPythonCommand $PythonCommand
switch ($SpeedProfile) {
    "fast" {
        if (-not $PSBoundParameters.ContainsKey("ResultsPerQuery")) { $ResultsPerQuery = 100 }
        if (-not $PSBoundParameters.ContainsKey("MaxCandidates")) { $MaxCandidates = 24 }
        if (-not $PSBoundParameters.ContainsKey("CandidateReviewBatchSize")) { $CandidateReviewBatchSize = 12 }
        if (-not $PSBoundParameters.ContainsKey("CandidateReviewTargetSuitableCount")) { $CandidateReviewTargetSuitableCount = 1 }
        if (-not $PSBoundParameters.ContainsKey("MaxCandidateReviewTargetSuitableCount")) { $MaxCandidateReviewTargetSuitableCount = 6 }
        if (-not $PSBoundParameters.ContainsKey("VisionCandidatesPerExercise")) { $VisionCandidatesPerExercise = 12 }
        if (-not $PSBoundParameters.ContainsKey("VisionMaxChunksPerCandidate")) { $VisionMaxChunksPerCandidate = 2 }
        if (-not $PSBoundParameters.ContainsKey("PosePrefilterCandidatesPerExercise")) { $PosePrefilterCandidatesPerExercise = 24 }
        if (-not $PSBoundParameters.ContainsKey("FallbackCandidates")) { $FallbackCandidates = 6 }
        if (-not $PSBoundParameters.ContainsKey("MaxSourceWindowAttempts")) { $MaxSourceWindowAttempts = 3 }
        if (-not $PSBoundParameters.ContainsKey("MaxFinalOutputRejections")) { $MaxFinalOutputRejections = 6 }
        if (-not $PSBoundParameters.ContainsKey("NoExerciseNameRewrite")) { $NoExerciseNameRewrite = $true }
        if (-not $PSBoundParameters.ContainsKey("SemanticGateWithLlamaCpp") -and -not $PSBoundParameters.ContainsKey("SkipSemanticGate")) {
            $SkipSemanticGate = $true
        }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppCtxSize")) { $LlamaCppCtxSize = 8192 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppFitCtx")) { $LlamaCppFitCtx = 8192 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppBatchSize")) { $LlamaCppBatchSize = 256 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppUBatchSize")) { $LlamaCppUBatchSize = 512 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppImageMaxTokens")) { $LlamaCppImageMaxTokens = 2048 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppMtmdBatchMaxTokens")) { $LlamaCppMtmdBatchMaxTokens = 768 }
    }
    "max" {
        if (-not $PSBoundParameters.ContainsKey("MaxCandidates")) { $MaxCandidates = 6 }
        if (-not $PSBoundParameters.ContainsKey("CandidateReviewBatchSize")) { $CandidateReviewBatchSize = 6 }
        if (-not $PSBoundParameters.ContainsKey("CandidateReviewTargetSuitableCount")) { $CandidateReviewTargetSuitableCount = 1 }
        if (-not $PSBoundParameters.ContainsKey("MaxCandidateReviewTargetSuitableCount")) { $MaxCandidateReviewTargetSuitableCount = 6 }
        if (-not $PSBoundParameters.ContainsKey("VisionCandidatesPerExercise")) { $VisionCandidatesPerExercise = 6 }
        if (-not $PSBoundParameters.ContainsKey("PosePrefilterCandidatesPerExercise")) { $PosePrefilterCandidatesPerExercise = 6 }
        if (-not $PSBoundParameters.ContainsKey("FallbackCandidates")) { $FallbackCandidates = 2 }
        if (-not $PSBoundParameters.ContainsKey("ReviewFrames")) { $ReviewFrames = 4 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppCtxSize")) { $LlamaCppCtxSize = 8192 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppFitCtx")) { $LlamaCppFitCtx = 8192 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppBatchSize")) { $LlamaCppBatchSize = 256 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppUBatchSize")) { $LlamaCppUBatchSize = 512 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppImageMaxTokens")) { $LlamaCppImageMaxTokens = 2048 }
        if (-not $PSBoundParameters.ContainsKey("LlamaCppMtmdBatchMaxTokens")) { $LlamaCppMtmdBatchMaxTokens = 768 }
    }
}
if ($PSBoundParameters.ContainsKey("LlamaCppCtxSize") -and -not $PSBoundParameters.ContainsKey("LlamaCppFitCtx")) {
    $LlamaCppFitCtx = $LlamaCppCtxSize
}
Ensure-LlamaCppParallelContext
$effectiveSkipSmplify = $SkipSmplify -or (($SpeedProfile -in @("fast", "max")) -and -not $RunSmplify)
$llamaParallelSlots = if ($null -ne $LlamaCppParallel) { [Math]::Max(1, [int]$LlamaCppParallel) } else { 1 }
$visionLlmWorkersExplicit = $PSBoundParameters.ContainsKey("VisionLlmWorkers")
if (-not $PSBoundParameters.ContainsKey("ReviewLlmWorkers")) {
    $ReviewLlmWorkers = [Math]::Max(1, $llamaParallelSlots)
}
if (-not $PSBoundParameters.ContainsKey("SegmentClassificationWorkers")) {
    $SegmentClassificationWorkers = [Math]::Max(1, $llamaParallelSlots)
}
if (-not $PSBoundParameters.ContainsKey("VisionDownloadWorkers")) {
    $VisionDownloadWorkers = [Math]::Max(8, [Math]::Min(16, $llamaParallelSlots * 2))
}
$resolvedWorkoutPlanJson = Resolve-StrictPath $WorkoutPlanJson
if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $EquipmentJson = Resolve-StrictPath $EquipmentJson
}
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $YouTubeCookiesPath = Resolve-StrictPath $YouTubeCookiesPath
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
if ($ExerciseWorkers -lt 1) {
    throw "ExerciseWorkers must be at least 1."
}
$posePrefilterEnabled = $PosePrefilter -or -not $SkipPosePrefilter
if ($posePrefilterEnabled) {
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
$effectiveGpuDiscoveryBakeOverlap = if ($GpuDiscoveryBakeOverlap -eq "auto") {
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
    [Math]::Max($FallbackCandidates, $CandidateReviewTargetSuitableCount, $MaxSelectedResults)
}
$initialTargetSuitableCount = [Math]::Max($CandidateReviewTargetSuitableCount, $MaxSelectedResults)
if ($resolvedMaxCandidateReviewTargetSuitableCount -lt $initialTargetSuitableCount) {
    throw "MaxCandidateReviewTargetSuitableCount must be greater than or equal to CandidateReviewTargetSuitableCount and MaxSelectedResults."
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

$resolvedWhamRepoPath = Resolve-StrictPath $WhamRepoPath
$resolvedBodyModelRoot = Resolve-StrictPath $BodyModelRoot

New-Item -ItemType Directory -Force -Path $WorkspaceRoot | Out-Null
$resolvedWorkspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$effectiveWarmWhamWorker = $WarmWhamWorker -and -not $SkipWarmWhamWorker -and -not $NoWhamDocker
$resolvedWhamWorkerSessionDir = $null
$whamWarmWorkerScriptPath = Join-Path $repoRoot "exercise_motion_pkg\wham_warm_worker.py"
if ($effectiveWarmWhamWorker) {
    if (-not (Test-Path -LiteralPath $whamWarmWorkerScriptPath)) {
        throw "Warm WHAM worker script not found: $whamWarmWorkerScriptPath"
    }
    $activeWhamWorkerSessionDir = if ([string]::IsNullOrWhiteSpace($WhamWorkerSessionDir)) {
        Join-Path $resolvedWorkspaceRoot "wham-warm-worker"
    } else {
        $WhamWorkerSessionDir
    }
    New-Item -ItemType Directory -Force -Path $activeWhamWorkerSessionDir | Out-Null
    $resolvedWhamWorkerSessionDir = (Resolve-Path -LiteralPath $activeWhamWorkerSessionDir).Path
}
$sharedPreviewCachePath = if ([string]::IsNullOrWhiteSpace($YouTubePreviewCacheDir)) {
    Join-Path (Join-Path $repoRoot "build\exercise_motion") "youtube-preview-cache"
} else {
    $YouTubePreviewCacheDir
}
New-Item -ItemType Directory -Force -Path $sharedPreviewCachePath | Out-Null
$exerciseListPath = Join-Path $resolvedWorkspaceRoot "workout_plan_exercises.json"
$summaryPath = Join-Path $resolvedWorkspaceRoot "workout_motion_generation_summary.json"

$listArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "list-workout-plan-exercises",
    "--workout-plan-json", $resolvedWorkoutPlanJson,
    "--out-json", $exerciseListPath
)
if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $listArgs += @("--equipment-json", $EquipmentJson)
}
if ($IncludeDisabled) {
    $listArgs += "--include-disabled"
}
Invoke-PythonModule -Arguments $listArgs

$exerciseList = Get-Content -LiteralPath $exerciseListPath -Raw | ConvertFrom-Json
if (-not $exerciseList.exercises -or $exerciseList.exercises.Count -eq 0) {
    throw "No exercises were found in the workout plan: $resolvedWorkoutPlanJson"
}

$youtubeBaseArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "find-youtube-videos",
    "--results-per-query", "$ResultsPerQuery",
    "--max-candidates", "$MaxCandidates",
    "--candidate-review-batch-size", "$CandidateReviewBatchSize",
    "--candidate-review-target-suitable-count", "$CandidateReviewTargetSuitableCount",
    "--vision-candidates-per-exercise", "$VisionCandidatesPerExercise",
    "--vision-download-workers", "$VisionDownloadWorkers",
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
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $youtubeBaseArgs += @("--youtube-cookies", $YouTubeCookiesPath)
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
    $previewCachePath = $sharedPreviewCachePath
    $bakeWorkspace = Join-Path $exerciseWorkspace "bake"
    $logPath = Join-Path $exerciseWorkspace "bake.log"

    New-Item -ItemType Directory -Force -Path $exerciseWorkspace | Out-Null
    New-OneExercisePlanJson -Exercise $exercise -OutPath $exercisePlanPath

    $discoveryArgs = @($youtubeBaseArgs)
    $discoveryArgs += @(
        "--workout-plan-json", $exercisePlanPath,
        "--out-json", $exerciseCandidatesPath,
        "--youtube-preview-cache-dir", $previewCachePath
    )
    $exerciseExcludeCandidateJsonPaths = @($resolvedExcludeYoutubeCandidatesJson)
    $exerciseExcludeCandidateJsonPaths += Get-PreviousCandidateJsonPaths `
        -WorkspaceRoots $resolvedExcludeCandidatesFromWorkspaceRoot `
        -ExerciseSlug $exerciseSlug
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

    $bakeArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "bake-and-rank",
        "--candidates-json", $exerciseCandidatesPath,
        "--fallback-candidates", "$FallbackCandidates",
        "--max-source-window-attempts", "$MaxSourceWindowAttempts",
        "--max-final-output-rejections", "$MaxFinalOutputRejections",
        "--source-review-timeout-seconds", "$SourceReviewTimeoutSeconds",
        "--final-review-timeout-seconds", "$FinalReviewTimeoutSeconds",
        "--candidate-timeout-seconds", "$CandidateTimeoutSeconds",
        "--exercise-timeout-seconds", "$ExerciseTimeoutSeconds",
        "--max-selected-results", "$MaxSelectedResults",
        "--candidate-workers", "$CandidateWorkers",
        "--workspace", $bakeWorkspace,
        "--wham-repo-path", $resolvedWhamRepoPath,
        "--body-model-root", $resolvedBodyModelRoot,
        "--wham-python", "python",
        "--wham-timeout-seconds", "$WhamTimeoutSeconds",
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
    if (-not $NoWhamDocker) {
        $bakeArgs += @(
            "--use-wham-docker",
            "--wham-docker-image", $WhamDockerImage,
            "--wham-docker-gpus", $WhamDockerGpus,
            "--wham-docker-shm-size", $WhamDockerShmSize
        )
    }
    if ($effectiveWarmWhamWorker) {
        $bakeArgs += @(
            "--warm-wham-worker",
            "--wham-worker-session-dir", $resolvedWhamWorkerSessionDir,
            "--wham-worker-mount-root", $resolvedWorkspaceRoot,
            "--wham-worker-timeout-seconds", "$WhamWorkerJobTimeoutSeconds"
        )
    }
    if (-not $FullWhamCameraSlam) {
        $bakeArgs += "--estimate-local-only"
    }
    if ($effectiveSkipSmplify) {
        $bakeArgs += "--skip-smplify"
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
    if (-not $SkipPreWhamSourceValidation) {
        $bakeArgs += "--pre-wham-source-validation"
    }
    if ($SkipPreWhamSourceValidation) {
        $bakeArgs += "--skip-pre-wham-source-validation"
    }
    if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
        $bakeArgs += @("--youtube-cookies", $YouTubeCookiesPath)
    }

    $workItems += [pscustomobject]@{
        index = $exerciseIndex
        exerciseId = $exerciseId
        exerciseName = $exerciseName
        exerciseSlug = $exerciseSlug
        candidateCount = $null
        exerciseWorkspace = $exerciseWorkspace
        exercisePlanPath = $exercisePlanPath
        exerciseCandidatesPath = $exerciseCandidatesPath
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
        bakeCommandSeconds = 0.0
        discoveryAttemptCount = 0
        bakeAttemptCount = 0
        attempts = @()
        discoveryArgs = [string[]]$discoveryArgs
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
}

$summaryByIndex = @{}
$completedCount = 0
$pendingDiscoveryItems = [System.Collections.Queue]::new()
$pendingBakeItems = [System.Collections.Queue]::new()
foreach ($workItem in $workItems) {
    $existingSummary = if ($ReuseExistingSelected) { Get-ExistingSelectedSummary -WorkItem $workItem } else { $null }
    if ($existingSummary) {
        $summaryByIndex[$workItem.index] = $existingSummary
        $completedCount += 1
        continue
    }
    $pendingDiscoveryItems.Enqueue($workItem)
}

$overallStartedAt = Get-Date
if ($pendingDiscoveryItems.Count -gt 0 -or $pendingBakeItems.Count -gt 0) {
    $discoveryRunningJobs = @()
    $bakeRunningJobs = @()
    $discoveryCompletedCount = 0
    $bakeCompletedCount = 0
    $bakeTotalCount = $pendingBakeItems.Count
    $lastProgressAt = [datetime]::MinValue
    $warmWhamWorkerInstance = $null
    Write-Host "Pipelining candidate discovery and movement baking with $resolvedDiscoveryWorkers discovery worker(s) and $resolvedBakeWorkers bake worker(s)."
    if (-not $NoWhamDocker -and $resolvedBakeWorkers -gt 1) {
        Write-Warning "WHAM Docker runs are still serialized by the shared lock; extra bake workers can overlap non-WHAM work but will not run multiple WHAM containers at once."
    }
    try {
        while (
            $pendingDiscoveryItems.Count -gt 0 -or
            $discoveryRunningJobs.Count -gt 0 -or
            $pendingBakeItems.Count -gt 0 -or
            $bakeRunningJobs.Count -gt 0
        ) {
            $canLaunchDiscovery = -not (
                $avoidGpuDiscoveryBakeOverlap -and
                ($pendingBakeItems.Count -gt 0 -or $bakeRunningJobs.Count -gt 0)
            )
            while ($canLaunchDiscovery -and $pendingDiscoveryItems.Count -gt 0 -and $discoveryRunningJobs.Count -lt $resolvedDiscoveryWorkers) {
                $discoveryRunningJobs += Start-InitialDiscoveryJob -WorkItem ($pendingDiscoveryItems.Dequeue())
            }

            $canLaunchBake = -not (
                $avoidGpuDiscoveryBakeOverlap -and
                $discoveryRunningJobs.Count -gt 0
            )

            if ($canLaunchBake -and $pendingBakeItems.Count -gt 0 -and $null -eq $warmWhamWorkerInstance -and $effectiveWarmWhamWorker) {
                $warmWhamWorkerInstance = Start-WhamWarmWorker `
                    -SessionDir $resolvedWhamWorkerSessionDir `
                    -MountRoot $resolvedWorkspaceRoot `
                    -WorkerScriptPath $whamWarmWorkerScriptPath
            }

            while ($canLaunchBake -and $pendingBakeItems.Count -gt 0 -and $bakeRunningJobs.Count -lt $resolvedBakeWorkers) {
                $bakeRunningJobs += Start-BakeJob -WorkItem ($pendingBakeItems.Dequeue()) -UseExistingCandidatesForFirstAttempt $true
            }

            $runningJobs = @($discoveryRunningJobs + $bakeRunningJobs)
            if ($runningJobs.Count -eq 0) {
                continue
            }

            $now = Get-Date
            if (($now - $lastProgressAt).TotalSeconds -ge $ProgressIntervalSeconds) {
                Write-ProgressSnapshot -Stage "Pipeline" -StartedAt $overallStartedAt -RunningJobs $runningJobs -CompletedCount $completedCount -TotalCount $workItems.Count -PendingCount ($pendingDiscoveryItems.Count + $pendingBakeItems.Count) -DetailedLogs:$DetailedProgressLogs
                $lastProgressAt = $now
            }

            $finishedJobs = @(Wait-Job -Job $runningJobs -Any -Timeout 2)
            if ($finishedJobs.Count -eq 0) {
                continue
            }

            $discoveryJobIds = @($discoveryRunningJobs | ForEach-Object { $_.Id })
            $bakeJobIds = @($bakeRunningJobs | ForEach-Object { $_.Id })
            foreach ($job in $finishedJobs) {
                if ($discoveryJobIds -contains $job.Id) {
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
                    $workItem.discoveryAttemptCount = [int]$workItem.discoveryAttemptCount + 1
                    $workItem.candidateCount = Get-ObjectProperty -Object $jobResult -Name "candidateCount"
                    $workItem.attempts += [ordered]@{
                        attemptIndex = 1
                        stage = "initial_discovery"
                        exitCode = if ($jobResult) { $jobResult.exitCode } else { $null }
                        targetSuitableCount = if ($jobResult) { $jobResult.targetSuitableCount } else { $workItem.candidateReviewTargetSuitableCount }
                        candidateCount = if ($jobResult) { $jobResult.candidateCount } else { 0 }
                        recommendedCount = if ($jobResult) { $jobResult.recommendedCount } else { 0 }
                        elapsedSeconds = $discoverySeconds
                    }

                    if ($status -eq "failed") {
                        Write-Host "[failed] $($workItem.exerciseName) [initial_discovery] (log: $($workItem.logPath)) - $errorMessage"
                        $discoveryExitCode = if ($jobResult) { $jobResult.exitCode } else { "unknown" }
                        $summaryByIndex[$workItem.index] = New-TerminalExerciseSummary -WorkItem $workItem -Status "failed" -ErrorMessage $errorMessage -Stage "initial_discovery" -ExitCode $discoveryExitCode
                        $completedCount += 1
                    } else {
                        $pendingBakeItems.Enqueue($workItem)
                        $bakeTotalCount += 1
                    }
                    $discoveryCompletedCount += 1
                } elseif ($bakeJobIds -contains $job.Id) {
                    $summaryByIndex[$job.WorkItem.index] = Complete-BakeJob -Job $job
                    $completedCount += 1
                    $bakeCompletedCount += 1
                }
            }
            $finishedJobIds = @($finishedJobs | ForEach-Object { $_.Id })
            $discoveryRunningJobs = @($discoveryRunningJobs | Where-Object { $_.Id -notin $finishedJobIds })
            $bakeRunningJobs = @($bakeRunningJobs | Where-Object { $_.Id -notin $finishedJobIds })
        }
    } finally {
        Stop-WhamWarmWorker -Worker $warmWhamWorkerInstance
    }
}

$summaryItems = @()
for ($index = 0; $index -lt $workItems.Count; $index += 1) {
    $summaryItems += $summaryByIndex[$index]
}

$summary = [ordered]@{
    schemaVersion = 1
    generatedAt = (Get-Date).ToUniversalTime().ToString("o")
    sourceWorkoutPlanPath = $resolvedWorkoutPlanJson
    equipmentJsonPath = if ([string]::IsNullOrWhiteSpace($EquipmentJson)) { $null } else { $EquipmentJson }
    workspaceRoot = $resolvedWorkspaceRoot
    excludeCandidatesFromWorkspaceRoots = $resolvedExcludeCandidatesFromWorkspaceRoot
    excludeYoutubeCandidateJsonPaths = $resolvedExcludeYoutubeCandidatesJson
    excludeYoutubeVideoIds = @($ExcludeYoutubeVideoId | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    excludeYoutubeUrls = @($ExcludeYoutubeUrl | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    exerciseListJsonPath = $exerciseListPath
    processingOrder = "pipelined_discovery_and_bake"
    speedProfile = $SpeedProfile
    exerciseWorkers = $ExerciseWorkers
    discoveryWorkers = $resolvedDiscoveryWorkers
    bakeWorkers = $resolvedBakeWorkers
    candidateWorkers = $CandidateWorkers
    parallelism = [ordered]@{
        llamaCppParallel = $LlamaCppParallel
        activeDiscoveryWorkerBudget = $activeDiscoveryWorkerBudget
        visionDownloadWorkers = $VisionDownloadWorkers
        discoveryVisionLlmWorkers = $resolvedDiscoveryVisionLlmWorkers
        requestedVisionLlmWorkers = if ($visionLlmWorkersExplicit) { $VisionLlmWorkers } else { $null }
        posePrefilterWorkers = $PosePrefilterWorkers
        segmentClassificationWorkers = $SegmentClassificationWorkers
        reviewLlmWorkers = $ReviewLlmWorkers
        gpuDiscoveryStages = $gpuDiscoveryStages
        gpuDiscoveryBakeOverlap = $effectiveGpuDiscoveryBakeOverlap
        defaultDiscoveryWorkerCap = $defaultDiscoveryWorkerCap
    }
    llamaCppRuntime = [ordered]@{
        visualModel = $LlamaCppModel
        visualMmproj = $LlamaCppMmproj
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
    warmWhamWorkerEnabled = $effectiveWarmWhamWorker
    whamWorkerSessionDir = $resolvedWhamWorkerSessionDir
    whamWorkerMountRoot = if ($effectiveWarmWhamWorker) { $resolvedWorkspaceRoot } else { $null }
    smplifyEnabled = -not $effectiveSkipSmplify
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
    exercises = $summaryItems
}
$summary | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host "Workout plan JSON: $resolvedWorkoutPlanJson"
Write-Host "Workout-plan exercises JSON: $exerciseListPath"
Write-Host "Summary JSON: $summaryPath"
