$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root 'scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
function Get-AssignmentText([string]$Name) {
    $node = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq $Name
    }.GetNewClosure(), $true)
    if (-not $node) { throw "Missing assignment $Name" }
    return $node.Extent.Text
}
$admissionFunction = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Test-StagedWaveOverlapAdmission'
}, $true)
if (-not $admissionFunction) { throw 'Missing staged-wave admission function.' }
. ([scriptblock]::Create($admissionFunction.Extent.Text))
$splitPlacementFunction = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Test-VerifiedExclusiveGpuSplitPlacement'
}, $true)
if (-not $splitPlacementFunction) { throw 'Missing verified exclusive GPU placement check.' }
. ([scriptblock]::Create($splitPlacementFunction.Extent.Text))
foreach ($functionName in @(
    'Get-ArgumentArraySha256', 'Get-ObjectProperty', 'Resolve-WaveSourceSelectionPolicyVersion',
    'Set-DiscoveryArgumentValue', 'Set-BoundedSourceRecoveryDiscovery'
)) {
    $functionAst = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $functionName
    }.GetNewClosure(), $true)
    if (-not $functionAst) { throw "Missing source-recovery helper $functionName." }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}
$SourceSelectionPolicyVersion = 64
if ((Resolve-WaveSourceSelectionPolicyVersion -Source ([pscustomobject]@{})) -ne 64) {
    throw 'Legacy wave state without a reported source policy version must use the current policy version.'
}
$legacyDeferredBranch = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    @($node.Clauses | Where-Object {
        $_.Item1.Extent.Text -match "(?s)retryDisposition.*continue_source" -and
        $_.Item1.Extent.Text -match "(?s)failureReason.*source_turn_deferred"
    }).Count -gt 0
}, $true)
if (-not $legacyDeferredBranch) { throw 'Legacy source_turn_deferred results must share the cursor continuation route.' }
$decision = [scriptblock]::Create((@(
    (Get-AssignmentText '$stagedWaveAdmission'),
    (Get-AssignmentText '$stagedWaveReady'),
    (Get-AssignmentText '$shouldYieldDiscoveryForStagedWave'),
    (Get-AssignmentText '$canLaunchDiscovery'), (Get-AssignmentText '$canLaunchBake'),
    (Get-AssignmentText '$discoveryAndDownloadDrained'), (Get-AssignmentText '$canStartStagedWave'),
    '@{ ready=$stagedWaveReady; discover=$canLaunchDiscovery; bake=$canStartStagedWave }'
) -join "`n"))
$overlapPolicy = [scriptblock]::Create((Get-AssignmentText '$effectiveGpuDiscoveryBakeOverlap') + "`n`$effectiveGpuDiscoveryBakeOverlap")
$splitPlacementRows = @('0, GPU-LLAMA', '1, GPU-RECON')
if (-not (Test-VerifiedExclusiveGpuSplitPlacement -Device '1' -GpuRows $splitPlacementRows) -or
    (Test-VerifiedExclusiveGpuSplitPlacement -Device '1' -GpuRows @('0, GPU-LLAMA', '1, GPU-LLAMA')) -or
    (Test-VerifiedExclusiveGpuSplitPlacement -Device '0' -GpuRows $splitPlacementRows)) {
    throw 'Split placement must require distinct verified GPU 0 and exclusive-device UUIDs.'
}
$SharedLlamaServer = $true
$StagedWaveSize = 32
$MaxConcurrentStagedWaves = 1
$verifiedExclusiveGpuSplit = $true
$GpuDiscoveryBakeOverlap = 'auto'
$discoveryUsesGpu = $true
$globalGpuLockEnabled = $true
if ((& $overlapPolicy) -ne 'allow') {
    throw 'Verified split GPUs must allow discovery/reconstruction overlap without increasing wave concurrency.'
}
$GpuDiscoveryBakeOverlap = 'avoid'
if ((& $overlapPolicy) -ne 'avoid') { throw 'Explicit avoid must override split-GPU auto overlap.' }
$GpuDiscoveryBakeOverlap = 'auto'
$verifiedExclusiveGpuSplit = $false
if ((& $overlapPolicy) -ne 'avoid') { throw 'Unverified split placement must retain serialized GPU behavior.' }
$stagedWavesEnabled = $true
$stagedWaveIndex = 0
$StagedWaveSize = 32
$StagedWaveMaxWaitSeconds = 300
$effectiveMaxConcurrentStagedWaves = 1

$recoveryWorkspace = Join-Path ([System.IO.Path]::GetTempPath()) ("motion-source-recovery-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $recoveryWorkspace | Out-Null
# Source exhaustion gets one bounded discovery turn while preserving exact
# attempted windows for candidate-key filtering in the next source pass.
$recoveryWorkItem = [pscustomobject]@{
    discoveryArgs = @('--discovery-candidate-budget', '0', '--out-json', 'recovery.json')
    discoveryArgumentsSha256 = ''
    candidateReviewTargetSuitableCount = 2
    bakeWorkspace = $recoveryWorkspace
}
$recoveryWaveState = [pscustomobject]@{ source = [pscustomobject]@{
    sourceSelectionPolicyVersion = 64
    priorAttemptedCandidateKeys = @('old-video-window-a')
    priorAttemptedVideoIds = @('previously-failed-video')
    attempts = @([pscustomobject]@{ candidateKey = 'current-video-window-b'; videoId = 'current-failed-video' })
}}
if (-not (Set-BoundedSourceRecoveryDiscovery -WorkItem $recoveryWorkItem -WaveState $recoveryWaveState -CandidateBudget 0)) {
    throw 'First bounded source-discovery continuation was refused.'
}
if ($recoveryWorkItem.discoveryArgs -contains '--exclude-youtube-video-id' -or
    $recoveryWorkItem.discoveryArgs[[Array]::IndexOf($recoveryWorkItem.discoveryArgs, '--discovery-candidate-budget') + 1] -ne '3' -or
    $recoveryWorkItem.candidateReviewTargetSuitableCount -ne 1) {
    throw 'Source recovery must keep alternate windows eligible and bound an unlimited discovery budget to one candidate.'
}
$resumePath = Join-Path $recoveryWorkspace 'source_turn_resume.json'
$resume = Get-Content -LiteralPath $resumePath -Raw | ConvertFrom-Json
if ($resume.attemptedCandidateKeys -notcontains 'old-video-window-a' -or
    $resume.attemptedCandidateKeys -notcontains 'current-video-window-b' -or
    $resume.attemptedVideoIds -notcontains 'previously-failed-video' -or
    $resume.attemptedVideoIds -notcontains 'current-failed-video') {
    throw 'Source recovery must persist exact attempted keys and video provenance for the next candidate pass.'
}
Remove-Item -LiteralPath $recoveryWorkspace -Recurse -Force
if (Set-BoundedSourceRecoveryDiscovery -WorkItem $recoveryWorkItem -WaveState $recoveryWaveState -CandidateBudget 0) {
    throw 'Source-discovery continuation must stop after one recovery turn.'
}
$avoidGpuDiscoveryBakeOverlap = $true
$pendingBakeItems = @(1)
$pendingLegacyBakeItems = @()
$pendingCompletionItems = @()
$bakeRunningJobs = @()
$pendingDiscoveryItems = @(1)
$discoveryRunningJobs = @()
$pendingSourceDownloadItems = @()
$pendingFallbackSourceDownloadItems = @()
$sourceDownloadRunningJobs = @()
$result = & $decision
if (-not $result.ready -or -not $result.bake -or $result.discover) { throw 'An admitted singleton must dispatch immediately and request discovery yield on the shared GPU.' }
$avoidGpuDiscoveryBakeOverlap = $false
$result = & $decision
if (-not $result.ready -or -not $result.bake -or -not $result.discover) { throw 'An explicitly safe overlap mode must not yield discovery for an admitted wave.' }
$avoidGpuDiscoveryBakeOverlap = $true
$discoveryRunningJobs = @(1)
$result = & $decision
if (-not $result.ready -or $result.bake -or $result.discover) { throw 'A ready item must request a discovery yield and wait for the active GPU owner.' }
$discoveryRunningJobs = @()
$pendingBakeItems = @()
$result = & $decision
if ($result.ready -or $result.bake) { throw 'Empty batch must not start.' }
$pendingBakeItems = @(1..32)
$result = & $decision
if (-not $result.ready -or -not $result.bake) { throw 'Full batch should start immediately.' }
$effectiveMaxConcurrentStagedWaves = 0
$result = & $decision
if (-not $result.ready -or $result.bake -or -not $result.discover) { throw 'Discovery must continue when no staged-wave slot is available.' }
$effectiveMaxConcurrentStagedWaves = 1

# Handoff drains ready work only up to StagedWaveSize.
$handoff = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.WhileStatementAst] -and
    $node.Condition.Extent.Text -match '\$waveItems\.Count -lt \$StagedWaveSize'
}, $true)
if (-not $handoff) { throw 'Wave handoff must preserve StagedWaveSize as a maximum.' }

# Cached review work must not consume this run's bounded CPU preparation buffer.
$prefetchLoop = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.WhileStatementAst] -and
    $node.Condition.Extent.Text -match 'PrefetchQueueDepth'
}, $true)
$prefetchDecision = [scriptblock]::Create($prefetchLoop.Condition.Extent.Text)
$pendingPrefetchItems = @(1)
$prefetchRunningJobs = @()
$PrefetchWorkers = 2
$PrefetchQueueDepth = 40
$pendingDiscoveryItems = @(1..42 | ForEach-Object { [pscustomobject]@{ prefetchReused = $true } })
if (-not (& $prefetchDecision)) { throw 'Cached source-review backlog blocked CPU preparation.' }
$pendingDiscoveryItems += @(1..40 | ForEach-Object { [pscustomobject]@{ prefetchReused = $false } })
if (& $prefetchDecision) { throw 'CPU preparation buffer is not bounded.' }
Write-Output 'Scheduling checks passed: partial wait, full batch, empty queue, and exclusive GPU ownership.'

# Execute the production yield block without starting any job or GPU work.
$yieldBlock = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Clauses[0].Item1.Extent.Text -eq '$shouldYieldDiscoveryForStagedWave'
}, $true)
if (-not $yieldBlock) { throw 'Missing cooperative discovery yield block.' }
$testDirectory = Join-Path $root ('build/test-discovery-yield/' + [guid]::NewGuid().ToString('N'))
[void][System.IO.Directory]::CreateDirectory($testDirectory)
$discoveryRunningJobs = @([pscustomobject]@{ WorkItem = [pscustomobject]@{
    exerciseCandidatesPath = Join-Path $testDirectory 'youtube_candidates.json'; exerciseName = 'Test movement'
}})
$yieldDecision = [scriptblock]::Create($yieldBlock.Extent.Text)
$stagedWaveReady = $false
$stagedWaveAdmission = [pscustomobject]@{ admitted = $true; runningStagedWaveCount = 0 }
$shouldYieldDiscoveryForStagedWave = $false
& $yieldDecision
if (Test-Path -LiteralPath (Join-Path $testDirectory 'discovery_yield.request')) { throw 'Yield requested without ready reconstruction.' }
$stagedWaveReady = $true
$shouldYieldDiscoveryForStagedWave = $true
& $yieldDecision
if (-not (Test-Path -LiteralPath (Join-Path $testDirectory 'discovery_yield.request'))) { throw 'Ready reconstruction failed to request discovery yield.' }
Write-Output 'Discovery yield signal checks passed.'
