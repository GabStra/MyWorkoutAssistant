param(
    [Parameter(Mandatory = $true)]
    [string]$CandidatesJson,

    [string]$Workspace = "build/exercise_motion",
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [string]$WhamPython = "python",
    [switch]$UseWhamDocker,
    [string]$WhamDockerImage = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "16g",
    [bool]$WarmWhamWorker = $false,
    [switch]$SkipWarmWhamWorker,
    [string]$WhamWorkerSessionDir,
    [double]$WhamWorkerStartupTimeoutSeconds = 600.0,
    [double]$WhamWorkerJobTimeoutSeconds = 0.0,
    [double]$WhamTimeoutSeconds = 0.0,
    [Alias("YoutubeCookiesPath")]
    [string]$YoutubeCookies,
    [int]$FallbackCandidates = 12,
    [int]$MaxSourceWindowAttempts = 3,
    [int]$MaxFinalOutputRejections = 3,
    [int]$MaxSelectedResults = 1,
    [int]$CandidateWorkers = 1,
    [switch]$EstimateLocalOnly,
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
    [switch]$ReselectExisting,
    [string]$SegmentBaseUrl,
    [string]$SegmentModel,
    [double]$SegmentWindowSeconds = 5.0,
    [double]$SegmentOverlapSeconds = 2.5,
    [int]$SegmentFramesPerWindow = 20,
    [double]$SegmentConfidenceThreshold = 0.45,
    [double]$SegmentPaddingSeconds = 0.35,
    [double]$SegmentEndPaddingSeconds = 0.35,
    [double]$SegmentMinSeconds = 2.0,
    [double]$SegmentMaxSeconds = 20.0,
    [switch]$SkipPreWhamSourceValidation,
    [switch]$NoExerciseMotionContract,
    [switch]$RankPreviewVariants,
    [switch]$AdaptivePreviewSettings,
    [switch]$SkipAdaptivePreviewSettings,
    [int]$MaxAdaptivePreviewSettings = 2,
    [switch]$SkipPreviewVariantRanking,
    [switch]$ClassifySupportDominance,
    [switch]$SkipSupportDominanceClassification,
    [int]$ReviewFrames = 12,
    [int]$ReviewLlmWorkers = 12,
    [int]$MaxLlmReviewItems = 2,
    [int]$MaxReviewWindows = 0,
    [double]$MinSelectedScore = 0.55,
    [bool]$FinalOutputValidation = $true,
    [switch]$SkipFinalOutputValidation,
    [double]$FinalOutputValidationMinScore = 0.90,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [string]$LlamaCppModel = "C:\Users\gabri\Downloads\gemma-4-12b-it-UD-Q4_K_XL.gguf",
    [string]$LlamaCppServerCommand = "C:\Users\gabri\Downloads\llama-b9936-bin-win-cuda-12.4-x64\llama-server.exe",
    [string]$LlamaCppMmproj = "C:\Users\gabri\Downloads\mmproj-BF16(4).gguf",
    [string]$LlamaCppBackend = "gpu",
    [int]$LlamaCppNPredict = 512,
    [double]$LlamaCppTemperature = 1.0,
    [Nullable[double]]$LlamaCppTopP = 0.95,
    [Nullable[int]]$LlamaCppTopK = 64,
    [bool]$LlamaCppDisableReasoning = $false,
    [Nullable[int]]$LlamaCppReasoningBudget = 64,
    [string]$LlamaCppReasoningBudgetMessage = "Now stop thinking and return the JSON object.",
    [Nullable[int]]$LlamaCppCtxSize = 8192,
    [Nullable[int]]$LlamaCppBatchSize = 256,
    [Nullable[int]]$LlamaCppUBatchSize = 512,
    [ValidateSet("on", "off", "auto")]
    [string]$LlamaCppFlashAttn = "on",
    [ValidateSet("f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1")]
    [string]$LlamaCppCacheTypeK = "q8_0",
    [ValidateSet("f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1")]
    [string]$LlamaCppCacheTypeV = "q8_0",
    [Nullable[int]]$LlamaCppParallel = 1,
    [Nullable[int]]$LlamaCppThreadsHttp,
    [Nullable[int]]$LlamaCppCacheReuse = $null,
    [ValidateSet("on", "off")]
    [string]$LlamaCppFit = "on",
    [Nullable[int]]$LlamaCppFitCtx = 8192,
    [Nullable[int]]$LlamaCppFitTarget = 2048,
    [bool]$LlamaCppMmap = $true,
    [bool]$LlamaCppMlock = $false,
    [bool]$LlamaCppMmprojOffload = $true,
    [bool]$LlamaCppContBatching = $true,
    [Nullable[int]]$LlamaCppImageMinTokens = 1024,
    [Nullable[int]]$LlamaCppImageMaxTokens = 2048,
    [Nullable[int]]$LlamaCppMtmdBatchMaxTokens = 768,
    [switch]$NoLlamaCppAutoStartServer,
    [bool]$KeepLlamaCppServer = $false,
    [double]$LlamaCppServerStartupTimeoutSeconds = 180.0,
    [double]$LlamaCppRequestTimeoutSeconds = 240.0,
    [ValidateSet("debug", "full")]
    [string]$ArtifactRetention = "full"
)

$ErrorActionPreference = "Stop"

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Get-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
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
    $cudaPython = "C:\Users\gabri\miniconda3\envs\mwa-motion-cuda\python.exe"
    if ((Test-Path -LiteralPath $cudaPython) -and (Test-PythonRuntime $cudaPython)) {
        return $cudaPython
    }
    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = if ($pythonCommand.Source) { $pythonCommand.Source } else { $pythonCommand.Path }
    if (-not (Test-PythonRuntime $pythonPath)) {
        throw "Could not find a Python runtime with torch, smplx, and joblib."
    }
    return $pythonPath
}

function Get-BasicPythonCommand {
    if (-not [string]::IsNullOrWhiteSpace($env:EXERCISE_MOTION_PYTHON)) {
        return $env:EXERCISE_MOTION_PYTHON
    }
    $cudaPython = "C:\Users\gabri\miniconda3\envs\mwa-motion-cuda\python.exe"
    if (Test-Path -LiteralPath $cudaPython) {
        return $cudaPython
    }
    $pythonCommand = Get-Command python -ErrorAction Stop
    if ($pythonCommand.Source) {
        return $pythonCommand.Source
    }
    return $pythonCommand.Path
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

$repoRoot = Get-RepoRoot
$resolvedCandidatesJson = Resolve-StrictPath $CandidatesJson
if ($MaxSelectedResults -lt 1) {
    throw "MaxSelectedResults must be at least 1."
}
Ensure-LlamaCppParallelContext

if ($ReselectExisting) {
    $pythonCommand = Get-BasicPythonCommand
    $argsList = @(
        "-m", "exercise_motion_pkg.cli",
        "reselect-baked",
        "--workspace", $Workspace,
        "--min-selected-score", "$MinSelectedScore",
        "--review-frames", "$ReviewFrames",
        "--max-review-windows", "$MaxReviewWindows",
        "--max-selected-results", "$MaxSelectedResults"
    )
    & $pythonCommand @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "exercise motion baked reselection failed with exit code $LASTEXITCODE."
    }
    return
}

$pythonCommand = Get-PythonCommand

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
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
$resolvedWorkspaceRoot = (Resolve-Path -LiteralPath $Workspace).Path
$effectiveWarmWhamWorker = $WarmWhamWorker -and -not $SkipWarmWhamWorker -and $UseWhamDocker
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

$argsList = @(
    "-m", "exercise_motion_pkg.cli",
    "bake-and-rank",
    "--candidates-json", $resolvedCandidatesJson,
    "--fallback-candidates", "$FallbackCandidates",
    "--max-source-window-attempts", "$MaxSourceWindowAttempts",
    "--max-final-output-rejections", "$MaxFinalOutputRejections",
    "--max-selected-results", "$MaxSelectedResults",
    "--candidate-workers", "$CandidateWorkers",
    "--workspace", $Workspace,
    "--wham-repo-path", $resolvedWhamRepoPath,
    "--body-model-root", $resolvedBodyModelRoot,
    "--wham-python", $WhamPython,
    "--wham-timeout-seconds", "$WhamTimeoutSeconds",
    "--segment-window-seconds", "$SegmentWindowSeconds",
    "--segment-overlap-seconds", "$SegmentOverlapSeconds",
    "--segment-frames-per-window", "$SegmentFramesPerWindow",
    "--segment-confidence-threshold", "$SegmentConfidenceThreshold",
    "--segment-padding-seconds", "$SegmentPaddingSeconds",
    "--segment-end-padding-seconds", "$SegmentEndPaddingSeconds",
    "--segment-min-seconds", "$SegmentMinSeconds",
    "--segment-max-seconds", "$SegmentMaxSeconds",
    "--review-frames", "$ReviewFrames",
    "--review-llm-workers", "$ReviewLlmWorkers",
    "--max-llm-review-items", "$MaxLlmReviewItems",
    "--max-review-windows", "$MaxReviewWindows",
    "--min-selected-score", "$MinSelectedScore",
    "--final-output-validation-min-score", "$FinalOutputValidationMinScore",
    "--llama-cpp-base-url", $LlamaCppBaseUrl,
    "--llama-cpp-model", $LlamaCppModel,
    "--llama-cpp-mmproj", $LlamaCppMmproj,
    "--llama-cpp-backend", $LlamaCppBackend,
    "--llama-cpp-n-predict", "$LlamaCppNPredict",
    "--llama-cpp-temperature", "$LlamaCppTemperature",
    "--llama-cpp-server-startup-timeout-seconds", "$LlamaCppServerStartupTimeoutSeconds",
    "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds",
    "--artifact-retention", $ArtifactRetention
)
if ($FinalOutputValidation -and -not $SkipFinalOutputValidation) {
    $argsList += "--final-output-validation"
}
if ($SkipFinalOutputValidation) {
    $argsList += "--skip-final-output-validation"
}
if ($null -ne $LlamaCppTopP) {
    $argsList += @("--llama-cpp-top-p", "$LlamaCppTopP")
}
if ($null -ne $LlamaCppTopK) {
    $argsList += @("--llama-cpp-top-k", "$LlamaCppTopK")
}

if ($RankPreviewVariants -and -not $SkipPreviewVariantRanking) {
    $argsList += "--rank-preview-variants"
}
if ($AdaptivePreviewSettings -or (-not $SkipAdaptivePreviewSettings -and -not $RankPreviewVariants)) {
    $argsList += @(
        "--adaptive-preview-settings",
        "--max-adaptive-preview-settings", "$MaxAdaptivePreviewSettings"
    )
}
if (-not $ClassifySupportDominance -or $SkipSupportDominanceClassification) {
    $argsList += "--no-classify-support-dominance"
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppServerCommand)) {
    $argsList += @("--llama-cpp-server-command", $LlamaCppServerCommand)
}
if ($null -ne $LlamaCppCtxSize) {
    $argsList += @("--llama-cpp-ctx-size", "$LlamaCppCtxSize")
}
if ($null -ne $LlamaCppBatchSize) {
    $argsList += @("--llama-cpp-batch-size", "$LlamaCppBatchSize")
}
if ($null -ne $LlamaCppUBatchSize) {
    $argsList += @("--llama-cpp-ubatch-size", "$LlamaCppUBatchSize")
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppFlashAttn)) {
    $argsList += @("--llama-cpp-flash-attn", $LlamaCppFlashAttn)
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppCacheTypeK)) {
    $argsList += @("--llama-cpp-cache-type-k", $LlamaCppCacheTypeK)
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppCacheTypeV)) {
    $argsList += @("--llama-cpp-cache-type-v", $LlamaCppCacheTypeV)
}
if ($null -ne $LlamaCppParallel) {
    $argsList += @("--llama-cpp-parallel", "$LlamaCppParallel")
}
if ($null -ne $LlamaCppThreadsHttp) {
    $argsList += @("--llama-cpp-threads-http", "$LlamaCppThreadsHttp")
}
if ($null -ne $LlamaCppCacheReuse) {
    $argsList += @("--llama-cpp-cache-reuse", "$LlamaCppCacheReuse")
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppFit)) {
    $argsList += @("--llama-cpp-fit", $LlamaCppFit)
}
if ($null -ne $LlamaCppFitCtx) {
    $argsList += @("--llama-cpp-fit-ctx", "$LlamaCppFitCtx")
}
if ($null -ne $LlamaCppFitTarget) {
    $argsList += @("--llama-cpp-fit-target", "$LlamaCppFitTarget")
}
if (-not $LlamaCppMmap) {
    $argsList += "--no-llama-cpp-mmap"
}
if ($LlamaCppMlock) {
    $argsList += "--llama-cpp-mlock"
}
if (-not $LlamaCppMmprojOffload) {
    $argsList += "--no-llama-cpp-mmproj-offload"
}
if (-not $LlamaCppContBatching) {
    $argsList += "--no-llama-cpp-cont-batching"
}
if ($null -ne $LlamaCppImageMinTokens) {
    $argsList += @("--llama-cpp-image-min-tokens", "$LlamaCppImageMinTokens")
}
if ($null -ne $LlamaCppImageMaxTokens) {
    $argsList += @("--llama-cpp-image-max-tokens", "$LlamaCppImageMaxTokens")
}
if ($null -ne $LlamaCppMtmdBatchMaxTokens) {
    $argsList += @("--llama-cpp-mtmd-batch-max-tokens", "$LlamaCppMtmdBatchMaxTokens")
}
if ($NoLlamaCppAutoStartServer) {
    $argsList += "--no-llama-cpp-auto-start-server"
}
if ($LlamaCppDisableReasoning) {
    $argsList += "--llama-cpp-disable-reasoning"
}
if ($null -ne $LlamaCppReasoningBudget) {
    $argsList += @("--llama-cpp-reasoning-budget", "$LlamaCppReasoningBudget")
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppReasoningBudgetMessage)) {
    $argsList += @("--llama-cpp-reasoning-budget-message", $LlamaCppReasoningBudgetMessage)
}
if (-not [string]::IsNullOrWhiteSpace($YoutubeCookies)) {
    $argsList += @("--youtube-cookies", (Resolve-StrictPath $YoutubeCookies))
}
if ($KeepLlamaCppServer) {
    $argsList += "--keep-llama-cpp-server"
}
if ($UseWhamDocker) {
    $argsList += @(
        "--use-wham-docker",
        "--wham-docker-image", $WhamDockerImage,
        "--wham-docker-gpus", $WhamDockerGpus,
        "--wham-docker-shm-size", $WhamDockerShmSize
    )
}
if ($effectiveWarmWhamWorker) {
    $argsList += @(
        "--warm-wham-worker",
        "--wham-worker-session-dir", $resolvedWhamWorkerSessionDir,
        "--wham-worker-mount-root", $resolvedWorkspaceRoot,
        "--wham-worker-timeout-seconds", "$WhamWorkerJobTimeoutSeconds"
    )
}
if ($EstimateLocalOnly) {
    $argsList += "--estimate-local-only"
}
if ($SkipSmplify) {
    $argsList += "--skip-smplify"
}
if ($NoReuseWhamCache) {
    $argsList += "--no-reuse-wham-cache"
}
if ($SkipMotionTuning) {
    $argsList += "--skip-motion-tuning"
}
if ($ExportWhamSmplPreview) {
    $argsList += "--export-wham-smpl-preview"
}
if ($SkipSpinePose -or -not $EnableSpinePose) {
    $argsList += "--skip-spinepose"
}
else {
    $argsList += @(
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
    $argsList += "--enable-spinepose"
    if (-not [string]::IsNullOrWhiteSpace($SpinePoseJsonDir)) {
        $argsList += @("--spinepose-json-dir", (Resolve-StrictPath $SpinePoseJsonDir))
    }
    if (-not [string]::IsNullOrWhiteSpace($SpinePoseCommand)) {
        $argsList += @("--spinepose-command", $SpinePoseCommand)
    }
    if (-not [string]::IsNullOrWhiteSpace($SpinePoseOutputDir)) {
        $argsList += @("--spinepose-output-dir", $SpinePoseOutputDir)
    }
    if ($SpinePoseInvert) {
        $argsList += "--spinepose-invert"
    }
    if ($NoReuseSpinePoseCache) {
        $argsList += "--no-spinepose-cache"
    }
}
if (-not [string]::IsNullOrWhiteSpace($SegmentBaseUrl)) {
    $argsList += @("--segment-base-url", $SegmentBaseUrl)
}
if (-not [string]::IsNullOrWhiteSpace($SegmentModel)) {
    $argsList += @("--segment-model", $SegmentModel)
}
if ($SkipSourceSegmentDetection) {
    $argsList += "--skip-source-segment-detection"
}
if (-not $SkipPreWhamSourceValidation) {
    $argsList += "--pre-wham-source-validation"
}
if ($SkipPreWhamSourceValidation) {
    $argsList += "--skip-pre-wham-source-validation"
}
if ($NoExerciseMotionContract) {
    $argsList += "--no-exercise-motion-contract"
}

try {
    $warmWhamWorkerInstance = $null
    if ($effectiveWarmWhamWorker) {
        $warmWhamWorkerInstance = Start-WhamWarmWorker `
            -SessionDir $resolvedWhamWorkerSessionDir `
            -MountRoot $resolvedWorkspaceRoot `
            -WorkerScriptPath $whamWarmWorkerScriptPath
    }
    & $pythonCommand @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "exercise motion bake-and-rank failed with exit code $LASTEXITCODE."
    }
}
finally {
    Stop-WhamWarmWorker -Worker $warmWhamWorkerInstance
}

$selectionPath = Join-Path $Workspace "selection_manifest.json"
if (Test-Path -LiteralPath $selectionPath) {
    $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-Json
    if ($selection.selected) {
        Write-Host "Wear skeleton JSON: $($selection.selected.selectedWearSkeletonPath)"
        if ($selection.PSObject.Properties.Name -contains "selectedResults" -and @($selection.selectedResults).Count -gt 1) {
            Write-Host "Selected result options: $(@($selection.selectedResults).Count)"
            $optionIndex = 1
            foreach ($option in @($selection.selectedResults)) {
                Write-Host "  Option ${optionIndex}: $($option.selectedWearSkeletonPath)"
                $optionIndex += 1
            }
        }
        if ($selection.selected.PSObject.Properties.Name -contains "wearSkeletonSettingsBaked") {
            Write-Host "Wear skeleton settings baked: $($selection.selected.wearSkeletonSettingsBaked)"
        }
        $selectedOptions = if ($selection.PSObject.Properties.Name -contains "selectedResults" -and $selection.selectedResults) {
            @($selection.selectedResults)
        } else {
            @($selection.selected)
        }
        $optionIndex = 1
        foreach ($option in $selectedOptions) {
            if ($option.wearSkeletonSettingsBaked -ne $true) {
                $contractJson = $option.wearSkeletonPreviewSettingsContract | ConvertTo-Json -Depth 8
                throw "Selected Wear skeleton option $optionIndex does not contain the baked preview settings required by Wear. Contract: $contractJson"
            }
            $optionIndex += 1
        }
    } else {
        Write-Host "Selected Wear skeleton: none"
        throw "Bake-and-rank completed without selecting a Wear skeleton. Inspect $selectionPath."
    }
}
