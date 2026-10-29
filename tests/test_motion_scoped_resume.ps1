$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$turnAssignment = $ast.Find({ param($n)
    $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $n.Left.Extent.Text -eq '$sourceReviewTurnId'
}, $true)
$preflightAssignment = $ast.Find({ param($n)
    $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $n.Left.Extent.Text -eq '$listArgs'
}, $true)
if (-not $turnAssignment -or -not $preflightAssignment -or
    $turnAssignment.Extent.StartOffset -gt $preflightAssignment.Extent.StartOffset) {
    throw 'Review-turn identity must exist before offline budget preflight.'
}
$movementRunId = 'invocation-one'
foreach ($LibraryRunId in @('library-one', '')) {
    . ([scriptblock]::Create($turnAssignment.Extent.Text))
    $expectedTurn = if ($LibraryRunId) { $LibraryRunId } else { $movementRunId }
    if ($sourceReviewTurnId -ne $expectedTurn) { throw 'Review budget must follow the library turn across invocation restarts.' }
}
if ($preflightAssignment.Extent.Text -notmatch '"--source-review-turn-id", \$sourceReviewTurnId' -or
    $ast.Extent.Text -notmatch 'sourceReviewTurnId = \$sourceReviewTurnId') {
    throw 'Offline budget preflight and staged manifests must share the same review turn.'
}
$node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text.StartsWith('if ($priorRunStateExists -and -not $script:MotionSourceIdentityMatchesPriorRun)') }, $true)
if ($null -eq $node) { throw 'Source identity guard not found' }
$priorStateAssignment = $ast.Find({
    param($n)
    $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $n.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
    $n.Left.VariablePath.UserPath -eq 'priorRunStateExists'
}, $true)
if ($null -eq $priorStateAssignment) { throw 'Prior-state capture not found' }
$earlySummaryFunction = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-EarlyMotionRunOutcomeSummary' }, $true)
if ($null -eq $earlySummaryFunction) { throw 'Early summary writer not found' }
$definitionReviewReasonFunction = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-DefinitionReviewReason' }, $true)
$discoveryReadyFunction = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-DiscoveryStageReady' }, $true)
if ($null -eq $definitionReviewReasonFunction -or $null -eq $discoveryReadyFunction) { throw 'Discovery resume guards not found' }
$initialSummaryCall = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.Extent.Text -eq 'Write-EarlyMotionRunOutcomeSummary -Outcome "running"' }, $true)
if ($null -eq $initialSummaryCall -or $priorStateAssignment.Extent.StartOffset -gt $initialSummaryCall.Extent.StartOffset) {
    throw 'Prior run state must be captured before the current startup summary is written.'
}
$priorRunStateExists = $true
$script:MotionSourceIdentityMatchesPriorRun = $false
foreach ($explicitDisable in @($false, $true)) {
    $DisableStageResume = $explicitDisable
    $DisableMotionProcessingResume = $false
    . ([scriptblock]::Create($node.Extent.Text))
    if ($DisableStageResume -ne $explicitDisable -or -not $DisableMotionProcessingResume) {
        throw 'Code changes must invalidate motion processing while retaining signed source stages and explicit disable overrides'
    }
}
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('motion-source-startup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture | Out-Null
try {
    . ([scriptblock]::Create($earlySummaryFunction.Extent.Text))
    . ([scriptblock]::Create($definitionReviewReasonFunction.Extent.Text))
    . ([scriptblock]::Create($discoveryReadyFunction.Extent.Text))
    $discoveryStagePolicyVersion = 5
    $candidatePath = Join-Path $fixture 'youtube_candidates.json'
    '{}' | Set-Content -LiteralPath $candidatePath
    $definitionFailure = [pscustomobject]@{
        wrapperDiscoverySignature = [pscustomobject]@{
            schemaVersion = 1
            policyVersion = 5
            argumentsSha256 = 'args-sha'
            exercisePlanSha256 = 'plan-sha'
            equipmentSha256 = ''
        }
        exercises = @([pscustomobject]@{
            status = 'needs_definition_review'
            reason = 'target_action_definition_unresolved'
            exerciseMotionContract = [pscustomobject]@{ actionDefinitionAuthority = 'unresolved'; actionDefinitionStatus = 'defined' }
        })
    }
    $discoveryWorkItem = [pscustomobject]@{
        exerciseCandidatesPath = $candidatePath
        definitionReadinessStatus = 'ready'
        discoveryArgumentsSha256 = 'args-sha'
        exercisePlanSha256 = 'plan-sha'
        equipmentSha256 = ''
    }
    if (Test-DiscoveryStageReady -WorkItem $discoveryWorkItem -Payload $definitionFailure) {
        throw 'A cached definition failure must be regenerated when current preflight has an approved definition.'
    }
    $discoveryWorkItem.definitionReadinessStatus = 'needs_definition_review'
    if (-not (Test-DiscoveryStageReady -WorkItem $discoveryWorkItem -Payload $definitionFailure)) {
        throw 'A signed unresolved-definition result should remain reusable when current preflight is unresolved.'
    }
    $discoveryWorkItem.definitionReadinessStatus = 'ready'
    $definitionFailure.exercises[0].exerciseMotionContract.actionDefinitionAuthority = 'structured_definition'
    $definitionFailure.exercises[0].exerciseMotionContract.actionDefinitionStatus = 'uncertain'
    if (-not (Test-DiscoveryStageReady -WorkItem $discoveryWorkItem -Payload $definitionFailure)) {
        throw 'A current uncertain contract with structured-definition authority should remain reusable.'
    }

    $summaryPath = Join-Path $fixture 'workout_motion_generation_summary.json'
    $progressCheckpointPath = Join-Path $fixture 'workout_motion_generation_checkpoint.json'
    $script:MotionSourceIdentityPath = Join-Path $fixture 'motion_source_identity.json'
    $movementRunId = 'fresh-run'
    $movementRunStartedAtUtc = '2026-10-24T00:00:00Z'
    $LibraryRunId = ''
    $inputIdentitySha256 = 'input-sha'
    $definitionsInputSha256 = 'definitions-sha'
    $effectiveWorkoutPlanInputSha256 = 'effective-plan-sha'
    $earlyRunTargetCount = 1
    $script:MotionSourceIdentity = @{ schemaVersion = 1 }
    $resolvedWorkoutPlanJson = 'plan.json'
    $resolvedWorkspaceRoot = $fixture

    . ([scriptblock]::Create($priorStateAssignment.Extent.Text))
    if ($priorRunStateExists) { throw 'A fresh workspace was mistaken for a previous run before its first summary write.' }
    Write-EarlyMotionRunOutcomeSummary -Outcome 'running'
    if (-not (Test-Path -LiteralPath $summaryPath) -or $priorRunStateExists) {
        throw 'Writing the current startup summary must not change the captured fresh-workspace state.'
    }

    Remove-Item -LiteralPath $summaryPath -Force
    'prior checkpoint' | Set-Content -LiteralPath $progressCheckpointPath
    . ([scriptblock]::Create($priorStateAssignment.Extent.Text))
    if (-not $priorRunStateExists) { throw 'A genuine prior checkpoint was not captured before startup.' }
    $script:MotionSourceIdentityMatchesPriorRun = $false
    $DisableStageResume = $false
    $DisableMotionProcessingResume = $false
    . ([scriptblock]::Create($node.Extent.Text))
    if (-not $DisableMotionProcessingResume -or $DisableStageResume) {
        throw 'A genuine prior run with changed source identity must disable motion processing while retaining source-stage resume.'
    }
} finally {
    $resolvedFixture = [IO.Path]::GetFullPath($fixture)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolvedFixture.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unsafe fixture cleanup path.'
    }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}
Write-Host 'Scoped resume checks passed.'
