param(
    [string]$WhamRepoPath = (Join-Path $PSScriptRoot "..\third_party\WHAM"),
    [string]$ImageTag = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$BaseImage = "pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel",
    [switch]$NoCache
)

$ErrorActionPreference = "Stop"

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$dockerfile = Join-Path $repoRoot "docker\wham-ada\Dockerfile"
$resolvedWhamRepoPath = Resolve-StrictPath $WhamRepoPath
$patchScript = Join-Path $repoRoot "scripts\apply_wham_mmpose1_patch.ps1"

if (-not (Test-Path -LiteralPath (Join-Path $resolvedWhamRepoPath "demo.py"))) {
    throw "WHAM repo path does not look valid: $resolvedWhamRepoPath"
}

if (-not (Test-Path -LiteralPath $patchScript)) {
    throw "Missing WHAM patch script: $patchScript"
}

& pwsh $patchScript -WhamRepoPath $resolvedWhamRepoPath
if ($LASTEXITCODE -ne 0) {
    throw "Applying WHAM MMPose 1.x patch failed with exit code $LASTEXITCODE."
}

$dockerignore = Join-Path $resolvedWhamRepoPath ".dockerignore"
@(
    ".git",
    ".venv-fetch",
    "__pycache__",
    "**/__pycache__",
    "output",
    "examples",
    "*.mp4",
    "*.mov"
) | Set-Content -LiteralPath $dockerignore -Encoding UTF8
Write-Host "Wrote WHAM build .dockerignore (checkpoints and body models are included in the image): $dockerignore"

$requiredImageAssets = @(
    (Join-Path $resolvedWhamRepoPath "checkpoints\wham_vit_bedlam_w_3dpw.pth.tar"),
    (Join-Path $resolvedWhamRepoPath "checkpoints\wham_vit_w_3dpw.pth.tar"),
    (Join-Path $resolvedWhamRepoPath "checkpoints\hmr2a.ckpt"),
    (Join-Path $resolvedWhamRepoPath "dataset\body_models\smpl\SMPL_NEUTRAL.pkl")
)
$missingImageAssets = $requiredImageAssets | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missingImageAssets.Count -gt 0) {
    throw "Cannot build a self-contained WHAM image; missing:`n$($missingImageAssets -join "`n")"
}

$argsList = @(
    "build",
    "-f", $dockerfile,
    "--build-arg", "BASE_IMAGE=$BaseImage",
    "-t", $ImageTag
)
if ($NoCache) {
    $argsList += "--no-cache"
}
$argsList += $resolvedWhamRepoPath

Write-Host "Building WHAM Ada image '$ImageTag' from '$resolvedWhamRepoPath'."
Write-Host "Base image: $BaseImage"
& docker @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Docker build failed with exit code $LASTEXITCODE."
}

Write-Host "Built image: $ImageTag"
