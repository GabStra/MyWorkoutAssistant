param(
    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [string]$ExerciseName,
    [string]$OutputSlug,
    [string]$Workspace = "build/exercise_motion",
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

function Get-LlamaCppCommand {
    param([string]$ConfiguredCommand)

    if ([string]::IsNullOrWhiteSpace($ConfiguredCommand)) {
        return "llama-mtmd-cli"
    }
    return $ConfiguredCommand
}

function Get-LlamaCppServerCommand {
    param(
        [string]$ConfiguredCommand,
        [string]$PrimaryCommand
    )

    if (-not [string]::IsNullOrWhiteSpace($ConfiguredCommand)) {
        return $ConfiguredCommand
    }
    if (-not [string]::IsNullOrWhiteSpace($PrimaryCommand)) {
        $inferred = Join-Path (Split-Path -Parent $PrimaryCommand) "llama-server.exe"
        if (Test-Path -LiteralPath $inferred) {
            return $inferred
        }
    }
    $fallback = "C:\Users\gabri\Downloads\llama-b9555-bin-win-cuda-13.3-x64\llama-server.exe"
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
        [string]$Backend,
        [string]$HostAddress,
        [int]$Port
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
    "--max-segment-seconds", "$MaxSegmentSeconds"
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
    if ($UseLlamaCppServer) {
        if ($LlamaCppServerPort -lt 1 -or $LlamaCppServerPort -gt 65535) {
            throw "LlamaCppServerPort must be between 1 and 65535."
        }
        if ([string]::IsNullOrWhiteSpace($LlamaCppServerCommand)) {
            $llamaCppServerCommand = Get-LlamaCppServerCommand -ConfiguredCommand $LlamaCppServerCommand -PrimaryCommand $LlamaCppCommand
        }
        else {
            $llamaCppServerCommand = $LlamaCppServerCommand
        }
        if (-not (Test-Path -LiteralPath $llamaCppServerCommand)) {
            throw "Could not find llama-server binary '$llamaCppServerCommand'."
        }
        if (-not (Test-PortInUse -Port $LlamaCppServerPort)) {
            $serverHost = "127.0.0.1"
            $resolvedLlamaCppBaseUrl = "http://$serverHost`:$LlamaCppServerPort"
            Write-Host "Starting llama-server: $llamaCppServerCommand ..."
            $llamaCppServerProcess = Resolve-LlamaCppServerProcess `
                -Command $llamaCppServerCommand `
                -ModelPath $LlamaCppModel `
                -MmprojPath $LlamaCppMmproj `
                -Backend $LlamaCppBackend `
                -HostAddress $serverHost `
                -Port $LlamaCppServerPort
            $cleanupLlamaCppServer = $true
            if (-not $llamaCppServerProcess -or $llamaCppServerProcess.HasExited) {
                throw "Failed to start llama-server process."
            }
            if (-not (Wait-LlamaCppServer -HostAddress $serverHost -Port $LlamaCppServerPort -TimeoutSeconds 120)) {
                throw "Timed out waiting for llama-server startup on port $LlamaCppServerPort."
            }
        }
        else {
            Write-Host "Using existing server on port $LlamaCppServerPort."
            if (-not (Wait-LlamaCppServer -HostAddress "127.0.0.1" -Port $LlamaCppServerPort -TimeoutSeconds 120)) {
                throw "Existing llama-server on port $LlamaCppServerPort did not become ready."
            }
        }
        $pythonArgs += @(
            "--base-url", $resolvedLlamaCppBaseUrl,
            "--model", $LlamaCppModel,
            "--llama-cpp-backend", $LlamaCppBackend
        )
    }
    else {
        $pythonArgs += @(
            "--llama-cpp-command", (Get-LlamaCppCommand -ConfiguredCommand $LlamaCppCommand),
            "--llama-cpp-model", $LlamaCppModel,
            "--llama-cpp-backend", $LlamaCppBackend
        )
        if (-not [string]::IsNullOrWhiteSpace($LlamaCppMmproj)) {
            $pythonArgs += "--llama-cpp-mmproj", $LlamaCppMmproj
        }
    }
}

if (-not [string]::IsNullOrWhiteSpace($ExerciseName)) {
    $pythonArgs += @("--exercise-name", $ExerciseName)
}

$pythonArgs += @(
    "--llama-cpp-n-predict", "$LlamaCppNPredict"
)
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
