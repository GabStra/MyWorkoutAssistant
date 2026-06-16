param(
    [Parameter(Mandatory = $true)]
    [string]$CandidatesJson,

    [string]$Workspace = "build/exercise_motion",
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [string]$WhamPython = "python",
    [switch]$UseWhamDocker,
    [string]$WhamDockerImage = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "8g",
    [int]$FallbackCandidates = 3,
    [int]$CandidateWorkers = 2,
    [switch]$EstimateLocalOnly,
    [switch]$SkipSmplify,
    [switch]$NoReuseWhamCache,
    [switch]$SkipMotionTuning,
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
    [switch]$RankPreviewVariants,
    [switch]$SkipPreviewVariantRanking,
    [switch]$SkipSupportDominanceClassification,
    [int]$ReviewFrames = 12,
    [int]$ReviewLlmWorkers = 3,
    [int]$MaxLlmReviewItems = 2,
    [int]$MaxReviewWindows = 3,
    [double]$MinSelectedScore = 0.55,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [string]$LlamaCppModel = "C:\Users\gabri\Downloads\Qwen3VL-8B-Instruct-Q4_K_M.gguf",
    [string]$LlamaCppCommand,
    [string]$LlamaCppServerCommand,
    [string]$LlamaCppMmproj = "C:\Users\gabri\Downloads\mmproj-Qwen3VL-8B-Instruct-F16.gguf",
    [string]$LlamaCppBackend = "gpu",
    [int]$LlamaCppNPredict = 768,
    [double]$LlamaCppTemperature = 0.0,
    [bool]$LlamaCppDisableReasoning = $true,
    [Nullable[int]]$LlamaCppCtxSize = $null,
    [Nullable[int]]$LlamaCppBatchSize = 2048,
    [Nullable[int]]$LlamaCppUBatchSize = 512,
    [ValidateSet("on", "off", "auto")]
    [string]$LlamaCppFlashAttn = "auto",
    [Nullable[int]]$LlamaCppThreadsHttp = 6,
    [Nullable[int]]$LlamaCppCacheReuse = $null,
    [bool]$LlamaCppMmprojOffload = $true,
    [bool]$LlamaCppContBatching = $true,
    [Nullable[int]]$LlamaCppImageMinTokens,
    [Nullable[int]]$LlamaCppImageMaxTokens,
    [switch]$NoLlamaCppAutoStartServer,
    [bool]$KeepLlamaCppServer = $true,
    [double]$LlamaCppServerStartupTimeoutSeconds = 180.0,
    [double]$LlamaCppRequestTimeoutSeconds = 90.0
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
    $pythonCommand = Get-Command python -ErrorAction Stop
    if ($pythonCommand.Source) {
        return $pythonCommand.Source
    }
    return $pythonCommand.Path
}

$repoRoot = Get-RepoRoot
$resolvedCandidatesJson = Resolve-StrictPath $CandidatesJson

if ($ReselectExisting) {
    $pythonCommand = Get-BasicPythonCommand
    $argsList = @(
        "-m", "exercise_motion_pkg.cli",
        "reselect-baked",
        "--workspace", $Workspace,
        "--min-selected-score", "$MinSelectedScore",
        "--review-frames", "$ReviewFrames",
        "--max-review-windows", "$MaxReviewWindows"
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

$argsList = @(
    "-m", "exercise_motion_pkg.cli",
    "bake-and-rank",
    "--candidates-json", $resolvedCandidatesJson,
    "--fallback-candidates", "$FallbackCandidates",
    "--candidate-workers", "$CandidateWorkers",
    "--workspace", $Workspace,
    "--wham-repo-path", $resolvedWhamRepoPath,
    "--body-model-root", $resolvedBodyModelRoot,
    "--wham-python", $WhamPython,
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
    "--llama-cpp-base-url", $LlamaCppBaseUrl,
    "--llama-cpp-model", $LlamaCppModel,
    "--llama-cpp-mmproj", $LlamaCppMmproj,
    "--llama-cpp-backend", $LlamaCppBackend,
    "--llama-cpp-n-predict", "$LlamaCppNPredict",
    "--llama-cpp-temperature", "$LlamaCppTemperature",
    "--llama-cpp-server-startup-timeout-seconds", "$LlamaCppServerStartupTimeoutSeconds",
    "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds"
)

if (-not $SkipPreviewVariantRanking) {
    $argsList += "--rank-preview-variants"
}
if ($SkipSupportDominanceClassification) {
    $argsList += "--no-classify-support-dominance"
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppCommand)) {
    $argsList += @("--llama-cpp-command", $LlamaCppCommand)
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppServerCommand)) {
    $argsList += @("--llama-cpp-server-command", $LlamaCppServerCommand)
}
if ($LlamaCppCtxSize.HasValue) {
    $argsList += @("--llama-cpp-ctx-size", "$LlamaCppCtxSize")
}
if ($LlamaCppBatchSize.HasValue) {
    $argsList += @("--llama-cpp-batch-size", "$LlamaCppBatchSize")
}
if ($LlamaCppUBatchSize.HasValue) {
    $argsList += @("--llama-cpp-ubatch-size", "$LlamaCppUBatchSize")
}
if (-not [string]::IsNullOrWhiteSpace($LlamaCppFlashAttn)) {
    $argsList += @("--llama-cpp-flash-attn", $LlamaCppFlashAttn)
}
if ($LlamaCppThreadsHttp.HasValue) {
    $argsList += @("--llama-cpp-threads-http", "$LlamaCppThreadsHttp")
}
if ($LlamaCppCacheReuse.HasValue) {
    $argsList += @("--llama-cpp-cache-reuse", "$LlamaCppCacheReuse")
}
if (-not $LlamaCppMmprojOffload) {
    $argsList += "--no-llama-cpp-mmproj-offload"
}
if (-not $LlamaCppContBatching) {
    $argsList += "--no-llama-cpp-cont-batching"
}
if ($LlamaCppImageMinTokens.HasValue) {
    $argsList += @("--llama-cpp-image-min-tokens", "$LlamaCppImageMinTokens")
}
if ($LlamaCppImageMaxTokens.HasValue) {
    $argsList += @("--llama-cpp-image-max-tokens", "$LlamaCppImageMaxTokens")
}
if ($NoLlamaCppAutoStartServer) {
    $argsList += "--no-llama-cpp-auto-start-server"
}
if (-not $LlamaCppDisableReasoning) {
    $argsList += "--no-llama-cpp-disable-reasoning"
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
if (-not [string]::IsNullOrWhiteSpace($SegmentBaseUrl)) {
    $argsList += @("--segment-base-url", $SegmentBaseUrl)
}
if (-not [string]::IsNullOrWhiteSpace($SegmentModel)) {
    $argsList += @("--segment-model", $SegmentModel)
}
if ($SkipSourceSegmentDetection) {
    $argsList += "--skip-source-segment-detection"
}

& $pythonCommand @argsList
if ($LASTEXITCODE -ne 0) {
    throw "exercise motion bake-and-rank failed with exit code $LASTEXITCODE."
}
