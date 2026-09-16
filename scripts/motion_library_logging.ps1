# Presentation only: retain native process execution and its Ctrl+C/exit semantics.
function ConvertTo-MotionLibraryReasons {
    param([string]$Reasons, [switch]$CodesOnly)
    $labels = @{
        source_candidate_scorecard_no_passing_candidate = 'No reviewed video interval passed validation.'
        source_candidate_window_choice_failed = 'Could not select a usable video interval.'
        source_cut_deterministic_candidate_filter_failed = 'Video intervals failed the motion checks.'
        source_cut_deterministic_confirmation_failed = 'Could not confirm a complete movement within the selected interval.'
        source_cut_boundary_uncertain = 'The movement start or end could not be confirmed.'
        postprocess_joint_spike = 'Processing introduced joint jitter.'
        bone_orientation_discontinuity = 'A limb twists abruptly between frames.'
        limb_velocity_spike_penalty = 'A limb moves abruptly between frames.'
        joint_angle_spike_penalty = 'A joint angle changes abruptly between frames.'
        bone_length_instability_penalty = 'Bone lengths change during the movement.'
        materialized_incomplete_repetition_phase = 'The generated movement does not contain a complete repetition.'
        materialized_source_endpoint_pose_mismatch = 'Poses at the movement extremes do not match the source.'
        materialized_source_pose_joint_mismatch = 'The generated joint positions do not match the source.'
        materialized_source_support_posture_mismatch = 'The lower-body posture does not match the source.'
        materialized_support_contact_contradiction = 'The generated support contacts do not match the source.'
        materialized_phase_articulation_changed = 'Processing changed the limb pose too much.'
        materialized_source_joint_angle_mismatch = 'Joint angles do not match the source.'
        materialized_output_rejected = 'The generated movement failed validation.'
        materialized_pre_render_rejected = 'The baked movement failed deterministic pre-render checks.'
        baked_motion_validation_failed = 'The baked movement failed validation before review.'
        baked_motion_too_static = 'The baked movement had too little motion to review.'
        no_baked_review_clip = 'No reviewable baked movement clip was produced.'
        controlled_motion_processing_incomplete = 'Motion fitting did not finish within the candidate budget.'
        fit_timeout = 'Motion fitting hit its time budget before a validated cycle.'
        fit_evaluation_limit = 'Motion fitting hit its evaluation limit before a validated cycle.'
        no_validated_loop_cycle = 'No validated repetition cycle was produced.'
        pre_fit_source_articulation_fidelity_failed = 'Source articulation already mismatches the reference before fitting.'
        raw_wham_motion_validation_failed = 'The raw reconstructed motion failed validation.'
        raw_wham_rigid_two_hand_spacing_instability = 'Hand spacing in the reconstruction is unstable.'
        raw_wham_kinematic_artifact = 'The raw reconstruction has kinematic artifacts.'
    }
    $informational = @('pre_wham_validated_source_interval_review',
        'post_wham_movement_cut_blocked_by_source_authority', 'loop_continuity_not_required',
        'loop_bridge_mismatch_ignored_loop_not_required', 'source_candidate_scorecard_passed',
        'source_candidate_window_choice', 'progressive_source_cut_stable_level_selection')
    $codes = @($Reasons -split ',' | ForEach-Object {
        $_.Trim() -replace '^[\s''"\[\]]+|[\s''"\[\].]+$', ''
    } | Where-Object {
        $_ -and $_ -notin $informational -and
        (-not $CodesOnly -or $_ -match '^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$')
    })
    $result = @($codes | ForEach-Object {
        if ($_ -eq 'materialized_output_rejected' -and $codes.Count -gt 1) { return }
        if ($_ -eq 'baked_motion_validation_failed' -and $codes.Count -gt 1) { return }
        if ($_ -eq 'materialized_pre_render_rejected' -and (
                $codes | Where-Object { $_ -like 'materialized_*' -and $_ -ne 'materialized_pre_render_rejected' }
            ).Count) { return }
        if ($_ -eq 'source_candidate_window_choice_failed' -and
            'source_candidate_scorecard_no_passing_candidate' -in $codes) { return }
        if ($labels.ContainsKey($_)) { $labels[$_] }
        else { "Other detail: $($_ -replace '_', ' ')" }
    } | Select-Object -Unique)
    return ($result -join '; ')
}

function ConvertTo-MotionLibraryProgress {
    param([string]$Line)
    $text = ($Line -replace '\x1b\[[0-9;]*[A-Za-z]', '').Trim()
    $attemptContext = ''
    if ($text -match '^Source attempt:' -and
        $text -match ' \| (attempt \d+/\d+ this turn) \| (candidate window [^|]+) \|') {
        $attemptContext = " | $($Matches[1]) | $($Matches[2].Trim())"
        $text = $text -replace ' \| attempt \d+/\d+ this turn \| candidate window [^|]+ \|', ' |'
    }
    if ($text -match '^Revalidation\s+\[') { return $text }
    if ($text -match '^Source attempt: (.+?) \| video (\S+) \| needs_source_review:') {
        return "Source uncertain: $($Matches[1]) | incomplete/conflicting evidence | $($Matches[2])$attemptContext"
    }
    if ($text -match '^Source attempt: (.+?) \| video (\S+) \| (source_processing_failed|rejected_vlm_timeout):') {
        return "Source processing failed: $($Matches[1]) | no verdict | $($Matches[2])$attemptContext"
    }
    if ($text -match '^Source review: (.+?) \| unresolved: source_review_incomplete$') {
        return "Source uncertain: $($Matches[1]) | needs more review"
    }
    if ($text -match '^Source review: (.+?) \| unresolved: source_processing_failed$') {
        return "Source processing failed: $($Matches[1]) | retry; no verdict"
    }
    if ($text -match '^Source attempt: (.+?) \| video (\S+) \| rejected_source_validation: (.+)$') {
        $name, $video, $detail = $Matches[1], $Matches[2], $Matches[3]
        $reason = 'interval failed validation'
        if ($detail -match 'reasons=\[(.+)\]') {
            $translated = ConvertTo-MotionLibraryReasons $Matches[1] -CodesOnly
            if ($translated) { $reason = $translated }
        }
        if ($attemptContext) {
            return "Source window rejected: $name$attemptContext | $video | $reason"
        }
        return "Source rejected: $name | $reason | $video"
    }
    if ($text -match '^Source review: (.+?) \| unresolved: no_source_passed_exact_window_validation$') {
        return "No usable source: $($Matches[1]) | no interval passed"
    }
    if ($text -match '^Source review: .+ \| deferred remaining attempts; ready movements take priority\.$') { return $null }
    if ($text -match '^Source review: (.+?) \| unresolved: source_turn_deferred$') {
        return "Source deferred: $($Matches[1]) | ready movements first"
    }
    if ($text -match '^Movement result: (.+?) \| (selected|no_selection|incomplete_processing|failed) \| ([0-9.]+)s final processing \|') {
        $name, $status, $elapsed = $Matches[1], $Matches[2], $Matches[3]
        $timingDetail = ''
        if ($text -match ' \| elapsed breakdown: ([^|]+)') {
            $timingDetail = " | $($Matches[1].Trim())"
        }
        if ($status -eq 'selected') {
            return "Movement validated: $name | ${elapsed}s$timingDetail"
        }
        $reason = 'failed final validation'
        if ($status -eq 'failed') { $reason = 'processing error' }
        if ($status -eq 'incomplete_processing') { $reason = 'fitting incomplete' }
        $reasonText = $null
        if ($text -match ' \| reasons: (.+)$') {
            $reasonText = $Matches[1]
            $translated = ConvertTo-MotionLibraryReasons $reasonText
            if ($translated) { $reason = $translated }
        }
        # Legacy no_selection lines that still carry incomplete-fit codes.
        $incompleteCodes = @(
            'controlled_motion_processing_incomplete',
            'fit_timeout',
            'fit_evaluation_limit',
            'no_validated_loop_cycle'
        )
        $looksIncomplete = $status -eq 'incomplete_processing'
        if (-not $looksIncomplete -and $status -eq 'no_selection' -and $reasonText) {
            foreach ($code in $incompleteCodes) {
                if ($reasonText -match [regex]::Escape($code)) { $looksIncomplete = $true; break }
            }
        }
        if ($looksIncomplete) {
            return "Movement incomplete: $name | ${elapsed}s$timingDetail | Reasons: $reason"
        }
        $label = if ($status -eq 'failed') { 'Movement processing failed' } else { 'Movement rejected' }
        return "$label`: $name | ${elapsed}s$timingDetail | Reasons: $reason"
    }
    if ($text -match '^(Checking source videos:|Checking sources:|Batch finished:|Batch done:|\d+/\d+ movements ready)') {
        $text = $text -replace '(\d+) failed', '$1 unresolved'
    }
    if ($text -match '^(Source review:|Source attempt:|Discovery yield requested:|Movement result:|Deferred:|WARNING:|ERROR:|Failed:|Needs review:|No suitable movement:|Could not find a source|Ctrl\+C|Motion run stopped|Stopping background)') { return $text }
    if ($text -match '^SUCCESS:') { return $text }
    if ($text -match '^Ready: (.+)$') { return "SUCCESS: $($Matches[1]) | Validated movement saved." }
    if ($text -match '^Already have a movement for (.+)\.$') { return "Reused: $($Matches[1])" }
    if ($text -match '^Preparing \d+ missing exercise motion contract') { return 'Checking contracts...' }
    if ($text -match '^(Queues:|Reviewing:|Exercise contracts:|Contracts ready:|Inference:|Generating movements for|Finding a source for|Generating:|Resuming |Starting batch|Retrying remaining|Checking source videos:|Checking sources:|Validating sources:|Source validation:|Extracting motion:|Extracting:|Motion extraction finished|Extraction done|Validating generated movements:|Validating:|Batch finished:|Batch done:|Batch |Starting motion extractor|Restarting motion extractor|Motion extractor ready|Mobile package updated:)') { return $text }
    if ($text -match '^\d+/\d+ movements ready') { return "Progress: $($text -replace ', (\d+) failed', ', $1 unresolved')" }
    return $null
}

function Write-MotionLibraryMessage {
    param([string]$Message, [switch]$NewBlock)
    if ($NewBlock) { Write-Host '' }
    Write-Host ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message)
}

function New-MotionLibraryLogState {
    return @{
        Queue = $null; Review = $null; LastStage = $null; Snapshot = $null
        LastChange = $null; LastWaiting = $null
    }
}

function Get-MotionLibraryActivityKey {
    param([string]$Activity)
    # Ignore only transient age/elapsed tokens so the same step stays one key.
    $key = "$Activity"
    $key = $key -replace ' · \d+[smhd]\b', ''
    $key = $key -replace ' for \d+[smhd]\b', ''
    $key = $key -replace ' after \d+[smhd]\.?$', ''
    $key = $key -replace ' (?:—|-) .+$', ''
    return $key.Trim().TrimEnd('.')
}

function Format-MotionLibraryProgress {
    param(
        [string]$Message, [hashtable]$State,
        [string]$Timestamp = (Get-Date -Format 'HH:mm:ss'),
        [datetime]$Now = [datetime]::UtcNow,
        [int]$QuietSeconds = 300
    )
    # Queue and review lines precede the periodic progress message in the child.
    # Buffer only those two lines so the heartbeat is printed as one block.
    if ($Message -match '^SUCCESS: (.+?)(?: \| (.+))?$') {
        $exercise, $details = $Matches[1], $Matches[2]
        $State.LastChange = $Now
        $State.LastWaiting = $null
        $State.Snapshot = $null
        ''
        '================================================================'
        "[$Timestamp] MOVEMENT GENERATED SUCCESSFULLY"
        "  Exercise: $exercise"
        if ($details) {
            foreach ($detail in ($details -split ' \| ')) { "  $detail" }
        } else {
            '  Validated movement saved.'
        }
        '================================================================'
        ''
        return
    }
    if ($Message.StartsWith('Queues:')) { $State.Queue = $Message; return }
    if ($Message.StartsWith('Reviewing:')) { $State.Review = $Message; return }
    if ($Message.StartsWith('Progress:')) {
        $text = $Message.Substring(9).Trim()
        $elapsed = ''
        if ($text -match ' after (.+)\.$') {
            $elapsed = " | Elapsed $($Matches[1])"
            $text = $text -replace ' after (.+)\.$', ''
        }
        $parts = $text -split '\. ', 2
        # The old remaining count excludes active jobs but includes completed
        # intermediate stages, so it is not a useful queue count.
        $counts = $parts[0] -replace ', \d+ remaining', ''
        $activity = if ($parts.Count -gt 1) { $parts[1] -replace '^Generating:', 'Preparing / reviewing:' } else { '' }
        $activityKey = Get-MotionLibraryActivityKey $activity
        $snapshotKey = @($counts, $State.Queue, $State.Review, $activityKey) -join "`n"
        # Same step + same queues/counts: keep quiet. Elapsed-only heartbeats are noise.
        if ($State.Snapshot -eq $snapshotKey) {
            $State.Queue = $null
            $State.Review = $null
            return
        }
        $State.Snapshot = $snapshotKey
        $State.LastChange = $Now
        $State.LastWaiting = $null
        if ($activityKey) { $State.LastStage = $activityKey }
        ''
        "[$Timestamp] Progress$elapsed"
        "  $counts"
        if ($State.Queue) {
            $queue = $State.Queue -replace '^Queues: ', ''
            $queue = $queue `
                -replace ' awaiting candidate preparation', ' prep' `
                -replace ' awaiting source review', ' review' `
                -replace ' ready for reconstruction', ' ready' `
                -replace ' reconstructing$', ' batch' `
                -replace ' active generation batch\(es\)', ' batch' `
                -replace ' \| ', ' | '
            "  Queues: $queue"
        }
        if ($State.Review) { "  $($State.Review)" }
        if ($activity) {
            "  Activity: $activity"
        }
        $State.Queue = $null
        $State.Review = $null
        return
    }
    # Per-exercise outcomes already announce source completion. Keep source
    # counters in the periodic progress block instead of printing both events.
    if ($Message.StartsWith('Checking source videos:') -or $Message.StartsWith('Checking sources:')) { return }
    $isStage = $Message -match '^(Extracting motion:|Extracting:|Validating generated movements:|Validating:|Batch finished:|Batch done:)'
    if ($Message -match '^Starting batch') {
        # Identical counters in a new batch still represent new work.
        $State.LastStage = $null
        $State.Snapshot = $null
    }
    if ($isStage) {
        # A transient latest-exercise suffix should not cause the following
        # otherwise identical heartbeat to be printed again.
        $stage = Get-MotionLibraryActivityKey $Message
        if ($State.LastStage -eq $stage) { return }
        $State.LastStage = $stage
        $State.LastChange = $Now
        $State.LastWaiting = $null
        $State.Snapshot = $null
    }
    if ($Message -match '^(SUCCESS:|Saved:|Reused:|Source (?:window rejected|uncertain|processing failed|rejected|deferred):|No usable source:|Movement validated:|Movement incomplete:|Movement rejected:|Movement processing failed:|Source review:|Source attempt:|Discovery yield requested:|Movement result:|Starting |Restarting |Deferred:|Failed:|Needs review:|No suitable movement:)') {
        $State.LastChange = $Now
        $State.LastWaiting = $null
        # Allow the next Progress snapshot to print once after an outcome event.
        $State.Snapshot = $null
    }
    # Never suppress warnings, failures, or per-exercise outcomes.
    if ($Message -match '^(SUCCESS:|Starting batch|Starting motion extractor|Restarting motion extractor|Deferred:|Failed:|WARNING:|ERROR:|Saved:|Needs review:|No suitable movement:)') {
        ''
    }
    if ($Message -match '^(Movement rejected:|Movement incomplete:|Movement processing failed:|Source window rejected:).+ \| Reasons: ') {
        $parts = $Message -split ' \| Reasons: ', 2
        "[$Timestamp] $($parts[0])"
        foreach ($reason in ($parts[1] -split '; ')) { "  - $reason" }
        return
    }
    "[$Timestamp] $Message"
}

function Invoke-MotionLibraryLoggedCommand {
    param([string]$Command, [string[]]$Arguments, [string]$LogPath, [switch]$ShowDetails)
    $writer = [System.IO.StreamWriter]::new($LogPath, $true)
    $writer.AutoFlush = $true
    $displayState = New-MotionLibraryLogState
    # stderr is diagnostic output; the native exit code decides success.
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $writer.WriteLine("[$(Get-Date -Format o)] Starting $Command")
        & $Command @Arguments 2>&1 | ForEach-Object {
            $line = "$_"
            $writer.WriteLine("[$(Get-Date -Format o)] $line")
            if ($ShowDetails -and $line -notmatch '^SUCCESS:') { Write-MotionLibraryMessage $line }
            else {
                $progress = ConvertTo-MotionLibraryProgress -Line $line
                if ($progress) { Format-MotionLibraryProgress -Message $progress -State $displayState | ForEach-Object { Write-Host $_ } }
            }
        }
        $exitCode = $LASTEXITCODE
        $writer.WriteLine("[$(Get-Date -Format o)] Exit code: $exitCode")
        if ($exitCode -eq 130) { Write-MotionLibraryMessage "Run interrupted. Saved checkpoints are available for resume." }
        elseif ($exitCode -ne 0) { Write-MotionLibraryMessage -NewBlock "WARNING: Operation exited with code $exitCode. Details: $LogPath" }
        return $exitCode
    } finally { $writer.Dispose() }
}

function Write-MotionLibraryOutcomeSummary {
    param([string]$SummaryPath)
    $summary = Get-Content -LiteralPath $SummaryPath -Raw | ConvertFrom-Json
    $items = @($summary.exercises)
    $saved = @($items | Where-Object status -eq 'completed').Count
    Write-MotionLibraryMessage -NewBlock "Movements available: $saved/$($items.Count) | Unresolved: $($items.Count - $saved)"
    foreach ($item in $items | Where-Object status -ne 'completed') {
        $label = switch ($item.status) {
            'needs_manual_review' { 'Needs review' }
            'needs_source_review' { 'Needs review' }
            'no_selection' { 'No suitable movement' }
            'failed' { 'Failed' }
            default { 'Unresolved' }
        }
        $reason = if ($item.error) { ("$($item.error)" -replace '\s+', ' ').Trim() } else { "$($item.status)".Replace('_', ' ') }
        if ($reason.Length -gt 240) { $reason = $reason.Substring(0, 237) + '...' }
        Write-MotionLibraryMessage "  $label`: $($item.exerciseName) - $reason"
    }
}
