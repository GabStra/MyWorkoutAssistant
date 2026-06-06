param(
    [Parameter(Mandatory = $true)]
    [string]$WhamRepoPath,

    [Parameter(Mandatory = $true)]
    [string]$InputVideo,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$PythonCommand = "python",
    [switch]$EstimateLocalOnly,
    [switch]$RunSmplify,
    [switch]$UseDocker,
    [string]$DockerImage = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    [string]$DockerGpus = "all",
    [string]$DockerShmSize = "8g"
)

$ErrorActionPreference = "Stop"

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Assert-PathExists {
    param([string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue)) {
        throw "Required path not found: $PathValue"
    }
}

Assert-PathExists $WhamRepoPath
Assert-PathExists $InputVideo

$resolvedRepo = Resolve-StrictPath $WhamRepoPath
$resolvedInputVideo = Resolve-StrictPath $InputVideo
$resolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Force -Path $resolvedOutputRoot | Out-Null

$requiredPaths = @(
    (Join-Path $resolvedRepo "demo.py"),
    (Join-Path $resolvedRepo "requirements.txt"),
    (Join-Path $resolvedRepo "checkpoints\wham_vit_w_3dpw.pth.tar"),
    (Join-Path $resolvedRepo "checkpoints\hmr2a.ckpt"),
    (Join-Path $resolvedRepo "checkpoints\vitpose-h-multi-coco.pth"),
    (Join-Path $resolvedRepo "checkpoints\yolov8x.pt"),
    (Join-Path $resolvedRepo "dataset\body_models\smpl\SMPL_NEUTRAL.pkl")
)
if (-not $EstimateLocalOnly) {
    $requiredPaths += Join-Path $resolvedRepo "checkpoints\dpvo.pth"
}

$missing = $requiredPaths | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing.Count -gt 0) {
    throw "WHAM repo is missing required files:`n$($missing -join "`n")"
}

$argsList = @(
    "demo.py",
    "--video",
    $resolvedInputVideo,
    "--output_pth",
    $resolvedOutputRoot,
    "--save_pkl"
)
if ($EstimateLocalOnly) {
    $argsList += "--estimate_local_only"
}
if ($RunSmplify) {
    $argsList += "--run_smplify"
}

if ($UseDocker) {
    $inputDir = Split-Path -Parent $resolvedInputVideo
    $inputName = [System.IO.Path]::GetFileName($resolvedInputVideo)
    $dockerLog = Join-Path $resolvedOutputRoot "wham_docker.log"
    $dockerArgs = @(
        "run",
        "--rm"
    )
    if (-not [string]::IsNullOrWhiteSpace($DockerGpus)) {
        $dockerArgs += @("--gpus", $DockerGpus)
    }
    if (-not [string]::IsNullOrWhiteSpace($DockerShmSize)) {
        $dockerArgs += @("--shm-size", $DockerShmSize)
    }
    $dockerArgs += @(
        "-v", "${resolvedRepo}:/code",
        "-v", "${inputDir}:/input",
        "-v", "${resolvedOutputRoot}:/output",
        "-w", "/code",
        $DockerImage,
        "python",
        "-u",
        "demo.py",
        "--video",
        "/input/$inputName",
        "--output_pth",
        "/output",
        "--save_pkl"
    )
    if ($EstimateLocalOnly) {
        $dockerArgs += "--estimate_local_only"
    }
    if ($RunSmplify) {
        $dockerArgs += "--run_smplify"
    }
    & docker @dockerArgs 2>&1 | Tee-Object -FilePath $dockerLog
    $dockerExitCode = $LASTEXITCODE
    if ($dockerExitCode -ne 0) {
        throw "WHAM Docker run failed with exit code $dockerExitCode. See '$dockerLog'."
    }
    return
}

Push-Location $resolvedRepo
try {
    & $PythonCommand @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "WHAM run failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
