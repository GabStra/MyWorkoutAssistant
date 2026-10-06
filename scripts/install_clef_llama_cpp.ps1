param(
    [string]$ReleaseTag = "b11433"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$runtimeRoot = Join-Path $repoRoot "build\clef_runtime"
$downloadRoot = Join-Path $runtimeRoot "downloads"
$installRoot = Join-Path $runtimeRoot "llama.cpp\$ReleaseTag"
New-Item -ItemType Directory -Force -Path $downloadRoot, $installRoot | Out-Null

if ($ReleaseTag -ne "b11433") {
    throw "This installer currently pins the verified Clef-capable release b11433."
}

$assets = @(
    @{
        Name = "llama-b11433-bin-win-cuda-12.4-x64.zip"
        Url = "https://github.com/ggml-org/llama.cpp/releases/download/b11433/llama-b11433-bin-win-cuda-12.4-x64.zip"
        Sha256 = "ca560fd770cd849195c7aed269d65c23107486dbf4655b1d64df894c6549e09a"
    },
    @{
        Name = "cudart-llama-bin-win-cuda-12.4-x64.zip"
        Url = "https://github.com/ggml-org/llama.cpp/releases/download/b11433/cudart-llama-bin-win-cuda-12.4-x64.zip"
        Sha256 = "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"
    }
)

foreach ($asset in $assets) {
    $archivePath = Join-Path $downloadRoot $asset.Name
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
        Write-Host "Downloading $($asset.Name)"
        Invoke-WebRequest -Uri $asset.Url -OutFile $archivePath
    }
    $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $asset.Sha256) {
        throw "SHA-256 mismatch for $($asset.Name): expected $($asset.Sha256), got $actualHash"
    }
}

$serverPath = Join-Path $installRoot "llama-server.exe"
if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
    Expand-Archive -LiteralPath (Join-Path $downloadRoot $assets[0].Name) -DestinationPath $installRoot -Force
}
Expand-Archive -LiteralPath (Join-Path $downloadRoot $assets[1].Name) -DestinationPath $installRoot -Force

if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
    throw "The b11433 archive did not contain llama-server.exe at the expected path: $serverPath"
}

$versionOutput = (& $serverPath --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "(?i)(?:b11433|build\s+11433)") {
    throw "Installed llama-server did not report b11433. Output: $versionOutput"
}

Write-Host "Installed verified llama.cpp $versionOutput at $serverPath"
Write-Host "Runtime downloads and extracted files are kept under build\clef_runtime."
