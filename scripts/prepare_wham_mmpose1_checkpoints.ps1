param(
    [string]$WhamRepoPath = (Join-Path $PSScriptRoot "..\third_party\WHAM")
)

$ErrorActionPreference = "Stop"

$resolvedWhamRepoPath = (Resolve-Path -LiteralPath $WhamRepoPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $resolvedWhamRepoPath "demo.py"))) {
    throw "WHAM repo path does not look valid: $resolvedWhamRepoPath"
}

$checkpointDir = Join-Path $resolvedWhamRepoPath "checkpoints"
New-Item -ItemType Directory -Force -Path $checkpointDir | Out-Null

$vitposeName = "td-hm_ViTPose-huge_8xb64-210e_coco-256x192-e32adcd4_20230314.pth"
$vitposePath = Join-Path $checkpointDir $vitposeName
$vitposeUrl = "https://download.openmmlab.com/mmpose/v1/body_2d_keypoint/topdown_heatmap/coco/$vitposeName"

if (-not (Test-Path -LiteralPath $vitposePath)) {
    Write-Host "Downloading ViTPose-Huge checkpoint to $vitposePath"
    Invoke-WebRequest -Uri $vitposeUrl -OutFile $vitposePath
} else {
    Write-Host "ViTPose-Huge checkpoint already exists: $vitposePath"
}

$yoloPath = Join-Path $checkpointDir "yolo26x.pt"
if (-not (Test-Path -LiteralPath $yoloPath)) {
    Write-Host "Downloading YOLO26x checkpoint to $yoloPath"
    Invoke-WebRequest -Uri "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26x.pt" -OutFile $yoloPath
} else {
    Write-Host "YOLO26x checkpoint already exists: $yoloPath"
}

$bedlamName = "wham_vit_bedlam_w_3dpw.pth.tar"
$bedlamPath = Join-Path $checkpointDir $bedlamName
if (-not (Test-Path -LiteralPath $bedlamPath)) {
    Write-Host "Downloading WHAM demo checkpoint to $bedlamPath"
    python -m pip install --quiet gdown
    python -m gdown "https://drive.google.com/uc?id=19qkI-a6xuwob9_RFNSPWf1yWErwVVlks" -O $bedlamPath
} else {
    Write-Host "WHAM demo checkpoint already exists: $bedlamPath"
}
