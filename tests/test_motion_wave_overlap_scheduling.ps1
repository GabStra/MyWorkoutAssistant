$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
# Dot-source at script scope (a foreach loop does not open a new scope), the
# same extraction pattern as test_motion_wave_run_isolation.ps1.
foreach ($functionName in @('Get-FlaggedJobCount', 'Get-StagedWaveCheckpointStage', 'Test-StagedWaveOverlapAdmission', 'Start-StagedResultCompletionJob', 'Receive-StagedWaveReadyItems', 'Test-SharedLlamaExclusiveHandoffActive')) {
    $node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $functionName }, $true)
    if ($null -eq $node) { throw "Function $functionName not found in runner" }
    . ([scriptblock]::Create($node.Extent.Text))
}
function Convert-ReconstructionMetadata { process { $_ } }
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

$overlapAssignment = $ast.Find({ param($n)
    $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $n.Left.Extent.Text -eq '$effectiveGpuDiscoveryBakeOverlap'
}, $true)
$discoveryUsesGpu = $true
$globalGpuLockEnabled = $true
$StagedWaveSize = 8
$MaxConcurrentStagedWaves = 2
$GpuDiscoveryBakeOverlap = 'auto'
$SharedLlamaServer = $true
. ([scriptblock]::Create($overlapAssignment.Extent.Text))
Assert-True ($effectiveGpuDiscoveryBakeOverlap -eq 'allow') 'Coordinated shared discovery must supply overlapping waves'
$SharedLlamaServer = $false
. ([scriptblock]::Create($overlapAssignment.Extent.Text))
Assert-True ($effectiveGpuDiscoveryBakeOverlap -eq 'avoid') 'Standalone GPU discovery must remain serialized'
$SharedLlamaServer = $true
$GpuDiscoveryBakeOverlap = 'avoid'
. ([scriptblock]::Create($overlapAssignment.Extent.Text))
Assert-True ($effectiveGpuDiscoveryBakeOverlap -eq 'avoid') 'Explicit avoid must remain respected'
$GpuDiscoveryBakeOverlap = 'auto'
$MaxConcurrentStagedWaves = 1
. ([scriptblock]::Create($overlapAssignment.Extent.Text))
Assert-True ($effectiveGpuDiscoveryBakeOverlap -eq 'avoid') 'Default wave cap must remain serialized'

# --- Get-StagedWaveCheckpointStage ---
$plainJob = [pscustomobject]@{ Id = 1 }
Assert-True ((Get-StagedWaveCheckpointStage -Job $plainJob) -eq $null) 'Non-wave job must return null stage'
$missingCheckpointJob = New-FakeStagedWaveJob -WaveWorkspace (New-WaveWorkspace -Stage $null) -Id 2
Assert-True ((Get-StagedWaveCheckpointStage -Job $missingCheckpointJob) -eq '') 'Missing checkpoint must read as an early (empty) stage'
foreach ($stage in @('source_validation', 'reconstruction_generation', 'reconstruction_released', 'cpu_preparation', 'completed')) {
    $stageJob = New-FakeStagedWaveJob -WaveWorkspace (New-WaveWorkspace -Stage $stage) -Id 3
    Assert-True ((Get-StagedWaveCheckpointStage -Job $stageJob) -eq $stage) "Stage $stage must round-trip"
}
$corruptWorkspace = New-WaveWorkspace -Stage 'cpu_preparation'
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
@{ stage = 'cpu_preparation'; items = @() } | ConvertTo-Json | Set-Content -LiteralPath $cachedPath
(Get-Item -LiteralPath $cachedPath).LastWriteTimeUtc = $t1
Assert-True ((Get-StagedWaveCheckpointStage -Job $cachedJob) -eq 'source_validation') 'Unchanged mtime must serve the cached stage'
(Get-Item -LiteralPath $cachedPath).LastWriteTimeUtc = $t2
Assert-True ((Get-StagedWaveCheckpointStage -Job $cachedJob) -eq 'cpu_preparation') 'Bumped mtime must force a fresh read'

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
# in cpu_preparation: exactly the serialized behavior of the old gate.
$serialized = Test-Admission -Jobs @(New-WaveJobAtStage -Stage 'cpu_preparation' -Id 10) -Max 1
Assert-True (-not $serialized.admitted -and $serialized.runningStagedWaveCount -eq 1) 'Cap 1 must keep waves serialized'

# Overlap: a single wave in cpu_preparation admits the next one at cap 2.
$overlap = Test-Admission -Jobs @(New-WaveJobAtStage -Stage 'cpu_preparation' -Id 11) -Max 2
Assert-True ($overlap.admitted) 'cpu_preparation wave must admit the next wave at cap 2'

$streaming = Test-Admission -Jobs @(New-WaveJobAtStage -Stage 'generation_and_validation' -Id 30) -Max 2
Assert-True ($streaming.admitted) 'Streaming waves must allow the next bounded service request'

# A completed checkpoint item enters the existing export lane once, before its sibling finishes.
function Add-StagedWaveTimelineOutcome { param($WorkItem, $WaveState) }
$streamWorkspace = New-WaveWorkspace -Stage 'generation_and_validation'
$streamJob = New-FakeStagedWaveJob -WaveWorkspace $streamWorkspace -Id 31
$streamJob | Add-Member -MemberType NoteProperty -Name WorkItems -Value @(
    [pscustomobject]@{ exerciseId = 'fast' }, [pscustomobject]@{ exerciseId = 'slow' }
)
$streamCheckpoint = Join-Path $streamWorkspace 'staged_wave_checkpoint.json'
@{ stage = 'generation_and_validation'; items = @(
    @{ exerciseId = 'fast'; status = 'completed' }, @{ exerciseId = 'slow'; status = 'pending' }
) } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $streamCheckpoint
$completionQueue = [System.Collections.Queue]::new()
Receive-StagedWaveReadyItems -RunningJobs @($streamJob) -CompletionQueue $completionQueue
Receive-StagedWaveReadyItems -RunningJobs @($streamJob) -CompletionQueue $completionQueue
Assert-True ($completionQueue.Count -eq 1 -and $completionQueue.Peek().exerciseId -eq 'fast') 'Fast movement must export once while its sibling remains pending'
Assert-True ($streamJob.CompletedExerciseIds.ContainsKey('fast')) 'Terminal wave processing must recognize the earlier export'

# Server restart remains blocked while a live extractor holds VRAM, even between GPU operations.
function Get-MotionProcessIdentityState { param($ProcessId, $ExpectedProcessIdentity); return $script:FakeHolderState }
$holderRoot = Join-Path $testRoot 'residency'
$holderDir = Join-Path $holderRoot 'generation-holders'
New-Item -ItemType Directory -Force -Path $holderDir | Out-Null
@{ pid = 123; processIdentity = 456 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $holderDir '123.json')
$script:FakeHolderState = 'running'
Assert-True (Test-SharedLlamaExclusiveHandoffActive -SessionDir $holderRoot) 'Resident extractor must block model startup'
$script:FakeHolderState = 'unknown'
Assert-True (Test-SharedLlamaExclusiveHandoffActive -SessionDir $holderRoot) 'Unverified holder must block model startup'
$script:FakeHolderState = 'stopped'
Assert-True (-not (Test-SharedLlamaExclusiveHandoffActive -SessionDir $holderRoot)) 'Dead holder must not block model startup'

# Early and GPU phases block: no checkpoint yet, source_validation,
# reconstruction_generation, and the reconstruction_released transition all hold the gate.
foreach ($blockingStage in @($null, 'source_validation', 'reconstruction_generation', 'reconstruction_released', 'final_validation')) {
    $blocked = Test-Admission -Jobs @(New-WaveJobAtStage -Stage $blockingStage -Id 12) -Max 2
    Assert-True (-not $blocked.admitted) "Stage $blockingStage must block the next wave"
}

# Two waves at cap 2: full; at cap 3 only if BOTH are in cpu_preparation.
$twoFinal = @(New-WaveJobAtStage -Stage 'cpu_preparation' -Id 13; New-WaveJobAtStage -Stage 'cpu_preparation' -Id 14)
Assert-True (-not (Test-Admission -Jobs $twoFinal -Max 2).admitted) 'Wave count at the cap must block'
Assert-True ((Test-Admission -Jobs $twoFinal -Max 3).admitted) 'Two cpu_preparation waves must admit a third at cap 3'
$oneEarly = @(New-WaveJobAtStage -Stage 'cpu_preparation' -Id 15; New-WaveJobAtStage -Stage 'reconstruction_generation' -Id 16)
Assert-True (-not (Test-Admission -Jobs $oneEarly -Max 3).admitted) 'Any non-final-validation wave must block even below the cap'

# Legacy fallbacks are full GPU-capable pipelines: pending or running, they
# keep the bake lane exclusive.
Assert-True (-not (Test-Admission -Jobs @() -Max 2 -LegacyPending 1).admitted) 'Pending legacy bake item must block'
$legacyRunning = Test-Admission -Jobs @((New-WaveJobAtStage -Stage 'cpu_preparation' -Id 17); (New-FakeLegacyBakeJob -Id 18)) -Max 2
Assert-True (-not $legacyRunning.admitted) 'Running legacy bake job must block'

# Completion jobs are trivial and must never block the next wave.
function Start-Job {
    param($Name, $ScriptBlock, $ArgumentList)
    [pscustomobject]@{ Name = $Name; Worker = $ScriptBlock; Arguments = $ArgumentList }
}
$completionWorkItem = [pscustomobject]@{ exerciseSlug = 'curl' }
$completionJob = Start-StagedResultCompletionJob -WorkItem $completionWorkItem
Assert-True ($completionJob.IsStagedCompletion) 'Completion jobs must be marked IsStagedCompletion'
$besideCompletions = Test-Admission -Jobs @((New-WaveJobAtStage -Stage 'cpu_preparation' -Id 19); $completionJob; $completionJob) -Max 2
Assert-True ($besideCompletions.admitted) 'Completion jobs must not block the next wave'

# --- Completion admission beside a wave (own bounded lane) ---
Assert-True ((Get-FlaggedJobCount -Jobs @() -FlagPropertyName 'IsStagedCompletion') -eq 0) 'Flagged count of an empty lane must be 0'
$laneJobs = @((New-WaveJobAtStage -Stage 'cpu_preparation' -Id 20); $completionJob)
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

# Library opt-in forwards the cap and enables the shared model server.
$libraryRunner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_library.ps1'
$libraryAst = [System.Management.Automation.Language.Parser]::ParseFile($libraryRunner, [ref]$null, [ref]$errors)
$passNode = $libraryAst.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-MovementPass' }, $true)
. ([scriptblock]::Create($passNode.Extent.Text))
function Write-MotionLibraryMessage { param($Message) }
function Exit-IfMotionRunInterrupted { param($ExitCode) }
function Invoke-MotionLibraryLoggedCommand {
    param($Command, $Arguments, $LogPath, $ShowDetails)
    $script:ForwardedLibraryArguments = @($Arguments)
    return 0
}
$summaryPath = $libraryRunner
$DisableCpuPrefetch = $true
$DisableStagedWaves = $false
$PassRestartAttempts = 1
$StagedWaveSize = 8
foreach ($cap in @(1, 2)) {
    $MaxConcurrentStagedWaves = $cap
    Invoke-MovementPass -FirstPass
    $index = [Array]::IndexOf($script:ForwardedLibraryArguments, '-MaxConcurrentStagedWaves')
    Assert-True ($index -ge 0 -and $script:ForwardedLibraryArguments[$index + 1] -eq "$cap") 'Library lost its configured overlap cap'
    Assert-True (('-SharedLlamaServer' -in $script:ForwardedLibraryArguments) -eq ($cap -gt 1)) 'Shared server must accompany the overlap opt-in'
}

# Remove only the explicitly created synthetic tree.
Remove-Item -LiteralPath $testRoot -Recurse -Force
Write-Host 'Wave overlap scheduling tests passed.'
