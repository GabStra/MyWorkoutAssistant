param(
    [Parameter(Mandatory = $true)]
    [string]$CandidatesJson,

    [string]$Workspace = "build/exercise_motion",
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [double]$MaxLoopSeconds = 10.0,
    [string]$WhamPython = "python",
    [switch]$UseWhamDocker,
    [string]$WhamDockerImage = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "8g",
    [switch]$EstimateLocalOnly,
    [switch]$RunSmplify,
    [ValidateSet("world", "camera")]
    [string]$WhamCoordinateSpace = "camera",
    [string]$LiteRtCommand,
    [ValidateSet("cpu", "gpu", "npu")]
    [string]$LiteRtBackend = "gpu",
    [string]$VisionModel = "gemma-4-E4B-it",
    [switch]$NoLiteRtServer,
    [string]$LiteRtServerUrl = "http://127.0.0.1:9379",
    [int]$LiteRtServerPort = 9379,
    [switch]$KeepLiteRtServer,
    [int]$ReviewFrames = 12,
    [double]$MinSelectedScore = 0.55,
    [switch]$SkipSourceSegmentDetection,
    [string]$SegmentBaseUrl,
    [string]$SegmentModel,
    [double]$SegmentWindowSeconds = 5.0,
    [double]$SegmentOverlapSeconds = 2.5,
    [int]$SegmentFramesPerWindow = 20,
    [double]$SegmentConfidenceThreshold = 0.45,
    [double]$SegmentPaddingSeconds = 0.35,
    [double]$SegmentEndPaddingSeconds = 0.35,
    [double]$SegmentMinSeconds = 2.0,
    [double]$SegmentMaxSeconds = 20.0
)

$ErrorActionPreference = "Stop"

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Get-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Get-PythonCommand {
    $venvPython = Join-Path (Get-RepoRoot) ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }
    return "python"
}

$repoRoot = Get-RepoRoot
$pythonCommand = Get-PythonCommand
$resolvedCandidatesJson = Resolve-StrictPath $CandidatesJson

$defaultWhamRepoPath = "C:\Users\gabri\Downloads\WHAM"
if (-not (Test-Path -LiteralPath $defaultWhamRepoPath)) {
    $defaultWhamRepoPath = Join-Path $repoRoot "third_party\WHAM"
}
if ([string]::IsNullOrWhiteSpace($WhamRepoPath)) {
    $WhamRepoPath = $defaultWhamRepoPath
}
if ([string]::IsNullOrWhiteSpace($BodyModelRoot)) {
    $BodyModelRoot = Join-Path $WhamRepoPath "dataset\body_models"
}

$resolvedWhamRepoPath = Resolve-StrictPath $WhamRepoPath
$resolvedBodyModelRoot = Resolve-StrictPath $BodyModelRoot

$argsList = @(
    "-m", "exercise_motion_pkg.cli",
    "bake-and-rank",
    "--candidates-json", $resolvedCandidatesJson,
    "--workspace", $Workspace,
    "--wham-repo-path", $resolvedWhamRepoPath,
    "--body-model-root", $resolvedBodyModelRoot,
    "--max-loop-seconds", "$MaxLoopSeconds",
    "--wham-python", $WhamPython,
    "--wham-coordinate-space", $WhamCoordinateSpace,
    "--litert-backend", $LiteRtBackend,
    "--vision-model", $VisionModel,
    "--litert-server-url", $LiteRtServerUrl,
    "--litert-server-port", "$LiteRtServerPort",
    "--review-frames", "$ReviewFrames",
    "--min-selected-score", "$MinSelectedScore",
    "--segment-window-seconds", "$SegmentWindowSeconds",
    "--segment-overlap-seconds", "$SegmentOverlapSeconds",
    "--segment-frames-per-window", "$SegmentFramesPerWindow",
    "--segment-confidence-threshold", "$SegmentConfidenceThreshold",
    "--segment-padding-seconds", "$SegmentPaddingSeconds",
    "--segment-end-padding-seconds", "$SegmentEndPaddingSeconds",
    "--segment-min-seconds", "$SegmentMinSeconds",
    "--segment-max-seconds", "$SegmentMaxSeconds"
)

if ($UseWhamDocker) {
    $argsList += @(
        "--use-wham-docker",
        "--wham-docker-image", $WhamDockerImage,
        "--wham-docker-gpus", $WhamDockerGpus,
        "--wham-docker-shm-size", $WhamDockerShmSize
    )
}
if ($EstimateLocalOnly) {
    $argsList += "--estimate-local-only"
}
if ($RunSmplify) {
    $argsList += "--run-smplify"
}
if (-not [string]::IsNullOrWhiteSpace($LiteRtCommand)) {
    $argsList += @("--litert-command", $LiteRtCommand)
}
if (-not [string]::IsNullOrWhiteSpace($SegmentBaseUrl)) {
    $argsList += @("--segment-base-url", $SegmentBaseUrl)
}
if (-not [string]::IsNullOrWhiteSpace($SegmentModel)) {
    $argsList += @("--segment-model", $SegmentModel)
}
if ($NoLiteRtServer) {
    $argsList += "--no-litert-server"
}
if ($KeepLiteRtServer) {
    $argsList += "--keep-litert-server"
}
if ($SkipSourceSegmentDetection) {
    $argsList += "--skip-source-segment-detection"
}

& $pythonCommand @argsList
if ($LASTEXITCODE -ne 0) {
    throw "exercise motion bake-and-rank failed with exit code $LASTEXITCODE."
}
