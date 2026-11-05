$ErrorActionPreference = "Stop"
$serverPath = "C:\llama.cpp\current\llama-server.exe"
if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
    throw "Shared llama.cpp runtime is missing at $serverPath. Update the central installation first."
}
$versionOutput = (& $serverPath --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Shared llama.cpp runtime could not start: $serverPath" }
Write-Host "Using shared llama.cpp at $serverPath"
Write-Host $versionOutput
