param(
    [string]$WhamRepoPath = "C:\Users\gabri\Downloads\WHAM"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$patchRoot = Join-Path $repoRoot "third_party_patches\wham_mmpose1"
$resolvedWhamRepoPath = (Resolve-Path -LiteralPath $WhamRepoPath).Path

if (-not (Test-Path -LiteralPath (Join-Path $resolvedWhamRepoPath "demo.py"))) {
    throw "WHAM repo path does not look valid: $resolvedWhamRepoPath"
}

$detectorSource = Join-Path $patchRoot "detector.py"
$detectorTarget = Join-Path $resolvedWhamRepoPath "lib\models\preproc\detector.py"
$extractorSource = Join-Path $patchRoot "extractor.py"
$extractorTarget = Join-Path $resolvedWhamRepoPath "lib\models\preproc\extractor.py"
$siteCustomizeSource = Join-Path $patchRoot "sitecustomize.py"
$siteCustomizeTarget = Join-Path $resolvedWhamRepoPath "sitecustomize.py"
$configSource = Join-Path $patchRoot "configs\VIT"
$configTarget = Join-Path $resolvedWhamRepoPath "configs\VIT"

function Update-TextInFile {
    param(
        [string]$PathValue,
        [string]$Find,
        [string]$Replace
    )

    if (-not (Test-Path -LiteralPath $PathValue)) {
        throw "Cannot patch missing file: $PathValue"
    }

    $content = Get-Content -LiteralPath $PathValue -Raw
    if ($content.Contains($Find)) {
        $content.Replace($Find, $Replace) | Set-Content -LiteralPath $PathValue -Encoding UTF8
    }
}

if (-not (Test-Path -LiteralPath $detectorSource)) {
    throw "Missing detector patch: $detectorSource"
}
if (-not (Test-Path -LiteralPath $extractorSource)) {
    throw "Missing feature extractor patch: $extractorSource"
}
if (-not (Test-Path -LiteralPath $configSource)) {
    throw "Missing VIT config patch directory: $configSource"
}
if (-not (Test-Path -LiteralPath $siteCustomizeSource)) {
    throw "Missing sitecustomize patch: $siteCustomizeSource"
}

$backupRoot = Join-Path $resolvedWhamRepoPath ".codex_backup\mmpose1"
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
if (Test-Path -LiteralPath $detectorTarget) {
    $backupDetector = Join-Path $backupRoot ("detector.py." + (Get-Date -Format "yyyyMMdd-HHmmss"))
    Copy-Item -LiteralPath $detectorTarget -Destination $backupDetector
    Write-Host "Backed up detector.py to $backupDetector"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $detectorTarget) | Out-Null
New-Item -ItemType Directory -Force -Path $configTarget | Out-Null
Copy-Item -LiteralPath $detectorSource -Destination $detectorTarget -Force
Copy-Item -LiteralPath $extractorSource -Destination $extractorTarget -Force
Copy-Item -LiteralPath $siteCustomizeSource -Destination $siteCustomizeTarget -Force
Copy-Item -Path (Join-Path $configSource "*") -Destination $configTarget -Force

$dpvoRoot = Join-Path $resolvedWhamRepoPath "third-party\DPVO\dpvo"
$altcorr = Join-Path $dpvoRoot "altcorr\correlation_kernel.cu"
$lietorchGpu = Join-Path $dpvoRoot "lietorch\src\lietorch_gpu.cu"
$lietorchCpu = Join-Path $dpvoRoot "lietorch\src\lietorch_cpu.cpp"
$fastBaCuda = Join-Path $dpvoRoot "fastba\ba_cuda.cu"
$dpvoModel = Join-Path $dpvoRoot "dpvo.py"
$whamModelsInit = Join-Path $resolvedWhamRepoPath "lib\models\__init__.py"
$whamAugmentor = Join-Path $resolvedWhamRepoPath "lib\data\utils\augmentor.py"
$whamHmr2 = Join-Path $resolvedWhamRepoPath "lib\models\preproc\backbone\hmr2.py"

Update-TextInFile -PathValue $altcorr -Find "fmap1.type()" -Replace "fmap1.scalar_type()"
Update-TextInFile -PathValue $altcorr -Find "net.type()" -Replace "net.scalar_type()"
Update-TextInFile -PathValue $lietorchGpu -Find '.type(), "' -Replace '.scalar_type(), "'
Update-TextInFile -PathValue $lietorchCpu -Find '.type(), "' -Replace '.scalar_type(), "'
Update-TextInFile -PathValue $fastBaCuda -Find "torch::linalg::cholesky(S)" -Replace "at::linalg_cholesky(S)"
Update-TextInFile -PathValue $dpvoModel -Find "state_dict = torch.load(network)" -Replace "state_dict = torch.load(network, weights_only=False)"
Update-TextInFile -PathValue $whamModelsInit -Find "checkpoint = torch.load(cfg.TRAIN.CHECKPOINT)" -Replace "checkpoint = torch.load(cfg.TRAIN.CHECKPOINT, weights_only=False)"
Update-TextInFile -PathValue $whamAugmentor -Find "self.aug_dict = torch.load(_C.KEYPOINTS.COCO_AUG_DICT)" -Replace "self.aug_dict = torch.load(_C.KEYPOINTS.COCO_AUG_DICT, weights_only=False)"
Update-TextInFile -PathValue $whamHmr2 -Find "torch.load(checkpoint_pth, map_location='cpu')" -Replace "torch.load(checkpoint_pth, map_location='cpu', weights_only=False)"

Write-Host "Applied WHAM MMPose 1.x detector patch to $resolvedWhamRepoPath"
Write-Host "Detector: $detectorTarget"
Write-Host "Batched feature extractor: $extractorTarget"
Write-Host "Torch checkpoint compatibility: $siteCustomizeTarget"
Write-Host "ViTPose config directory: $configTarget"
Write-Host "Applied DPVO PyTorch 2.9 extension patches."
