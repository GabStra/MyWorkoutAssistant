param(
    [string]$LlamaServerPath,
    [string]$HuggingFaceRepository = "ggml-org/Clef-Flash-GGUF",
    [string]$ModelFile = "Clef-Flash-Q4_K_M.gguf",
    [string]$MmprojFile = "mmproj-Clef-Flash-BF16.gguf",
    [int]$Port = 8091,
    [int]$ContextSize = 8192,
    [int]$BatchSize = 3072,
    [int]$UBatchSize = 3072,
    [int]$GpuLayers = 99
)

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$runtimeRoot = Join-Path $repoRoot "build\clef_runtime"
$env:HF_HOME = Join-Path $runtimeRoot "hf-home"
$modelDirectory = Join-Path $runtimeRoot "hf-model"
$modelPath = Join-Path $modelDirectory $ModelFile
$mmprojPath = Join-Path $modelDirectory $MmprojFile
New-Item -ItemType Directory -Force -Path $env:HF_HOME, $modelDirectory | Out-Null
$hfCommand = $null
if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf)) {
    $hfCommand = Get-Command -Name "hf" -ErrorAction Stop
    & $hfCommand.Source download $HuggingFaceRepository $ModelFile --local-dir $modelDirectory
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $modelPath -PathType Leaf)) {
        throw "Hugging Face download failed for $HuggingFaceRepository/$ModelFile."
    }
}
if (-not (Test-Path -LiteralPath $mmprojPath -PathType Leaf)) {
    if ($null -eq $hfCommand) {
        $hfCommand = Get-Command -Name "hf" -ErrorAction Stop
    }
    & $hfCommand.Source download $HuggingFaceRepository $MmprojFile --local-dir $modelDirectory
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $mmprojPath -PathType Leaf)) {
        throw "Hugging Face download failed for $HuggingFaceRepository/$MmprojFile."
    }
}

if ([string]::IsNullOrWhiteSpace($LlamaServerPath)) {
    $workspaceServer = Join-Path $runtimeRoot "llama.cpp\b11433\llama-server.exe"
    if (Test-Path -LiteralPath $workspaceServer -PathType Leaf) {
        $LlamaServerPath = $workspaceServer
    } else {
        $LlamaServerPath = "llama-server"
    }
}

$resolvedCommand = Get-Command -Name $LlamaServerPath -ErrorAction SilentlyContinue
if ($null -ne $resolvedCommand) {
    $serverExe = $resolvedCommand.Source
} elseif (Test-Path -LiteralPath $LlamaServerPath -PathType Leaf) {
    $serverExe = (Resolve-Path -LiteralPath $LlamaServerPath).Path
} else {
    throw "llama-server was not found. Extract the workspace runtime or pass -LlamaServerPath <path>."
}

$versionOutput = (& $serverExe --version 2>&1 | Out-String).Trim()
Write-Host "Using llama-server: $serverExe"
Write-Host "Version: $versionOutput"
Write-Host "Clef typed image decisions use the /v1/systemone endpoint and the configured multimodal projector."
Write-Host "The server will stay in this terminal; stop it with Ctrl+C."

$serverArgs = @(
    "-m", $modelPath,
    "--mmproj", $mmprojPath,
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--ctx-size", "$ContextSize",
    "--batch-size", "$BatchSize",
    "--ubatch-size", "$UBatchSize",
    "--n-gpu-layers", "$GpuLayers"
)
if ($GpuLayers -le 0) {
    $serverArgs += @("--mmproj-device", "none")
}

& $serverExe @serverArgs
exit $LASTEXITCODE
