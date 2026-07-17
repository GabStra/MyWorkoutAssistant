param(
    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [string]$ExerciseName,
    [string]$OutputSlug,
    [string]$Workspace = "build/exercise_motion",
    [string]$LlamaCppModel = "C:\\Users\\gabri\\Downloads\\gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
    [string]$LlamaCppMmproj = "C:\\Users\\gabri\\Downloads\\mmproj-BF16(5).gguf",
    [string]$LlamaCppMtpModel = "C:\\Users\\gabri\\Downloads\\mtp-gemma-4-12B-it(1).gguf",
    [int]$LlamaCppSpecDraftNMax = 3,
    [ValidateSet("cpu", "gpu")]
    [string]$LlamaCppBackend = "gpu",
    [string]$LlamaCppServerCommand = "C:\\Users\\gabri\\Downloads\\llama-b10038-bin-win-cuda-12.4-x64\\llama-server.exe",
    [int]$LlamaCppServerPort = 8090,
    [string]$LlamaCppBaseUrl = "http://127.0.0.1:8090",
    [int]$LlamaCppNPredict = 512,
    [double]$LlamaCppTemperature = 1.0,
    [Nullable[double]]$LlamaCppTopP = 0.95,
    [Nullable[int]]$LlamaCppTopK = 64,
    [bool]$LlamaCppDisableReasoning = $false,
    [Nullable[int]]$LlamaCppReasoningBudget = 64,
    [string]$LlamaCppReasoningBudgetMessage = "Now stop thinking and return the JSON object.",
    [int]$LlamaCppImageMinTokens = 1024,
    [int]$LlamaCppImageMaxTokens = 2048,
    [int]$LlamaCppCtxSize = 8192,
    [int]$LlamaCppBatchSize = 256,
    [int]$LlamaCppUBatchSize = 512,
    [string]$LlamaCppFlashAttn = "on",
    [string]$LlamaCppCacheTypeK = "q8_0",
    [string]$LlamaCppCacheTypeV = "q8_0",
    [string]$LlamaCppFit = "on",
    [int]$LlamaCppFitCtx = 8192,
    [int]$LlamaCppFitTarget = 2048,
    [bool]$LlamaCppMmap = $true,
    [bool]$LlamaCppMlock = $false,
    [int]$LlamaCppMtmdBatchMaxTokens = 768,
    [bool]$LlamaCppMmprojOffload = $true,
    [bool]$LlamaCppContBatching = $true,
    [string]$LiteRtModelRepo = "litert-community/gemma-4-E4B-it-litert-lm",
    [string]$LiteRtModelFile = "gemma-4-E4B-it.litertlm",
    [string]$VisionModel = "gemma-4-E4B-it",
    [int]$VisionPort = 8090,
    [ValidateSet("cpu", "gpu", "npu")]
    [string]$LiteRtBackend = "gpu",
    [switch]$UseLiteRt,
    [double]$WindowSeconds = 5.0,
    [double]$OverlapSeconds = 2.5,
    [int]$FramesPerWindow = 20,
    [int]$MaxFrameWidth = 960,
    [double]$MergeGapSeconds = 2.0,
    [double]$ConfidenceThreshold = 0.45,
    [double]$MinSegmentSeconds = 2.0,
    [double]$MaxSegmentSeconds = 20.0,
    [int]$ClassificationWorkers = 3,
    [int]$LlamaCppServerParallel = 1,
    [int]$HealthTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Get-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
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

function Get-LiteRtCommand {
    $repoRoot = Get-RepoRoot
    $venvLiteRt = Join-Path $repoRoot ".venv\Scripts\litert-lm.exe"
    if (Test-Path -LiteralPath $venvLiteRt) {
        return $venvLiteRt
    }
    return "litert-lm"
}

function Get-LlamaCppServerCommand {
    param([string]$ConfiguredCommand)

    if (-not [string]::IsNullOrWhiteSpace($ConfiguredCommand)) {
        return $ConfiguredCommand
    }
    $fallback = "C:\Users\gabri\Downloads\llama-b10038-bin-win-cuda-12.4-x64\llama-server.exe"
    if (Test-Path -LiteralPath $fallback) {
        return $fallback
    }
    return "llama-server.exe"
}

function Resolve-LlamaCppServerProcess {
    param(
        [string]$Command,
        [string]$ModelPath,
        [string]$MmprojPath,
        [string]$MtpModelPath,
        [int]$SpecDraftNMax,
        [string]$Backend,
        [string]$HostAddress,
        [int]$Port,
        [int]$ParallelSlots,
        [bool]$DisableReasoning,
        [Nullable[int]]$ReasoningBudget,
        [string]$ReasoningBudgetMessage,
        [int]$CtxSize,
        [int]$BatchSize,
        [int]$UBatchSize,
        [string]$FlashAttn,
        [string]$CacheTypeK,
        [string]$CacheTypeV,
        [string]$Fit,
        [int]$FitCtx,
        [int]$FitTarget,
        [int]$ImageMinTokens,
        [int]$ImageMaxTokens,
        [int]$MtmdBatchMaxTokens,
        [bool]$Mmap,
        [bool]$Mlock,
        [bool]$MmprojOffload,
        [bool]$ContBatching
    )

    $args = @(
        "-m",
        $ModelPath,
        "--mmproj",
        $MmprojPath,
        "--host",
        $HostAddress,
        "--port",
        "$Port"
    )
    if ($ParallelSlots -gt 1) {
        $args += @("--parallel", "$ParallelSlots")
    }
    if (-not [string]::IsNullOrWhiteSpace($MtpModelPath)) {
        $args += @(
            "--model-draft", $MtpModelPath,
            "--spec-type", "draft-mtp",
            "--spec-draft-n-max", "$SpecDraftNMax"
        )
        $args += if ($Backend -eq "gpu") { @("--gpu-layers-draft", "all") } else { @("--gpu-layers-draft", "0") }
    }
    if ($CtxSize -gt 0) {
        $args += @("--ctx-size", "$CtxSize")
    }
    if ($BatchSize -gt 0) {
        $args += @("--batch-size", "$BatchSize")
    }
    if ($UBatchSize -gt 0) {
        $args += @("--ubatch-size", "$UBatchSize")
    }
    if (-not [string]::IsNullOrWhiteSpace($FlashAttn)) {
        $args += @("--flash-attn", $FlashAttn)
    }
    if (-not [string]::IsNullOrWhiteSpace($CacheTypeK)) {
        $args += @("--cache-type-k", $CacheTypeK)
    }
    if (-not [string]::IsNullOrWhiteSpace($CacheTypeV)) {
        $args += @("--cache-type-v", $CacheTypeV)
    }
    if ($DisableReasoning) {
        $args += @("--reasoning", "off", "--reasoning-format", "none", "--reasoning-budget", "0")
    }
    else {
        $args += @("--reasoning", "on", "--reasoning-format", "deepseek")
        if ($null -ne $ReasoningBudget) {
            $args += @("--reasoning-budget", "$ReasoningBudget")
            if ($ReasoningBudget -ge 0 -and -not [string]::IsNullOrWhiteSpace($ReasoningBudgetMessage)) {
                $args += @("--reasoning-budget-message", $ReasoningBudgetMessage)
            }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($Fit)) {
        $args += @("--fit", $Fit)
    }
    if ($FitCtx -gt 0) {
        $args += @("--fit-ctx", "$FitCtx")
    }
    if ($FitTarget -gt 0) {
        $args += @("--fit-target", "$FitTarget")
    }
    if ($ImageMinTokens -gt 0) {
        $args += @("--image-min-tokens", "$ImageMinTokens")
    }
    if ($ImageMaxTokens -gt 0) {
        $args += @("--image-max-tokens", "$ImageMaxTokens")
    }
    if ($MtmdBatchMaxTokens -gt 0) {
        $args += @("--mtmd-batch-max-tokens", "$MtmdBatchMaxTokens")
    }
    if (-not $Mmap) {
        $args += "--no-mmap"
    }
    if ($Mlock) {
        $args += "--mlock"
    }
    $args += if ($MmprojOffload) { "--mmproj-offload" } else { "--no-mmproj-offload" }
    $args += if ($ContBatching) { "--cont-batching" } else { "--no-cont-batching" }
    if ($Backend -eq "gpu") {
        $args += @("--gpu-layers", "all")
    }
    else {
        $args += @("--gpu-layers", "0")
    }
    return Start-Process -FilePath $Command -ArgumentList $args -PassThru -WindowStyle Hidden
}

function Wait-LlamaCppServer {
    param(
        [string]$HostAddress,
        [int]$Port,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-LlamaCppApiReady -HostAddress $HostAddress -Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-LiteRtModelImported {
    param(
        [string]$CommandPath,
        [string]$ModelRef
    )

    $output = & $CommandPath list 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to list LiteRT-LM models.`n$output"
    }
    return ($output | Select-String -SimpleMatch $ModelRef) -ne $null
}

function Ensure-LiteRtModelImported {
    param(
        [string]$CommandPath,
        [string]$RepoId,
        [string]$ModelFile,
        [string]$ModelRef
    )

    if (Test-LiteRtModelImported -CommandPath $CommandPath -ModelRef $ModelRef) {
        return
    }

    & $CommandPath import --from-huggingface-repo $RepoId $ModelFile $ModelRef
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to import LiteRT-LM model '$ModelRef' from '$RepoId/$ModelFile'."
    }
}

function Test-PortInUse {
    param([int]$Port)
    try {
        return (
            Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue
        ).TcpTestSucceeded
    } catch {
        return $false
    }
}

function Test-LlamaCppApiReady {
    param(
        [string]$HostAddress,
        [int]$Port
    )

    try {
        $response = Invoke-WebRequest -Uri "http://$HostAddress`:$Port/v1/models" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-PathLikeFileName {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    return [System.IO.Path]::GetFileName(($PathValue -replace '/', '\'))
}

function Get-LlamaCppServerModelIds {
    param(
        [string]$HostAddress,
        [int]$Port
    )

    try {
        $payload = Invoke-RestMethod -Uri "http://$HostAddress`:$Port/v1/models" -UseBasicParsing -TimeoutSec 5
    } catch {
        return @()
    }

    $ids = @()
    foreach ($item in @($payload.data)) {
        if ($null -eq $item) {
            continue
        }
        if (-not [string]::IsNullOrWhiteSpace($item.id)) {
            $ids += [string]$item.id
        }
        elseif (-not [string]::IsNullOrWhiteSpace($item.model)) {
            $ids += [string]$item.model
        }
    }
    return $ids
}

function Assert-LlamaCppServerModelMatches {
    param(
        [string]$HostAddress,
        [int]$Port,
        [string]$ExpectedModelPath
    )

    $expectedName = Get-PathLikeFileName $ExpectedModelPath
    $modelIds = @(Get-LlamaCppServerModelIds -HostAddress $HostAddress -Port $Port)
    foreach ($modelId in $modelIds) {
        if ((Get-PathLikeFileName $modelId).Equals($expectedName, [System.StringComparison]::OrdinalIgnoreCase)) {
            return
        }
    }
    $servedModels = if ($modelIds.Count -gt 0) { $modelIds -join ", " } else { "unknown model" }
    throw "Existing llama-server on port $Port is serving $servedModels, but this run expects $expectedName. Stop the existing server or use a different -LlamaCppServerPort."
}

$repoRoot = Get-RepoRoot
$pythonCommand = Get-PythonCommand
$resolvedVideoPath = Resolve-StrictPath $VideoPath

if ([string]::IsNullOrWhiteSpace($OutputSlug)) {
    $OutputSlug = [System.IO.Path]::GetFileNameWithoutExtension($resolvedVideoPath)
}

$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Workspace))
$outputRoot = Join-Path $workspaceRoot $OutputSlug
$framesDir = Join-Path $outputRoot "segment_detection\frames"
$resultJson = Join-Path $outputRoot "segment_detection\segment_detection.json"
New-Item -ItemType Directory -Force -Path $framesDir | Out-Null

$pythonArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "detect-segment",
    "--video-path", $resolvedVideoPath,
    "--out-json", $resultJson,
    "--frames-dir", $framesDir,
    "--window-seconds", "$WindowSeconds",
    "--overlap-seconds", "$OverlapSeconds",
    "--frames-per-window", "$FramesPerWindow",
    "--max-frame-width", "$MaxFrameWidth",
    "--merge-gap-seconds", "$MergeGapSeconds",
    "--confidence-threshold", "$ConfidenceThreshold",
    "--min-segment-seconds", "$MinSegmentSeconds",
    "--max-segment-seconds", "$MaxSegmentSeconds",
    "--classification-workers", "$ClassificationWorkers"
)
$llamaCppServerProcess = $null
$cleanupLlamaCppServer = $false
$resolvedLlamaCppBaseUrl = $LlamaCppBaseUrl

if ($UseLiteRt) {
    $liteRtCommand = Get-LiteRtCommand
    Ensure-LiteRtModelImported `
        -CommandPath $liteRtCommand `
        -RepoId $LiteRtModelRepo `
        -ModelFile $LiteRtModelFile `
        -ModelRef $VisionModel
    $pythonArgs += @(
        "--litert-command", $liteRtCommand,
        "--litert-backend", $LiteRtBackend,
        "--model", $VisionModel
    )
} else {
    if ([string]::IsNullOrWhiteSpace($LlamaCppModel)) {
        throw "Llama.cpp mode requires -LlamaCppModel."
    }
    if (-not (Test-Path -LiteralPath $LlamaCppModel)) {
        throw "Could not find Llama.cpp model file '$LlamaCppModel'."
    }
    if ([string]::IsNullOrWhiteSpace($LlamaCppMmproj)) {
        throw "Llama.cpp mode requires -LlamaCppMmproj."
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppMmproj) -and -not (Test-Path -LiteralPath $LlamaCppMmproj)) {
        throw "Could not find Llama.cpp mmproj file '$LlamaCppMmproj'."
    }
    if (-not [string]::IsNullOrWhiteSpace($LlamaCppMtpModel) -and -not (Test-Path -LiteralPath $LlamaCppMtpModel)) {
        throw "Could not find Llama.cpp MTP model file '$LlamaCppMtpModel'."
    }
    if ($LlamaCppServerPort -lt 1 -or $LlamaCppServerPort -gt 65535) {
        throw "LlamaCppServerPort must be between 1 and 65535."
    }
    $llamaCppServerCommand = Get-LlamaCppServerCommand -ConfiguredCommand $LlamaCppServerCommand
    if (-not (Test-Path -LiteralPath $llamaCppServerCommand)) {
        throw "Could not find llama-server binary '$llamaCppServerCommand'."
    }
    if (-not (Test-PortInUse -Port $LlamaCppServerPort)) {
        $serverHost = "127.0.0.1"
        $resolvedLlamaCppBaseUrl = "http://$serverHost`:$LlamaCppServerPort"
        $parallelSlots = $LlamaCppServerParallel
        if ($parallelSlots -le 0) {
            $parallelSlots = $ClassificationWorkers
        }
        Write-Host "Starting llama-server: $llamaCppServerCommand ..."
        $llamaCppServerProcess = Resolve-LlamaCppServerProcess `
            -Command $llamaCppServerCommand `
            -ModelPath $LlamaCppModel `
            -MmprojPath $LlamaCppMmproj `
            -MtpModelPath $LlamaCppMtpModel `
            -SpecDraftNMax $LlamaCppSpecDraftNMax `
            -Backend $LlamaCppBackend `
            -HostAddress $serverHost `
            -Port $LlamaCppServerPort `
            -ParallelSlots $parallelSlots `
            -DisableReasoning $LlamaCppDisableReasoning `
            -ReasoningBudget $LlamaCppReasoningBudget `
            -ReasoningBudgetMessage $LlamaCppReasoningBudgetMessage `
            -CtxSize $LlamaCppCtxSize `
            -BatchSize $LlamaCppBatchSize `
            -UBatchSize $LlamaCppUBatchSize `
            -FlashAttn $LlamaCppFlashAttn `
            -CacheTypeK $LlamaCppCacheTypeK `
            -CacheTypeV $LlamaCppCacheTypeV `
            -Fit $LlamaCppFit `
            -FitCtx $LlamaCppFitCtx `
            -FitTarget $LlamaCppFitTarget `
            -ImageMinTokens $LlamaCppImageMinTokens `
            -ImageMaxTokens $LlamaCppImageMaxTokens `
            -MtmdBatchMaxTokens $LlamaCppMtmdBatchMaxTokens `
            -Mmap $LlamaCppMmap `
            -Mlock $LlamaCppMlock `
            -MmprojOffload $LlamaCppMmprojOffload `
            -ContBatching $LlamaCppContBatching
        $cleanupLlamaCppServer = $true
        if (-not $llamaCppServerProcess -or $llamaCppServerProcess.HasExited) {
            throw "Failed to start llama-server process."
        }
        if (-not (Wait-LlamaCppServer -HostAddress $serverHost -Port $LlamaCppServerPort -TimeoutSeconds $HealthTimeoutSeconds)) {
            throw "Timed out waiting for llama-server startup on port $LlamaCppServerPort."
        }
    }
    else {
        Write-Host "Using existing server on port $LlamaCppServerPort."
        if (-not (Wait-LlamaCppServer -HostAddress "127.0.0.1" -Port $LlamaCppServerPort -TimeoutSeconds $HealthTimeoutSeconds)) {
            throw "Existing llama-server on port $LlamaCppServerPort did not become ready."
        }
        Assert-LlamaCppServerModelMatches `
            -HostAddress "127.0.0.1" `
            -Port $LlamaCppServerPort `
            -ExpectedModelPath $LlamaCppModel
    }
    $pythonArgs += @(
        "--base-url", $resolvedLlamaCppBaseUrl,
        "--model", $LlamaCppModel,
        "--llama-cpp-backend", $LlamaCppBackend
    )
}

if (-not [string]::IsNullOrWhiteSpace($ExerciseName)) {
    $pythonArgs += @("--exercise-name", $ExerciseName)
}

$pythonArgs += @(
    "--llama-cpp-n-predict", "$LlamaCppNPredict",
    "--llama-cpp-temperature", "$LlamaCppTemperature"
)
if ($LlamaCppTopP.HasValue) {
    $pythonArgs += @("--llama-cpp-top-p", "$LlamaCppTopP")
}
if ($LlamaCppTopK.HasValue) {
    $pythonArgs += @("--llama-cpp-top-k", "$LlamaCppTopK")
}
if ($LlamaCppDisableReasoning) {
    $pythonArgs += "--llama-cpp-disable-reasoning"
}
if ($LlamaCppImageMinTokens -gt 0) {
    $pythonArgs += "--llama-cpp-image-min-tokens", "$LlamaCppImageMinTokens"
}
if ($LlamaCppImageMaxTokens -gt 0) {
    $pythonArgs += "--llama-cpp-image-max-tokens", "$LlamaCppImageMaxTokens"
}

try {
    & $pythonCommand @pythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "exercise segment detection failed with exit code $LASTEXITCODE."
    }
}
finally {
    if ($cleanupLlamaCppServer -and $llamaCppServerProcess -and -not $llamaCppServerProcess.HasExited) {
        $llamaCppServerProcess | Stop-Process -Force
    }
}
