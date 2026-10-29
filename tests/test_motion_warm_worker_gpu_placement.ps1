$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root 'scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$functionAsts = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Start-GvhmrWarmWorkerSingle', 'Start-GvhmrWarmWorker', 'Stop-GvhmrWarmWorker')
}, $true))
if ($functionAsts.Count -ne 3) { throw 'Missing GVHMR warm-worker start/stop functions.' }
foreach ($functionAst in $functionAsts) {
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:CapturedDockerArguments = @()
$script:CapturedDockerArgumentSets = @()
function Acquire-MotionServiceSessionLease { return 'test-lease' }
function Set-MotionServiceSessionRuntimeOwner {}
function Set-MotionServiceSessionState {}
function Release-MotionServiceSessionLease { return 'stopped' }
function Test-MotionRunCancelRequested { return $false }
function nvidia-smi {
    $global:LASTEXITCODE = 0
    return @('0, GPU-LLAMA', '1, GPU-RECON')
}
function docker {
    $script:CapturedDockerArguments = @($args)
    $script:CapturedDockerArgumentSets += ,@($args)
    $script:WorkerStarted = $true
    $global:LASTEXITCODE = 0
    return 'container-id'
}
function Test-Path {
    param([string]$LiteralPath)
    if ($LiteralPath -like '*ready.json' -and $script:WorkerStarted) { return $true }
    return Microsoft.PowerShell.Management\Test-Path -LiteralPath $LiteralPath
}
function Get-Content {
    param([string]$LiteralPath, [switch]$Raw)
    if ($LiteralPath -like '*ready.json') { return '{"loadSeconds":1,"gpuName":"RTX"}' }
    return Microsoft.PowerShell.Management\Get-Content -LiteralPath $LiteralPath -Raw:$Raw
}
function Remove-Item {
    param([string]$LiteralPath, [switch]$Force, [string]$ErrorAction = 'SilentlyContinue')
    if ($LiteralPath -like '*ready.json' -or $LiteralPath -like '*heartbeat.json') { return }
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Force:$Force -ErrorAction $ErrorAction
}

$workspace = Join-Path ([System.IO.Path]::GetTempPath()) ("warm-worker-gpu-" + [guid]::NewGuid().ToString('N'))
$SessionDir = Join-Path $workspace 'session'
$MountRoot = $workspace
$WorkerScriptPath = Join-Path $root 'exercise_motion_pkg/gvhmr_warm_worker.py'
$GvhmrWorkerStartupTimeoutSeconds = 10
$ReconstructionDockerImage = 'mwa-test/gvhmr'
$ReconstructionDockerGpus = 'all'
$env:EXERCISE_MOTION_EXCLUSIVE_GPU_DEVICE = '1'
$verifiedExclusiveGpuSplit = $true
$script:WorkerStarted = $false
$null = Start-GvhmrWarmWorker -SessionDir $SessionDir -MountRoot $MountRoot -WorkerScriptPath $WorkerScriptPath
$gpuArgumentIndex = [Array]::IndexOf($script:CapturedDockerArguments, '--gpus')
if ($gpuArgumentIndex -lt 0 -or $script:CapturedDockerArguments[$gpuArgumentIndex + 1] -ne 'device=GPU-RECON') {
    throw 'Warm worker split placement must grant only the verified reconstruction GPU UUID.'
}
$cudaEnvironmentIndex = [Array]::IndexOf($script:CapturedDockerArguments, 'CUDA_VISIBLE_DEVICES=GPU-RECON')
if ($cudaEnvironmentIndex -lt 0) {
    throw 'Warm worker split placement must restrict CUDA ordinal 0 to the selected physical GPU.'
}

$script:CapturedDockerArgumentSets = @()
$script:WorkerStarted = $false
$SessionDir = Join-Path $workspace 'stage-split-session'
$splitWorker = Start-GvhmrWarmWorker -SessionDir $SessionDir -MountRoot $MountRoot -WorkerScriptPath $WorkerScriptPath -StageSplit
if (@($splitWorker.workers).Count -ne 2) { throw 'Stage split must supervise both GVHMR roles as one worker group.' }
$preprocessArgs = $script:CapturedDockerArgumentSets | Where-Object { $_ -contains 'preprocess' }
$predictionArgs = $script:CapturedDockerArgumentSets | Where-Object { $_ -contains 'predict' }
if (-not $preprocessArgs -or -not $predictionArgs) { throw 'Stage split must start both preprocess and prediction worker roles.' }
if (
    $preprocessArgs[[Array]::IndexOf($preprocessArgs, '--gpu-device') + 1] -ne '1' -or
    $predictionArgs[[Array]::IndexOf($predictionArgs, '--gpu-device') + 1] -ne '0'
) {
    throw 'Stage split must place preprocessing on physical GPU 1 and prediction on physical GPU 0.'
}
if (
    [Array]::IndexOf($preprocessArgs, 'GVHMR_IMAGE_IDENTITY=container-id') -lt 0 -or
    [Array]::IndexOf($predictionArgs, 'GVHMR_IMAGE_IDENTITY=container-id') -lt 0
) {
    throw 'Both GVHMR roles must receive the immutable Docker image identity they were started from.'
}
Stop-GvhmrWarmWorker -Worker $splitWorker

$ReconstructionDockerGpus = 'all'
$verifiedExclusiveGpuSplit = $false
$env:EXERCISE_MOTION_EXCLUSIVE_GPU_DEVICE = ''
$script:WorkerStarted = $false
$SessionDir = Join-Path $workspace 'legacy-session'
$null = Start-GvhmrWarmWorker -SessionDir $SessionDir -MountRoot $MountRoot -WorkerScriptPath $WorkerScriptPath
$gpuArgumentIndex = [Array]::IndexOf($script:CapturedDockerArguments, '--gpus')
if ($gpuArgumentIndex -lt 0 -or $script:CapturedDockerArguments[$gpuArgumentIndex + 1] -ne 'all') {
    throw 'Legacy single-lane warm worker GPU selection must remain unchanged.'
}
Write-Host 'Warm GVHMR GPU placement checks passed.'
