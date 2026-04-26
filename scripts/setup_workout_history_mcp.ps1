Param(
    [string]$BackupPath,
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8000,
    [string]$VenvPath = ".venv",
    [switch]$NoVenv = $false,
    [switch]$SkipInstall = $false,
    [switch]$WithoutTestDependencies = $false,
    [switch]$StartServer = $false,
    [switch]$StartNgrok = $false
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot

function Resolve-RepoPath([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) {
        return $path
    }
    if ([System.IO.Path]::IsPathRooted($path)) {
        return $path
    }
    return Join-Path $repoRoot $path
}

function Get-ExecutablePath([object]$commandPath) {
    $normalizedPath = if ($commandPath -is [System.Array]) {
        $commandPath -join ""
    } else {
        [string]$commandPath
    }

    if ([System.IO.Path]::IsPathRooted($normalizedPath) -or $normalizedPath.Contains("\") -or $normalizedPath.Contains("/")) {
        return (Get-Item -LiteralPath $normalizedPath).FullName
    }

    $resolvedCommand = Get-Command $normalizedPath -ErrorAction SilentlyContinue
    if (-not $resolvedCommand) {
        throw "Command was not found on PATH: $normalizedPath"
    }
    return $resolvedCommand.Source
}

function Invoke-ExternalCommand {
    param(
        [string]$CommandPath,
        [string[]]$Arguments = @()
    )

    & (Get-ExecutablePath $CommandPath) @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $CommandPath $($Arguments -join ' ')"
    }
}

function Resolve-PythonCommand {
    if ($NoVenv) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCommand) {
            throw "Python was not found on PATH."
        }
        return $pythonCommand.Source
    }

    $resolvedVenvPath = Resolve-RepoPath $VenvPath
    $pythonPath = Join-Path $resolvedVenvPath "Scripts\python.exe"

    if (-not (Test-Path -LiteralPath $pythonPath)) {
        Write-Host "Creating virtual environment: $resolvedVenvPath"
        Invoke-ExternalCommand "python" @("-m", "venv", $resolvedVenvPath)
    }

    return $pythonPath
}

Push-Location $repoRoot
try {
    $pythonPath = Resolve-PythonCommand

    if (-not $SkipInstall) {
        $installTarget = if ($WithoutTestDependencies) { "." } else { ".[test]" }
        Write-Host "Installing MCP package from repo root with target: $installTarget"
        Invoke-ExternalCommand $pythonPath @("-m", "pip", "install", "-e", $installTarget)
    }

    $resolvedBackupPath = $null
    if (-not [string]::IsNullOrWhiteSpace($BackupPath)) {
        $resolvedBackupPath = Resolve-RepoPath $BackupPath
        if (-not (Test-Path -LiteralPath $resolvedBackupPath)) {
            throw "Backup file not found: $resolvedBackupPath"
        }
        $env:MYWORKOUT_BACKUP_PATH = $resolvedBackupPath
    } else {
        $defaultBackupPath = Join-Path $repoRoot "merged_workout_store_backup.json"
        if (Test-Path -LiteralPath $defaultBackupPath) {
            $env:MYWORKOUT_BACKUP_PATH = $defaultBackupPath
            $resolvedBackupPath = $defaultBackupPath
        }
    }

    $env:MYWORKOUT_MCP_HOST = $HostName
    $env:MYWORKOUT_MCP_PORT = [string]$Port

    Write-Host ""
    Write-Host "Workout History MCP configuration for this PowerShell process:"
    Write-Host "  MYWORKOUT_BACKUP_PATH = $env:MYWORKOUT_BACKUP_PATH"
    Write-Host "  MYWORKOUT_MCP_HOST    = $env:MYWORKOUT_MCP_HOST"
    Write-Host "  MYWORKOUT_MCP_PORT    = $env:MYWORKOUT_MCP_PORT"
    Write-Host ""
    Write-Host "Local MCP endpoint:"
    Write-Host "  http://$HostName`:$Port/mcp"
    Write-Host ""

    if ($StartNgrok) {
        $ngrokCommand = Get-Command ngrok -ErrorAction SilentlyContinue
        if (-not $ngrokCommand) {
            throw "ngrok was not found on PATH. Install ngrok or run it manually: ngrok http $Port"
        }
        Write-Host "Starting ngrok in a new hidden process for port $Port."
        Start-Process -FilePath $ngrokCommand.Source -ArgumentList @("http", [string]$Port) -WindowStyle Hidden
        Write-Host "Open the ngrok dashboard or terminal output to copy the HTTPS forwarding URL, then append /mcp."
        Write-Host ""
    }

    if ($StartServer) {
        Write-Host "Starting Workout History MCP server. Keep this window open."
        Invoke-ExternalCommand $pythonPath @("-m", "workout_history_mcp.server")
    } else {
        Write-Host "Setup complete. To start the server with this configuration, run:"
        Write-Host "  & `"$pythonPath`" -m workout_history_mcp.server"
        Write-Host ""
        Write-Host "To expose it with ngrok in another PowerShell window, run:"
        Write-Host "  ngrok http $Port"
    }
} finally {
    Pop-Location
}
