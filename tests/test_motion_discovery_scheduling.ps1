$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root 'scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$sourceReviewTimeout = $ast.ParamBlock.Parameters | Where-Object {
    $_.Name.VariablePath.UserPath -eq 'SourceReviewTimeoutSeconds'
} | Select-Object -First 1
if (-not $sourceReviewTimeout -or $sourceReviewTimeout.DefaultValue.SafeGetValue() -ne 240.0) {
	throw 'The workout-plan wrapper must use the bounded source-review transport timeout by default.'
}
$speedProfileSwitch = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.SwitchStatementAst] -and
    $node.Condition.Extent.Text -eq '$SpeedProfile'
}, $true)
$fastProfileClause = $speedProfileSwitch.Clauses | Where-Object { $_.Item1.Extent.Text -eq '"fast"' } | Select-Object -First 1
if (-not $fastProfileClause) { throw 'Missing fast speed profile.' }
if ($fastProfileClause.Item2.Extent.Text -notmatch '(?s)ContainsKey\("CandidateReviewBatchSize"\).*?\$CandidateReviewBatchSize = 1' -or
    $fastProfileClause.Item2.Extent.Text -notmatch '(?s)ContainsKey\("PosePrefilterSampleFps"\).*?\$PosePrefilterSampleFps = 2\.0') {
    throw 'Fast discovery must screen one candidate at a time using the existing coarse 2 FPS pose scan.'
}
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
    'Get-ArgumentArraySha256', 'Get-DiscoverySemanticArgumentArraySha256', 'Get-ObjectProperty', 'Resolve-WaveSourceSelectionPolicyVersion',
    'Set-DiscoveryArgumentValue', 'Write-CanonicalSourceTurnCursor', 'Set-BoundedSourceRecoveryDiscovery', 'Add-DiscoveryTurnUsage'
)) {
    $functionAst = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $functionName
    }.GetNewClosure(), $true)
    if (-not $functionAst) { throw "Missing source-recovery helper $functionName." }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}
$PythonCommand = 'python'
$sourceReviewTurnId = 'source-recovery-test-turn'
function Invoke-PythonModule {
    param([string[]]$Arguments)
    & $PythonCommand @Arguments | Write-Output
    if ($LASTEXITCODE -ne 0) { throw "python command failed with exit code $LASTEXITCODE." }
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
$initialNoSourceRecoveryBranch = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text -match 'discoveryStopReason -ne .scheduler_yield.' -and
    $node.Extent.Text -match 'Set-BoundedSourceRecoveryDiscovery'
}, $true)
if (-not $initialNoSourceRecoveryBranch) {
    throw 'Initial discovery with no suitable source must spend the shared allowance on another bounded turn.'
}
$decision = [scriptblock]::Create((@(
    (Get-AssignmentText '$stagedWaveAdmission'),
    (Get-AssignmentText '$stagedWaveReady'),
    (Get-AssignmentText '$shouldYieldDiscoveryForStagedWave'),
    (Get-AssignmentText '$canLaunchDiscovery'), (Get-AssignmentText '$canLaunchBake'),
    (Get-AssignmentText '$discoveryAndDownloadDrained'), (Get-AssignmentText '$canStartStagedWave'),
    '@{ ready=$stagedWaveReady; yield=$shouldYieldDiscoveryForStagedWave; discover=$canLaunchDiscovery; bake=$canStartStagedWave }'
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
$recoveryPlan = Join-Path $recoveryWorkspace 'exercise-plan.json'
@{ exercises = @(@{ id = 'recovery-exercise'; name = 'Recovery exercise'; motionContext = @{} }) } |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $recoveryPlan -Encoding UTF8
# Source recovery spends down one per-exercise budget across turns and preserves
# exact attempted windows while allowing other windows from the same video.
$recoveryWorkItem = [pscustomobject]@{
    discoveryArgs = @('--discovery-candidate-budget', '0', '--out-json', 'recovery.json')
    discoveryArgumentsSha256 = ''
    discoverySemanticArgumentsSha256 = ''
    candidateReviewTargetSuitableCount = 1
    bakeWorkspace = $recoveryWorkspace
    exercisePlanPath = $recoveryPlan
    exerciseCandidatesPath = (Join-Path $recoveryWorkspace 'youtube_candidates.json')
    discoveryCandidatesReviewed = 0
    lastDiscoveryTurnReviewed = 0
}
$recoveryWaveState = [pscustomobject]@{
    exerciseId = 'recovery-exercise'
    exerciseName = 'Recovery exercise'
    source = [pscustomobject]@{
    sourceSelectionPolicyVersion = 64
    priorAttemptedCandidateKeys = @()
    priorAttemptedVideoIds = @()
    attempts = @(
        [pscustomobject]@{ candidateKey = 'same-video-window-a'; videoId = 'same-video'; status = 'needs_source_review'; failureOwner = 'source_evidence' },
        [pscustomobject]@{ candidateKey = 'same-video-window-b'; videoId = 'same-video'; status = 'needs_source_review'; failureOwner = 'source_evidence' },
        [pscustomobject]@{ candidateKey = 'same-video-window-c'; videoId = 'same-video'; status = 'needs_source_review'; failureOwner = 'source_evidence' },
        [pscustomobject]@{ candidateKey = 'same-video-window-d'; videoId = 'same-video'; status = 'rejected_source_validation' }
    )
}}
@{ exercises = @(@{ candidateExpansion = @{ discoveryTurn = @{
    reviewedThisTurn = 6; reviewedTotal = 6; timeBudgetSeconds = 180; remainingTimeSeconds = 155
} } }) } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $recoveryWorkItem.exerciseCandidatesPath -Encoding UTF8
Add-DiscoveryTurnUsage -WorkItem $recoveryWorkItem
if ($recoveryWorkItem.discoveryCandidatesReviewed -ne 6 -or $recoveryWorkItem.lastDiscoveryTurnReviewed -ne 6) {
    throw 'Completed discovery usage must be accumulated from the candidate manifest.'
}
if (-not (Set-BoundedSourceRecoveryDiscovery -WorkItem $recoveryWorkItem -WaveState $recoveryWaveState -CandidateBudget 48 -TimeBudgetSeconds 180)) {
    throw 'Source recovery should continue while the shared candidate and time allowances remain.'
}
$candidateBudgetArgument = $recoveryWorkItem.discoveryArgs[[Array]::IndexOf($recoveryWorkItem.discoveryArgs, '--discovery-candidate-budget') + 1]
$timeBudgetArgument = $recoveryWorkItem.discoveryArgs[[Array]::IndexOf($recoveryWorkItem.discoveryArgs, '--discovery-time-budget-seconds') + 1]
if ($recoveryWorkItem.discoveryArgs -contains '--exclude-youtube-video-id' -or
    $candidateBudgetArgument -ne '42' -or
    $timeBudgetArgument -ne '180' -or
    $recoveryWorkItem.candidateReviewTargetSuitableCount -ne 2) {
    throw 'Four failed windows from one video must require only one additional suitable video while preserving alternate windows and budget.'
}

# A resumed process has no in-memory retry counter. It must reconstruct the
# target from the durable exact-window cursor instead of returning to one.
$resumedWorkItem = [pscustomobject]@{
    discoveryArgs = @('--discovery-candidate-budget', '48', '--discovery-time-budget-seconds', '180')
    discoveryArgumentsSha256 = ''
    discoverySemanticArgumentsSha256 = ''
    candidateReviewTargetSuitableCount = 1
    bakeWorkspace = $recoveryWorkspace
    exercisePlanPath = $recoveryPlan
    exerciseCandidatesPath = $recoveryWorkItem.exerciseCandidatesPath
    discoveryCandidatesReviewed = 6
    lastDiscoveryTurnReviewed = 6
}
if (-not (Set-BoundedSourceRecoveryDiscovery -WorkItem $resumedWorkItem -WaveState $null -CandidateBudget 48 -TimeBudgetSeconds 180) -or
    $resumedWorkItem.candidateReviewTargetSuitableCount -ne 2) {
    throw 'A process restart must recover the next suitable-source target from persisted failed windows.'
}

$recoveryWaveState.source.attempts += [pscustomobject]@{
    candidateKey = 'next-video-window-c'; videoId = 'next-video'; status = 'rejected_source_validation'
}
if (-not (Set-BoundedSourceRecoveryDiscovery -WorkItem $recoveryWorkItem -WaveState $recoveryWaveState -CandidateBudget 48 -TimeBudgetSeconds 180) -or
    $recoveryWorkItem.candidateReviewTargetSuitableCount -ne 3) {
    throw 'A second distinct failed video must raise the suitable-video target to three.'
}
$resumePath = Join-Path $recoveryWorkspace 'source_turn_resume.json'
$resume = Get-Content -LiteralPath $resumePath -Raw | ConvertFrom-Json
if (@($resume.attemptedCandidateKeys | Where-Object { $_ -like 'same-video-window-*' }).Count -ne 4 -or
    $resume.attemptedCandidateKeys -notcontains 'next-video-window-c' -or
    @($resume.attemptedVideoIds | Sort-Object -Unique).Count -ne 2 -or
    $resume.attemptedVideoIds -notcontains 'same-video' -or
    $resume.attemptedVideoIds -notcontains 'next-video') {
    throw 'Source recovery must persist exact attempted keys and video provenance for the next candidate pass.'
}
Remove-Item -LiteralPath $recoveryWorkspace -Recurse -Force

# A discovery turn with no suitable candidate has no staged-wave receipt. It
# still spends down the same per-exercise candidate allowance and resumes from
# the DiscoveryBudget checkpoint without creating a fabricated source cursor.
$initialRecoveryWorkspace = Join-Path ([System.IO.Path]::GetTempPath()) ("initial-no-source-recovery-" + [guid]::NewGuid().ToString('N'))
[void][System.IO.Directory]::CreateDirectory($initialRecoveryWorkspace)
$initialCandidatesPath = Join-Path $initialRecoveryWorkspace 'youtube_candidates.json'
@{ exercises = @(@{ candidateExpansion = @{ discoveryTurn = @{
    reviewedThisTurn = 12; stopReason = 'time_budget_exhausted'
} } }) } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $initialCandidatesPath -Encoding UTF8
$initialRecovery = [pscustomobject]@{
    discoveryArgs = @('--discovery-candidate-budget', '48', '--discovery-time-budget-seconds', '180')
    discoveryArgumentsSha256 = ''
    discoverySemanticArgumentsSha256 = ''
    candidateReviewTargetSuitableCount = 1
    bakeWorkspace = $initialRecoveryWorkspace
    exercisePlanPath = $recoveryPlan
    exerciseCandidatesPath = $initialCandidatesPath
    discoveryCandidatesReviewed = 0
    lastDiscoveryTurnReviewed = 0
}
Add-DiscoveryTurnUsage -WorkItem $initialRecovery
if (-not (Set-BoundedSourceRecoveryDiscovery -WorkItem $initialRecovery -WaveState $null -CandidateBudget 48 -TimeBudgetSeconds 180)) {
    throw 'An initial no-source turn should continue when unused candidate allowance remains.'
}
$initialCandidateBudget = $initialRecovery.discoveryArgs[[Array]::IndexOf($initialRecovery.discoveryArgs, '--discovery-candidate-budget') + 1]
if ($initialRecovery.discoveryCandidatesReviewed -ne 12 -or $initialCandidateBudget -ne '36' -or
    $initialRecovery.candidateReviewTargetSuitableCount -ne 1 -or
    (Test-Path -LiteralPath (Join-Path $initialRecoveryWorkspace 'source_turn_resume.json'))) {
    throw 'Initial discovery recovery must reuse reviewed candidates without inventing a source cursor or increasing the winner target.'
}
$cappedRecoveryPlan = Join-Path $initialRecoveryWorkspace 'exercise-plan.json'
@{ exercises = @(@{ id = 'recovery-exercise'; name = 'Recovery exercise'; motionContext = @{} }) } |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $cappedRecoveryPlan -Encoding UTF8
$cappedRecovery = [pscustomobject]@{
    discoveryArgs = @('--discovery-candidate-budget', '0', '--out-json', 'recovery.json')
    discoveryArgumentsSha256 = ''
    discoverySemanticArgumentsSha256 = ''
    candidateReviewTargetSuitableCount = 1
    maxCandidateReviewTargetSuitableCount = 1
    bakeWorkspace = $initialRecoveryWorkspace
    exercisePlanPath = $cappedRecoveryPlan
    exerciseCandidatesPath = $initialCandidatesPath
    discoveryCandidatesReviewed = 0
    lastDiscoveryTurnReviewed = 1
}
$cappedRecoveryWave = [pscustomobject]@{
    exerciseId = 'recovery-exercise'
    exerciseName = 'Recovery exercise'
    source = [pscustomobject]@{
    sourceSelectionPolicyVersion = 64
    priorAttemptedCandidateKeys = @()
    priorAttemptedVideoIds = @()
    attempts = @([pscustomobject]@{ candidateKey = 'failed-window'; videoId = 'failed-video' })
} }
if (-not (Set-BoundedSourceRecoveryDiscovery -WorkItem $cappedRecovery -WaveState $cappedRecoveryWave -CandidateBudget 48 -TimeBudgetSeconds 180) -or
    $cappedRecovery.candidateReviewTargetSuitableCount -ne 1) {
    throw 'An explicit suitable-candidate maximum must still bound recovery selection.'
}
Remove-Item -LiteralPath $initialRecoveryWorkspace -Recurse -Force

$recoveryWorkItem.discoveryCandidatesReviewed = 48
$recoveryWorkItem.lastDiscoveryTurnReviewed = 6
if (Set-BoundedSourceRecoveryDiscovery -WorkItem $recoveryWorkItem -WaveState $recoveryWaveState -CandidateBudget 48 -TimeBudgetSeconds 180) {
    throw 'Source-discovery continuation must stop when the cumulative candidate allowance is exhausted.'
}
$recoveryWorkItem.discoveryCandidatesReviewed = 6
$recoveryWorkItem.lastDiscoveryTurnReviewed = 0
if (Set-BoundedSourceRecoveryDiscovery -WorkItem $recoveryWorkItem -WaveState $recoveryWaveState -CandidateBudget 48 -TimeBudgetSeconds 180) {
    throw 'Source-discovery continuation must stop when the prior turn found no new candidates.'
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
if (-not $result.ready -or -not $result.yield -or -not $result.bake -or $result.discover) { throw 'A singleton with no active source review must dispatch immediately.' }
$avoidGpuDiscoveryBakeOverlap = $false
$result = & $decision
if (-not $result.ready -or $result.yield -or -not $result.bake -or -not $result.discover) { throw 'An explicitly safe overlap mode must not yield discovery for an admitted wave.' }
$avoidGpuDiscoveryBakeOverlap = $true
$discoveryRunningJobs = @(1)
$result = & $decision
if (-not $result.ready -or $result.yield -or $result.bake -or $result.discover) { throw 'A ready item must drain active source work without admitting queued work or starting reconstruction.' }
$pendingBakeItems = @(1..32)
$result = & $decision
if (-not $result.yield -or $result.bake -or $result.discover) { throw 'A full ready queue must request cooperative yield at the configured cap.' }
$discoveryRunningJobs = @()
$pendingBakeItems = @()
$result = & $decision
if ($result.ready -or $result.bake) { throw 'Empty batch must not start.' }
$pendingBakeItems = @(1..32)
$discoveryRunningJobs = @()
$result = & $decision
if (-not $result.ready -or -not $result.bake) { throw 'Full batch should start immediately.' }
$effectiveMaxConcurrentStagedWaves = 0
$result = & $decision
if (-not $result.ready -or $result.bake -or $result.discover) { throw 'A ready cohort must wait for GPU admission without starting more GPU discovery.' }
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
