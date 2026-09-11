$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../scripts/motion_library_logging.ps1')
$state = New-MotionLibraryLogState
$start = [datetime]'2026-09-07T12:00:00Z'
function Snapshot([int]$Seconds, [int]$Done = 7) {
    Format-MotionLibraryProgress -State $state -Now $start.AddSeconds($Seconds) -Message 'Queues: 202 awaiting candidate preparation'
    Format-MotionLibraryProgress -State $state -Now $start.AddSeconds($Seconds) -Message "Progress: 0/262 movements ready. Checking source videos: $Done of 25 (5 usable, 2 unresolved) | Work: 6 active source task(s); oldest: Curl for ${Seconds}s after ${Seconds}s."
}
$first = @(Snapshot 0)
if (-not ($first -match 'Progress')) { throw 'Missing initial summary' }
if (@(Snapshot 90).Count) { throw 'Duplicate snapshot printed' }
if (@(Snapshot 270).Count) { throw 'Early waiting message' }
$waiting = @(Snapshot 360)
if ($waiting.Count -ne 1 -or $waiting[0] -notmatch 'Waiting:.*6m.*oldest: Curl') { throw 'Missing useful waiting line' }
if (@(Snapshot 450).Count) { throw 'Waiting line repeated too soon' }
if (-not (@(Snapshot 500 8) -match 'Progress')) { throw 'Counter change suppressed' }
$event = @(Format-MotionLibraryProgress -State $state -Now $start.AddSeconds(510) -Message 'Source attempt: Curl | timeout')
if (-not ($event -match 'timeout')) { throw 'Timeout event suppressed' }
if (@(Snapshot 790 8).Count) { throw 'Event did not reset quiet interval' }
$stage = 'Checking source videos: 8 of 25 (5 usable, 3 unresolved)'
$null = Format-MotionLibraryProgress -State $state -Now $start.AddSeconds(800) -Message "$stage — Curl."
if (@(Format-MotionLibraryProgress -State $state -Now $start.AddSeconds(830) -Message "$stage.").Count) {
    throw 'Heartbeat removing latest exercise printed duplicate stage'
}
foreach ($warning in @('WARNING: test', 'Failed: test', 'Saved: test')) {
    if (-not @(Format-MotionLibraryProgress -State $state -Message $warning).Count) { throw 'Outcome suppressed' }
}
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($name in @('Get-ObjectProperty', 'Format-CompactElapsed', 'Get-StagedWaveActivityText')) {
    $node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }.GetNewClosure(), $true)
    . ([scriptblock]::Create($node.Extent.Text))
}
$temp = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
$null = New-Item -ItemType Directory -Path $temp
try {
    $checkpoint = @{
        stage = 'source_validation'; metrics = @{ sourceValidationWorkers = 6 }
        items = @(@{ exerciseName = 'Curl'; source = @{status = 'pending'}; sourceActivity = @{
            startedAt = [DateTimeOffset]::UtcNow.AddMinutes(-4).ToString('o')
            operation = 'preparing and validating source video'; videoId = 'video-1'
        }})
    }
    $path = Join-Path $temp 'staged_wave_checkpoint.json'
    $checkpoint | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path
    $job = [pscustomobject]@{ IsStagedWave = $true; WaveWorkspace = $temp; WorkItems = @('Curl') }
    $text = Get-StagedWaveActivityText -Job $job -IncludeWorkerDetails
    if ($text -notmatch '0 of 1' -or $text -notmatch '6 configured lanes' -or $text -notmatch '1 active source task.*Curl / video video-1') {
        throw "Incorrect worker details: $text"
    }
    if ($text -notmatch 'no overall operation deadline') { throw 'Invented deadline' }
    $checkpoint.items[0].source.status = 'failed'
    $checkpoint | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path
    $text = Get-StagedWaveActivityText -Job $job
    if ($text -notmatch '1 unresolved' -or $text -match '1 failed') { throw "Misclassified source outcome: $text" }
} finally {
    Remove-Item -LiteralPath (Join-Path $temp 'staged_wave_checkpoint.json') -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $temp
}
$revalidationLine = 'Revalidation [12/45]: Barbell Clean -> invalid in 473.2s (completed=22/45, valid=2, invalid=8, manual=12, totalElapsed=1255.2s).'
$convertedRevalidation = ConvertTo-MotionLibraryProgress -Line $revalidationLine
if ($convertedRevalidation -ne $revalidationLine) { throw 'Revalidation progress hidden by console filter' }
$renderedRevalidation = @(Format-MotionLibraryProgress -Message $convertedRevalidation -State (New-MotionLibraryLogState))
if (($renderedRevalidation -join "`n") -notmatch 'completed=22/45') { throw 'Revalidation counts lost in formatting' }
if ((ConvertTo-MotionLibraryProgress -Line 'Revalidation [28/45]: Barbell Lying Triceps Extension started.') -notmatch 'started') {
    throw 'Active revalidation exercise hidden'
}
$state = New-MotionLibraryLogState
$queue = 'Queues: 0 awaiting candidate preparation | 99 awaiting source review | 0 ready for reconstruction | 1 active generation batch(es)'
$counts = '47/262 movements ready, 114 unresolved'
$validation = 'Validating generated movements: 0 of 1 (0 kept, 0 without selection; includes baking, deterministic checks and model review)'
function RunSnapshot([int]$Seconds, [string]$Activity, [string]$Counts = $counts) {
    Format-MotionLibraryProgress -State $state -Now $start.AddSeconds($Seconds) -Message $queue
    Format-MotionLibraryProgress -State $state -Now $start.AddSeconds($Seconds) -Message "Progress: $Counts. $Activity after ${Seconds}s."
}
$null = RunSnapshot 0 'Extracting motion: 0 of 1 done, 1 still running'
$null = Format-MotionLibraryProgress -State $state -Now $start.AddSeconds(86) -Message 'Extracting motion: 1 of 1 done - Single Dumbbell Hammer Curl.'
$event = @(Format-MotionLibraryProgress -State $state -Now $start.AddSeconds(88) -Message "$validation.")
if ($event -notmatch 'Validating generated') { throw 'Stage transition suppressed' }
if (@(RunSnapshot 90 $validation).Count) { throw 'Snapshot repeated a just-printed stage and unchanged counts' }
$changed = @(RunSnapshot 180 $validation '48/262 movements ready, 114 unresolved')
if (($changed -join "`n") -notmatch '48/262' -or $changed -match 'Activity:') { throw 'Changed totals must print without repeating activity' }
$waiting = @(RunSnapshot 490 $validation '48/262 movements ready, 114 unresolved')
if ($waiting -notmatch 'Waiting:') { throw 'Stage deduplication hid a long wait' }
$newStage = 'Validating generated movements: 1 of 1 (1 kept, 0 without selection)'
$snapshot = @(RunSnapshot 500 $newStage '48/262 movements ready, 114 unresolved')
if (($snapshot -join "`n") -notmatch 'Activity:.*1 of 1') { throw 'Snapshot-only stage update suppressed' }
if (@(Format-MotionLibraryProgress -State $state -Now $start.AddSeconds(501) -Message "$newStage.").Count) { throw 'Stage event repeated snapshot activity' }
$null = Format-MotionLibraryProgress -State $state -Now $start.AddSeconds(502) -Message 'Starting batch 2 (1 exercises).'
if (-not @(Format-MotionLibraryProgress -State $state -Now $start.AddSeconds(503) -Message "$newStage.").Count) { throw 'New batch inherited old activity deduplication' }
$success = ConvertTo-MotionLibraryProgress 'SUCCESS: Ring Row | Validated movement saved.'
if ($success -ne 'SUCCESS: Ring Row | Validated movement saved.') { throw 'Saved success hidden' }
$successLines = @(Format-MotionLibraryProgress -Message $success -State $state -Timestamp '10:00:00')
if ($successLines.Count -ne 7 -or $successLines[0] -ne '' -or $successLines[2] -ne '[10:00:00] MOVEMENT GENERATED SUCCESSFULLY' -or $successLines[3] -ne '  Exercise: Ring Row') {
    throw 'Success does not stand out as its own block'
}
$countedSuccess = @(Format-MotionLibraryProgress -Message 'SUCCESS: Barbell Push Press | Validated movement saved. | Library: 39/262 ready' -State $state -Timestamp '12:06:39')
if ($countedSuccess[5] -ne '  Library: 39/262 ready' -or $countedSuccess[-1] -ne '') { throw 'Success count or trailing separation missing' }
$legacySuccess = @(Format-MotionLibraryProgress -Message (ConvertTo-MotionLibraryProgress 'Ready: Ring Row') -State $state)
if ($legacySuccess -notcontains '  Exercise: Ring Row') { throw 'Legacy success lost exercise name' }
if ((ConvertTo-MotionLibraryProgress 'Ready: Ring Row') -notmatch '^SUCCESS: Ring Row') { throw 'Legacy success missing' }
if ((ConvertTo-MotionLibraryProgress 'Already have a movement for Ring Row.') -match 'SUCCESS') { throw 'Cache reuse called new success' }
$selected = ConvertTo-MotionLibraryProgress 'Movement result: Ring Row | selected | 11.2s final processing | stage(s): output_validation'
if ($selected -match 'SUCCESS|saved' -or $selected -notmatch '^Movement validated:') { throw 'Selection called saved before files were copied' }

$sourceLine = "Source attempt: Ring Fallout | video EHHN-DoK2k4 | rejected_source_validation: SourceCandidateRejected: Pre-WHAM source validation rejected the source window: score 0.000 is below 0.500; reasons=['source_candidate_window_choice_failed', 'source_candidate_scorecard_no_passing_candidate']."
$source = ConvertTo-MotionLibraryProgress $sourceLine
if ($source -ne 'Source rejected: Ring Fallout | No reviewed video interval passed validation. | Video: EHHN-DoK2k4') { throw "Unreadable source rejection: $source" }
$deferred = ConvertTo-MotionLibraryProgress 'Source review: Ring Fallout | unresolved: source_turn_deferred'
if ($deferred -notmatch '^Source review deferred:.*pending' -or $deferred -match 'rejected') { throw 'Deferred work reported as rejected' }
$unusable = ConvertTo-MotionLibraryProgress 'Source review: Ring Reverse Fly | unresolved: no_source_passed_exact_window_validation'
if ($unusable -notmatch '^No usable source: Ring Reverse Fly') { throw 'Unusable source explanation missing' }

$movementLine = 'Movement result: Ring Row | no_selection | 11.2s final processing | stage(s): output_validation | timings: rawWhamMotionGateSeconds=0.7s | reasons: pre_wham_validated_source_interval_review, post_wham_movement_cut_blocked_by_source_authority, loop_continuity_not_required, loop_bridge_mismatch_ignored_loop_not_required, postprocess_joint_spike, materialized_output_rejected, materialized_incomplete_repetition_phase, materialized_source_endpoint_pose_mismatch'
$movement = ConvertTo-MotionLibraryProgress $movementLine
$readable = @(Format-MotionLibraryProgress -Message $movement -State $state -Timestamp '10:52:34')
if ($readable.Count -ne 4 -or $readable[0] -notmatch '^\[10:52:34\] Movement rejected: Ring Row.*11.2s') { throw "Unclear generated rejection: $readable" }
if ($readable[1] -ne '  - Processing introduced joint jitter.') { throw 'Primary rejection reason hidden' }
if (($readable -join ' ') -match 'pre_wham|loop_|timings:|materialized_') { throw 'Technical or informational codes clutter rejection' }
$unknown = ConvertTo-MotionLibraryReasons 'future_validation_rule'
if ($unknown -ne 'Other detail: future validation rule') { throw 'Unknown diagnostic silently discarded' }
$failed = ConvertTo-MotionLibraryProgress 'Movement result: Ring Row | failed | 1.0s final processing | stage(s): processing_error | RuntimeError: renderer crashed'
if ($failed -notmatch '^Movement processing failed:.*could not finish' -or $failed -match 'Movement rejected') { throw 'Processing error misclassified as invalid motion' }

foreach ($file in @('motion_library_logging.ps1', 'run_exercise_motion_workout_plan.ps1')) {
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot "../scripts/$file"), [ref]$null, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
}
$uncertain = ConvertTo-MotionLibraryProgress 'Source attempt: Ring Row | video abc | needs_source_review: SourceCandidateRejected: disputed'
if ($uncertain -notmatch '^Source review uncertain:' -or $uncertain -match 'Source rejected:') { throw 'Uncertainty reported as rejection' }
foreach ($status in @('source_processing_failed', 'rejected_vlm_timeout')) {
    $processing = ConvertTo-MotionLibraryProgress "Source attempt: Ring Row | video abc | ${status}: TimeoutError: deadline"
    if ($processing -notmatch '^Source processing failed:.*no quality verdict') { throw 'Source processing failure reported as quality rejection' }
}
foreach ($status in @('selected', 'no_selection', 'failed')) {
    $timed = ConvertTo-MotionLibraryProgress "Movement result: Curl | $status | 13.0s final processing | stage(s): output_validation | elapsed breakdown: executor queue=3.0s, waiting for render prefetch=4.0s, pipeline including retries=6.0s | timings: previewBakeSeconds=1.0s"
    if ($timed -notmatch 'waiting for render prefetch=4.0s' -or $timed -notmatch 'pipeline including retries=6.0s' -or $timed -match 'previewBakeSeconds') {
        throw 'Final timing breakdown missing or nested timings leaked into concise log'
    }
}
$windowLine = "Source attempt: Deadlift | video abc | attempt 2/3 this turn | candidate window 314.32-321.32s | rejected_source_validation: SourceCandidateRejected: reasons=['Full deadlift rep with barbell visible.', 'source_candidate_scorecard_passed', 'source_cut_deterministic_confirmation_failed']."
$windowMessage = ConvertTo-MotionLibraryProgress $windowLine
if ($windowMessage -notmatch '^Source window rejected: Deadlift' -or
    $windowMessage -notmatch 'attempt 2/3 this turn' -or
    $windowMessage -notmatch '314.32-321.32s' -or
    $windowMessage -match 'Full deadlift|Other detail|scorecard passed' -or
    $windowMessage -notmatch 'Could not confirm a complete movement') { throw "Misleading window result: $windowMessage" }
foreach ($status in @('needs_source_review', 'source_processing_failed', 'rejected_vlm_timeout')) {
    $message = ConvertTo-MotionLibraryProgress "Source attempt: Deadlift | video abc | attempt 2/3 this turn | candidate window automatic selection | ${status}: failed"
    if ($message -notmatch 'attempt 2/3 this turn' -or $message -notmatch 'candidate window automatic selection' -or $message -match 'Source window rejected:') {
        throw "Missing context or wrong classification: $message"
    }
}
$sourceState = New-MotionLibraryLogState
$lines = @(Format-MotionLibraryProgress -State $sourceState -Message $windowMessage)
if ($lines.Count -ne 2 -or $lines[1] -notmatch 'Could not confirm') { throw 'Source reason not presented separately' }
if (@(Format-MotionLibraryProgress -State $sourceState -Message 'Checking source videos: 5 of 8 (1 usable, 4 unresolved)').Count) {
    throw 'Redundant standalone source counters printed'
}
$summary = @(Format-MotionLibraryProgress -State $sourceState -Message 'Progress: 39/262 movements ready. Checking source videos: 5 of 8 (1 usable, 4 unresolved) after 9m.')
if (-not ($summary -match 'Checking source videos: 5 of 8')) { throw 'Source counters missing from periodic summary' }
$unknownReason = ConvertTo-MotionLibraryReasons "'A complete rep is visible.', 'source_new_failure_code'" -CodesOnly
if ($unknownReason -notmatch 'source new failure code' -or $unknownReason -match 'complete rep') { throw 'Unknown failure code lost or prose retained' }
Write-Host 'Motion logging tests passed.'
