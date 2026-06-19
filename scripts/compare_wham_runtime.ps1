param(
    [Parameter(Mandatory = $true)]
    [string]$InputVideo,

    [string]$WhamRepoPath = "C:\Users\gabri\Downloads\WHAM",
    [string]$OutputRoot = "build/exercise_motion/wham-runtime-compare",
    [string]$LocalPython = "python",
    [string]$DockerImage = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$DockerGpus = "all",
    [string]$DockerShmSize = "16g",
    [switch]$EstimateLocalOnly,
    [switch]$RunSmplify,
    [switch]$SkipDocker,
    [switch]$SkipLocal
)

$ErrorActionPreference = "Stop"

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Invoke-WhamRun {
    param(
        [string]$Mode,
        [string]$OutputDir,
        [switch]$UseDocker
    )

    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $argsList = @(
        "-WhamRepoPath", $resolvedWhamRepoPath,
        "-InputVideo", $resolvedInputVideo,
        "-OutputRoot", $OutputDir,
        "-PythonCommand", $LocalPython
    )
    if ($EstimateLocalOnly) {
        $argsList += "-EstimateLocalOnly"
    }
    if ($RunSmplify) {
        $argsList += "-RunSmplify"
    }
    if ($UseDocker) {
        $argsList += @(
            "-UseDocker",
            "-DockerImage", $DockerImage,
            "-DockerGpus", $DockerGpus,
            "-DockerShmSize", $DockerShmSize
        )
    }

    $runner = Join-Path $PSScriptRoot "run_wham_local.ps1"
    $elapsed = Measure-Command {
        & pwsh $runner @argsList
        if ($LASTEXITCODE -ne 0) {
            throw "WHAM $Mode run failed with exit code $LASTEXITCODE."
        }
    }
    $sequenceDir = Join-Path $OutputDir ([System.IO.Path]::GetFileNameWithoutExtension($resolvedInputVideo))
    $pklPath = Join-Path $sequenceDir "wham_output.pkl"
    [PSCustomObject]@{
        mode = $Mode
        elapsedSeconds = [math]::Round($elapsed.TotalSeconds, 3)
        outputPkl = [System.IO.Path]::GetFullPath($pklPath)
        exists = Test-Path -LiteralPath $pklPath
    }
}

$resolvedInputVideo = Resolve-StrictPath $InputVideo
$resolvedWhamRepoPath = Resolve-StrictPath $WhamRepoPath
$resolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Force -Path $resolvedOutputRoot | Out-Null

$results = @()
if (-not $SkipDocker) {
    $results += Invoke-WhamRun `
        -Mode "docker" `
        -OutputDir (Join-Path $resolvedOutputRoot "docker") `
        -UseDocker
}
if (-not $SkipLocal) {
    $results += Invoke-WhamRun `
        -Mode "local" `
        -OutputDir (Join-Path $resolvedOutputRoot "local")
}

$results | ConvertTo-Json -Depth 3
