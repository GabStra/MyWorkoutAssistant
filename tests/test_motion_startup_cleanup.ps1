$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$outerTry = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.TryStatementAst] -and
    $null -ne $node.Finally -and $node.Finally.Extent.Text.Contains('Release-MotionWorkspaceLease -Lease $script:MotionWorkspaceLease')
}, $false)
if ($null -eq $outerTry) { throw 'Outer cleanup not found' }
$cleanup = [scriptblock]::Create($outerTry.Finally.Extent.Text.Trim().Substring(1).TrimEnd().TrimEnd('}'))
function Test-MotionRunCancelRequested { return $script:cancelled }
function Stop-StagedBakeQueueService { param([switch]$Cancel); $script:calls.Add('worker'); return $script:workerStopped }
function Stop-MotionModelServicesAfterStagedWorker {
    param($StagedWaveShutdownConfirmed, $WarmGvhmrWorker, $SharedLlamaServer)
    if (-not $StagedWaveShutdownConfirmed -or $SharedLlamaServer -ne 'startup-server') { throw 'Wrong startup service ownership' }
    $script:calls.Add('models')
}
function Release-MotionServiceSessionLease {
    param($SessionDirectory)
    $script:calls.Add('session')
    if ($script:workerStopped) { return 'stopped' }
    return 'running'
}
function Release-MotionWorkspaceLease { param($Lease); $script:calls.Add('workspace') }
foreach ($case in @(
    @{ cancelled = $true; workerStopped = $true },
    @{ cancelled = $false; workerStopped = $true },
    @{ cancelled = $true; workerStopped = $false }
)) {
    $script:cancelled = $case.cancelled
    $script:workerStopped = $case.workerStopped
    $script:calls = [System.Collections.Generic.List[string]]::new()
    $script:MotionServiceShutdownUnconfirmed = $false
    $script:MotionServiceSessionLeases = @{ owned = $true }
    $script:MotionWorkspaceLease = 'owned-workspace'
    $sharedLlamaServerInstance = 'startup-server'
    $warmGvhmrWorkerInstance = $null
    # Reproduce an exit during startup, before the scheduler's inner try is entered.
    try { throw 'Startup interrupted' } catch {} finally { . $cleanup }
    $expected = if ($case.workerStopped) { 'worker,models,session,workspace' } else { 'worker,session,workspace' }
    if (($script:calls -join ',') -ne $expected) { throw "Wrong cleanup order: $($script:calls -join ',')" }
    if ($script:MotionServiceShutdownUnconfirmed -ne (-not $case.workerStopped)) { throw 'Unconfirmed worker ownership was lost' }
}
$startupLoops = $outerTry.Body.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.ForEachStatementAst] -and
    ($node.Extent.Text.StartsWith('foreach ($exercise in $exerciseList.exercises)') -or
     $node.Extent.Text.Contains('$indexKey = [string]$workItem.index'))
}, $false)
foreach ($loop in $startupLoops) {
    if (-not $loop.Body.Extent.Text.Contains('Exit-IfMotionRunInterrupted')) { throw 'Startup scan ignores cancellation' }
}
if ($startupLoops.Count -lt 3) { throw 'Startup cancellation scans were not found' }
Write-Host 'Startup cancellation cleanup checks passed.'
