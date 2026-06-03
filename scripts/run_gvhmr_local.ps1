param(
    [Parameter(Mandatory = $true)]
    [string]$GvhmrRepoPath,

    [Parameter(Mandatory = $true)]
    [string]$InputVideo,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$PythonCommand = "python",
    [switch]$UseWsl,
    [string]$WslDistro = "Ubuntu",
    [string]$WslCondaRoot = "/home/gabriele/miniforge3",
    [string]$WslEnvName = "gvhmr",

    [switch]$StaticCamera
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

function Convert-WindowsPathToWslPath {
    param([string]$PathValue)

    $fullPath = [System.IO.Path]::GetFullPath($PathValue)
    $normalized = $fullPath -replace '\\', '/'
    if ($normalized -match '^([A-Za-z]):/(.*)$') {
        $drive = $matches[1].ToLowerInvariant()
        $rest = $matches[2]
        return "/mnt/$drive/$rest"
    }
    throw "Cannot convert Windows path to WSL path: $PathValue"
}

Assert-PathExists $GvhmrRepoPath
Assert-PathExists $InputVideo

$resolvedRepo = Resolve-StrictPath $GvhmrRepoPath
$resolvedInputVideo = Resolve-StrictPath $InputVideo
$resolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Force -Path $resolvedOutputRoot | Out-Null

$requiredPaths = @(
    (Join-Path $resolvedRepo "tools\demo\demo.py"),
    (Join-Path $resolvedRepo "requirements.txt"),
    (Join-Path $resolvedRepo "inputs\checkpoints\gvhmr\gvhmr_siga24_release.ckpt"),
    (Join-Path $resolvedRepo "inputs\checkpoints\hmr2\epoch=10-step=25000.ckpt"),
    (Join-Path $resolvedRepo "inputs\checkpoints\vitpose\vitpose-h-multi-coco.pth"),
    (Join-Path $resolvedRepo "inputs\checkpoints\yolo\yolov8x.pt"),
    (Join-Path $resolvedRepo "inputs\checkpoints\body_models\smpl\SMPL_NEUTRAL.pkl"),
    (Join-Path $resolvedRepo "inputs\checkpoints\body_models\smplx\SMPLX_NEUTRAL.npz")
)

$missing = $requiredPaths | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing.Count -gt 0) {
    throw "GVHMR repo is missing required files:`n$($missing -join "`n")"
}

if ($UseWsl) {
    $repoWsl = Convert-WindowsPathToWslPath $resolvedRepo
    $inputWsl = Convert-WindowsPathToWslPath $resolvedInputVideo
    $outputWsl = Convert-WindowsPathToWslPath $resolvedOutputRoot
    $staticArg = if ($StaticCamera) { " -s" } else { "" }
    $bashScript = @"
source "$WslCondaRoot/etc/profile.d/conda.sh"
conda activate "$WslEnvName"
cd "$repoWsl"
python tools/demo/demo.py --video="$inputWsl" --output_root "$outputWsl"$staticArg
"@
    & wsl -d $WslDistro bash -lc $bashScript
    if ($LASTEXITCODE -ne 0) {
        throw "GVHMR WSL run failed with exit code $LASTEXITCODE."
    }
}
else {
    $argsList = @(
        "tools/demo/demo.py",
        "--video=$resolvedInputVideo",
        "--output_root",
        $resolvedOutputRoot
    )
    if ($StaticCamera) {
        $argsList += "-s"
    }

    Push-Location $resolvedRepo
    try {
        & $PythonCommand @argsList
        if ($LASTEXITCODE -ne 0) {
            throw "GVHMR run failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
