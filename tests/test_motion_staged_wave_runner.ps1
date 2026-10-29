$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }

$cursorFunction = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Write-CanonicalSourceTurnCursor'
}, $true)
if (-not $cursorFunction -or $cursorFunction.Extent.Text -notmatch 'ConvertTo-Json -Depth 64' -or
    $cursorFunction.Extent.Text -notmatch 'source_turn_cursor_cli' -or
    $cursorFunction.Extent.Text -notmatch '--transition' -or
    $cursorFunction.Extent.Text -notmatch '\$Transition') {
    throw 'PowerShell must hand the complete staged receipt to the canonical Python cursor writer.'
}
. ([scriptblock]::Create($cursorFunction.Extent.Text))
$cursorFixture = Join-Path ([IO.Path]::GetTempPath()) ('motion-cursor-handoff-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $cursorFixture | Out-Null
try {
    $motionContext = @{ action = 'squat'; equipment = @('dumbbell') }
    $exercisePlanPath = Join-Path $cursorFixture 'plan.json'
    @{ exercises = @(@{ id = 'ex-1'; name = 'Squat'; motionContext = $motionContext }) } |
        ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $exercisePlanPath -Encoding UTF8
    $workItem = [pscustomobject]@{
        bakeWorkspace = $cursorFixture
        exercisePlanPath = $exercisePlanPath
    }
    $sourceReviewTurnId = 'turn-ps'
    $waveState = @{
        exerciseId = 'ex-1'
        exerciseName = 'Squat'
        source = @{
            sourceSelectionPolicyVersion = 4
            priorAttemptedCandidateKeys = @()
            priorAttemptedVideoIds = @()
            attempts = @(@{ candidateKey = 'candidate-A'; videoId = 'video-A' })
            nextCandidateKey = 'candidate-B'
        }
    }
    function Invoke-PythonModule {
        param([string[]]$Arguments)
        & python @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Python cursor CLI exited $LASTEXITCODE" }
    }
    Write-CanonicalSourceTurnCursor -WorkItem $workItem -WaveState $waveState -Transition 'next_source_candidate'
    $writtenCursor = Get-Content -LiteralPath (Join-Path $cursorFixture 'source_turn_resume.json') -Raw | ConvertFrom-Json
    if ($writtenCursor.sourceReviewTurnId -ne 'turn-ps' -or
        $writtenCursor.nextCandidateKey -ne 'candidate-B' -or
        @($writtenCursor.attemptedCandidateKeys) -notcontains 'candidate-A' -or
        @($writtenCursor.attemptedVideoIds) -notcontains 'video-A') {
        throw 'The real PowerShell-to-Python handoff did not persist the next key and failed-candidate exclusions.'
    }
} finally {
    $resolvedCursorFixture = [IO.Path]::GetFullPath($cursorFixture)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolvedCursorFixture.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unsafe cursor fixture cleanup path.'
    }
    Remove-Item -LiteralPath $resolvedCursorFixture -Recurse -Force
}

$cancelGuard = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text -match 'Test-MotionRunCancelRequested' -and
    $node.Extent.Text -match 'Exit-IfMotionRunInterrupted -ExitCode 130'
}, $true)
$waveStatesAssignment = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$waveStates'
}, $true)
if (-not $cancelGuard -or -not $waveStatesAssignment -or
    $cancelGuard.Extent.StartOffset -gt $waveStatesAssignment.Extent.StartOffset) {
    throw 'A staged-wave cancellation must exit 130 before retry or legacy fallback routing.'
}
if ($ast.Extent.Text -notmatch "'retry_processing', 'repair_evidence'" -or
    $ast.Extent.Text -notmatch 'source_evidence_repair') {
    throw 'Unresolved required evidence must route to retained-source repair instead of an unchanged bake retry.'
}
if ($ast.Extent.Text -notmatch 'approved exact source cut is retained' -or
    $ast.Extent.Text -notmatch 'support evidence remained incomplete after bounded targeted observation') {
    throw 'Incomplete pre-reconstruction contact evidence must be reported as retained-source review, without claiming motion was generated.'
}

$timingFunction = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Add-StagedWaveSummaryTimings'
}, $true)
if (-not $timingFunction) { throw 'Common staged-wave timing enrichment is missing.' }
function Get-ObjectProperty {
    param([object]$Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary] -and $Object.Contains($Name)) { return $Object[$Name] }
    if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}
function Get-OptionalDouble {
    param([object]$Value)
    if ($null -eq $Value) { return $null }
    try { return [double]$Value } catch { return $null }
}
. ([scriptblock]::Create($timingFunction.Extent.Text))
$summary = [ordered]@{ timings = [ordered]@{} }
$waveState = @{
    source = @{ attempts = @(@{ candidateKey = 'A' }, @{ candidateKey = 'B' }) }
    reconstruction = @{ attempts = @(@{ status = 'prepared'; cacheStatus = 'generated'; elapsedSeconds = 3.2 }) }
    finalValidation = @{
        elapsedSeconds = 1.1
        candidateDiagnostics = @(@{ timings = @{ totalSeconds = 0.4 }; reasons = @('contact_failed') })
    }
}
Add-StagedWaveSummaryTimings -Summary $summary -WaveState $waveState -WaveResult @{ elapsedSeconds = 5.8 } -WaveId 'wave-1'
if ($summary.timings.stagedWaveId -ne 'wave-1' -or
    $summary.timings.stagedWaveElapsedSeconds -ne 5.8 -or
    $summary.timings.sourceAttemptCount -ne 2 -or
    $summary.timings.reconstructionSeconds -ne 3.2 -or
    $summary.timings.finalValidationSeconds -ne 1.1 -or
    $summary.timings.finalValidationDiagnosticSeconds -ne 0.4 -or
    $summary.finalValidationRejectionReasons -notcontains 'contact_failed') {
    throw 'Terminal staged-wave summaries must retain the source, reconstruction, and validation timing evidence.'
}

$progressFunction = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Write-ProgressCheckpoint'
}, $true)
if (-not $progressFunction -or $progressFunction.Extent.Text -notmatch 'Write-JsonAtomically -Path \$summaryPath' -or
    $progressFunction.Extent.Text -notmatch '\$liveSummary\.pendingExerciseCount') {
    throw 'Every progress checkpoint must refresh the live summary counts.'
}
. ([scriptblock]::Create($progressFunction.Extent.Text))
function Write-JsonAtomically {
    param([string]$Path, [object]$Value, [int]$Depth = 64)
    $Value | ConvertTo-Json -Depth $Depth | Set-Content -LiteralPath $Path -Encoding UTF8
}
function Update-IncrementalMobilePackage { param([int]$SuccessfulCount) }
$summaryFixture = Join-Path ([IO.Path]::GetTempPath()) ('motion-live-summary-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $summaryFixture | Out-Null
try {
    $movementRunId = 'live-summary-run'
    $LibraryRunId = ''
    $movementRunStartedAtUtc = '2026-10-27T00:00:00Z'
    $inputIdentitySha256 = 'input'
    $definitionsInputSha256 = 'definitions'
    $effectiveWorkoutPlanInputSha256 = 'plan'
    $resolvedWorkoutPlanJson = 'plan.json'
    $resolvedWorkspaceRoot = $summaryFixture
    $summaryPath = Join-Path $summaryFixture 'summary.json'
    $progressCheckpointPath = Join-Path $summaryFixture 'checkpoint.json'
    $summaryByIndex = @{}
    $workItems = @(@{ index = 0 }, @{ index = 1 })
    $pendingPrefetchItems = [System.Collections.Queue]::new()
    $pendingDiscoveryItems = [System.Collections.Queue]::new()
    $pendingSourceDownloadItems = [System.Collections.Queue]::new()
    $pendingFallbackSourceDownloadItems = [System.Collections.Queue]::new()
    $pendingBakeItems = [System.Collections.Queue]::new()
    $pendingLegacyBakeItems = [System.Collections.Queue]::new()
    $pendingCompletionItems = [System.Collections.Queue]::new()
    $prefetchRunningJobs = @()
    $discoveryRunningJobs = @()
    $sourceDownloadRunningJobs = @()
    $bakeRunningJobs = @()
    $script:MotionRunOutcome = 'running'
    $script:MotionSourceIdentity = @{ schemaVersion = 1 }
    [pscustomobject]@{
        schemaVersion = 2; runId = $movementRunId; generatedAt = 'startup';
        totalExerciseCount = 1; terminalExerciseCount = 0; successfulExerciseCount = 0;
        unsuccessfulExerciseCount = 0; pendingExerciseCount = 1; outcome = 'running'; exercises = @()
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-ProgressCheckpoint
    $updatedSummary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
    if (-not $updatedSummary.updatedAt -or $updatedSummary.totalExerciseCount -ne 2 -or
        $updatedSummary.pendingExerciseCount -ne 2 -or $updatedSummary.runId -ne $movementRunId) {
        throw 'A live summary without updatedAt must be safely extended and refreshed from the checkpoint.'
    }
} finally {
    $resolvedSummaryFixture = [IO.Path]::GetFullPath($summaryFixture)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolvedSummaryFixture.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unsafe summary fixture cleanup path.'
    }
    Remove-Item -LiteralPath $resolvedSummaryFixture -Recurse -Force
}
Write-Host 'Staged-wave runner checks passed.'
