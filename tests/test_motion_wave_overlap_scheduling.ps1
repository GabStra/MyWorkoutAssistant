$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
# Dot-source at script scope (a foreach loop does not open a new scope), the
# same extraction pattern as test_motion_wave_run_isolation.ps1.
foreach ($functionName in @('Get-FlaggedJobCount', 'Get-StagedWaveCheckpointStage', 'Test-StagedWaveOverlapAdmission', 'Start-StagedResultCompletionJob')) {
    $node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $functionName }, $true)
    if ($null -eq $node) { throw "Function $functionName not found in runner" }
    . ([scriptblock]::Create($node.Extent.Text))
}
# The runner initializes this script-scoped cache at file scope; mirror it.
$script:StagedWaveCheckpointStageCacheByPath = @{}

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('motion-wave-overlap-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null

function New-FakeStagedWaveJob {
    param([string]$WaveWorkspace, [int]$Id)
    return [pscustomobject]@{ Id = $Id; IsStagedWave = $true; WaveWorkspace = $WaveWorkspace }
}

function New-FakeLegacyBakeJob {
    param([int]$Id)
    return [pscustomobject]@{ Id = $Id; WorkItem = 'legacy' }
}

function New-WaveWorkspace {
    # $Stage = $null leaves no checkpoint (a wave that just started).
    param([string]$Stage, [datetime]$LastWriteTimeUtc = [datetime]::UtcNow)
    $workspace = Join-Path $testRoot ('wave-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $workspace | Out-Null
    if ($null -ne $Stage) {
        $checkpointPath = Join-Path $workspace 'staged_wave_checkpoint.json'
        @{ stage = $Stage; items = @() } | ConvertTo-Json | Set-Content -LiteralPath $checkpointPath
        (Get-Item -LiteralPath $checkpointPath).LastWriteTimeUtc = $LastWriteTimeUtc
    }
    return $workspace
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

# --- Get-StagedWaveCheckpointStage ---
$plainJob = [pscustomobject]@{ Id = 1 }
Assert-True ((Get-StagedWaveCheckpointStage -Job $plainJob) -eq $null) 'Non-wave job must return null stage'
$missingCheckpointJob = New-FakeStagedWaveJob -WaveWorkspace (New-WaveWorkspace -Stage $null) -Id 2
Assert-True ((Get-StagedWaveCheckpointStage -Job $missingCheckpointJob) -eq '') 'Missing checkpoint must read as an early (empty) stage'
foreach ($stage in @('source_validation', 'wham_generation', 'wham_released', 'final_validation', 'completed')) {
    $stageJob = New-FakeStagedWaveJob -WaveWorkspace (New-WaveWorkspace -Stage $stage) -Id 3
    Assert-True ((Get-StagedWaveCheckpointStage -Job $stageJob) -eq $stage) "Stage $stage must round-trip"
}
$corruptWorkspace = New-WaveWorkspace -Stage 'final_validation'
Set-Content -LiteralPath (Join-Path $corruptWorkspace 'staged_wave_checkpoint.json') -Value 'not json{{{'
$corruptJob = New-FakeStagedWaveJob -WaveWorkspace $corruptWorkspace -Id 4
Assert-True ((Get-StagedWaveCheckpointStage -Job $corruptJob) -eq '') 'Unparseable checkpoint must read as an early (empty) stage'

# mtime cache: same LastWriteTimeUtc returns the cached stage even if the
# file content changed; a bumped mtime forces a fresh read.
$t1 = [datetime]::UtcNow
$t2 = $t1.AddSeconds(2)
$cachedWorkspace = New-WaveWorkspace -Stage 'source_validation' -LastWriteTimeUtc $t1
$cachedJob = New-FakeStagedWaveJob -WaveWorkspace $cachedWorkspace -Id 5
$cachedPath = Join-Path $cachedWorkspace 'staged_wave_checkpoint.json'
Assert-True ((Get-StagedWaveCheckpointStage -Job $cachedJob) -eq 'source_validation') 'Cache seed read failed'
@{ stage = 'final_validation'; items = @() } | ConvertTo-Json | Set-Content -LiteralPath $cachedPath
(Get-Item -LiteralPath $cachedPath).LastWriteTimeUtc = $t1
Assert-True ((Get-StagedWaveCheckpointStage -Job $cachedJob) -eq 'source_validation') 'Unchanged mtime must serve the cached stage'
(Get-Item -LiteralPath $cachedPath).LastWriteTimeUtc = $t2
Assert-True ((Get-StagedWaveCheckpointStage -Job $cachedJob) -eq 'final_validation') 'Bumped mtime must force a fresh read'

# --- Test-StagedWaveOverlapAdmission ---
$idle = Test-StagedWaveOverlapAdmission -BakeRunningJobs @() -PendingLegacyBakeItemCount 0 -MaxConcurrentStagedWaves 1
Assert-True ($idle.admitted -and $idle.runningStagedWaveCount -eq 0) 'Idle pipeline must admit a wave'

function New-WaveJobAtStage {
    param([string]$Stage, [int]$Id)
    return New-FakeStagedWaveJob -WaveWorkspace (New-WaveWorkspace -Stage $Stage) -Id $Id
}
function Test-Admission {
    param([object[]]$Jobs, [int]$Max, [int]$LegacyPending = 0)
    return Test-StagedWaveOverlapAdmission -BakeRunningJobs $Jobs -PendingLegacyBakeItemCount $LegacyPending -MaxConcurrentStagedWaves $Max
}

# MaxConcurrentStagedWaves = 1 always blocks once any wave is running, even
# in final_validation: exactly the serialized behavior of the old gate.
$serialized = Test-Admission -Jobs @(New-WaveJobAtStage -Stage 'final_validation' -Id 10) -Max 1
Assert-True (-not $serialized.admitted -and $serialized.runningStagedWaveCount -eq 1) 'Cap 1 must keep waves serialized'

# Overlap: a single wave in final_validation admits the next one at cap 2.
$overlap = Test-Admission -Jobs @(New-WaveJobAtStage -Stage 'final_validation' -Id 11) -Max 2
Assert-True ($overlap.admitted) 'final_validation wave must admit the next wave at cap 2'

# Early and GPU phases block: no checkpoint yet, source_validation,
# wham_generation, and the wham_released transition all hold the gate.
foreach ($blockingStage in @($null, 'source_validation', 'wham_generation', 'wham_released')) {
    $blocked = Test-Admission -Jobs @(New-WaveJobAtStage -Stage $blockingStage -Id 12) -Max 2
    Assert-True (-not $blocked.admitted) "Stage $blockingStage must block the next wave"
}

# Two waves at cap 2: full; at cap 3 only if BOTH are in final_validation.
$twoFinal = @(New-WaveJobAtStage -Stage 'final_validation' -Id 13; New-WaveJobAtStage -Stage 'final_validation' -Id 14)
Assert-True (-not (Test-Admission -Jobs $twoFinal -Max 2).admitted) 'Wave count at the cap must block'
Assert-True ((Test-Admission -Jobs $twoFinal -Max 3).admitted) 'Two final_validation waves must admit a third at cap 3'
$oneEarly = @(New-WaveJobAtStage -Stage 'final_validation' -Id 15; New-WaveJobAtStage -Stage 'wham_generation' -Id 16)
Assert-True (-not (Test-Admission -Jobs $oneEarly -Max 3).admitted) 'Any non-final-validation wave must block even below the cap'

# Legacy fallbacks are full GPU-capable pipelines: pending or running, they
# keep the bake lane exclusive.
Assert-True (-not (Test-Admission -Jobs @() -Max 2 -LegacyPending 1).admitted) 'Pending legacy bake item must block'
$legacyRunning = Test-Admission -Jobs @((New-WaveJobAtStage -Stage 'final_validation' -Id 17); (New-FakeLegacyBakeJob -Id 18)) -Max 2
Assert-True (-not $legacyRunning.admitted) 'Running legacy bake job must block'

# Completion jobs are trivial and must never block the next wave.
function Start-Job {
    param($Name, $ScriptBlock, $ArgumentList)
    [pscustomobject]@{ Name = $Name; Worker = $ScriptBlock; Arguments = $ArgumentList }
}
$completionWorkItem = [pscustomobject]@{ exerciseSlug = 'curl' }
$completionJob = Start-StagedResultCompletionJob -WorkItem $completionWorkItem
Assert-True ($completionJob.IsStagedCompletion) 'Completion jobs must be marked IsStagedCompletion'
$besideCompletions = Test-Admission -Jobs @((New-WaveJobAtStage -Stage 'final_validation' -Id 19); $completionJob; $completionJob) -Max 2
Assert-True ($besideCompletions.admitted) 'Completion jobs must not block the next wave'

# --- Completion admission beside a wave (own bounded lane) ---
Assert-True ((Get-FlaggedJobCount -Jobs @() -FlagPropertyName 'IsStagedCompletion') -eq 0) 'Flagged count of an empty lane must be 0'
$laneJobs = @((New-WaveJobAtStage -Stage 'final_validation' -Id 20); $completionJob)
Assert-True ((Get-FlaggedJobCount -Jobs $laneJobs -FlagPropertyName 'IsStagedWave') -eq 1) 'Flagged count must isolate the wave marker'
Assert-True ((Get-FlaggedJobCount -Jobs $laneJobs -FlagPropertyName 'IsStagedCompletion') -eq 1) 'Flagged count must isolate the completion marker'
# Old gate: pending completion admitted only while $bakeRunningJobs.Count -lt
# $resolvedBakeWorkers, so a running wave starved the completion lane.
$resolvedBakeWorkers = 2
$oldGateWouldAdmit = $laneJobs.Count -lt $resolvedBakeWorkers
$runningCompletionJobCount = Get-FlaggedJobCount -Jobs $laneJobs -FlagPropertyName 'IsStagedCompletion'
$newGateWouldAdmit = $runningCompletionJobCount -lt $resolvedBakeWorkers
Assert-True (-not $oldGateWouldAdmit) 'Test premise failed: old gate would not starve here'
Assert-True ($newGateWouldAdmit) 'Completion lane must admit beside a running wave'
# The lane is still bounded: at capacity it stops spawning.
$fullLaneJobs = @($laneJobs[0]; $completionJob; $completionJob)
$atCapacity = (Get-FlaggedJobCount -Jobs $fullLaneJobs -FlagPropertyName 'IsStagedCompletion') -lt $resolvedBakeWorkers
Assert-True (-not $atCapacity) 'Completion lane must stay bounded by its own cap'

# Remove only the explicitly created synthetic tree.
Remove-Item -LiteralPath $testRoot -Recurse -Force
Write-Host 'Wave overlap scheduling tests passed.'
