[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)]
    [string]$ExerciseLibraryJson,

    [string]$ApprovedExerciseDefinitionsJson,

    [string]$EquipmentJson,

    [string]$WorkspaceRoot = "build/exercise_motion/exercise-library",

    [string]$OutputJson = "",

    [switch]$Fresh,

    [switch]$DisableCpuPrefetch,

    [switch]$SkipExistingSelectionRevalidation,

    [int]$PrefetchWorkers = 8,

    [int]$PrefetchQueueDepth = 40,

    [int]$StagedWaveSize = 8,

    [ValidateRange(1, 2)]
    [int]$MaxConcurrentStagedWaves = 1,

    [ValidateRange(1, 100000)]
    [int]$FirstPassCandidateBudget = 24,
    [ValidateRange(1, 86400)]
    [int]$FirstPassReviewSeconds = 300,
    [ValidateRange(1, 100000)]
    [int]$DeferredCandidateBudget = 96,
    [ValidateRange(1, 86400)]
    [int]$DeferredReviewSeconds = 900,
    [ValidateRange(1, 86400)]
    [int]$StagedWaveMaxWaitSeconds = 300,
    [ValidateRange(0, 10000)]
    [int]$MaxDeferredRounds = 0,

    # Per-exercise wall-clock budget for unattended library batches. Completed
    # library runs stay far below this (observed p90 ~4 min, max ~15 min), so it
    # only stops a pathological source pool from stalling the whole library.
    # Pass 0 to disable the bound.
    [ValidateRange(0, 86400)]
    [double]$ExerciseTimeoutSeconds = 1200.0,

    [ValidateRange(0, 86400)]
    [double]$SourceReviewTimeoutSeconds = 180.0,

    [ValidateRange(0, 10000)]
    [int]$MaxSourceWindowAttempts = 0,

    [switch]$DisableStagedWaves,

    # "auto" overlaps discovery with bake for a verified explicit GPU split;
    # otherwise CUDA stages share the GPU lock. CPU-only work can overlap.
    # Pass "allow" to explicitly overlap GPU discovery and bake stages.
    [ValidateSet("auto", "allow", "avoid")]
    [string]$GpuDiscoveryBakeOverlap = "auto",

    [ValidateRange(1, 10)]
    [int]$PassRestartAttempts = 3,

    [string]$PythonCommand = "",

    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArguments = @()
)

$ErrorActionPreference = "Stop"
$script:LibraryRunId = [guid]::NewGuid().ToString("N")
$script:LibraryRunStartedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
$script:LibraryRunOutcome = "running"
. (Join-Path $PSScriptRoot "reconstruction_compat.ps1")
. (Join-Path $PSScriptRoot "motion_run_interrupt.ps1")
. (Join-Path $PSScriptRoot "motion_library_logging.ps1")
Register-MotionInterruptHandler -Silent
trap {
    $interrupt = ($_.Exception -is [System.Management.Automation.PipelineStoppedException]) -or (Test-MotionRunCancelRequested)
    $script:LibraryRunOutcome = if ($interrupt) { "stopped" } else { "failed" }
    if (Get-Command Write-RunState -ErrorAction SilentlyContinue) {
        $summaryForOutcome = if (Get-Variable -Name summaryPath -ErrorAction SilentlyContinue) { [string]$summaryPath } else { "" }
        try { Write-RunState -Phase $script:LibraryRunOutcome -SummaryJson $summaryForOutcome -Outcome $script:LibraryRunOutcome -ErrorMessage ([string]$_.Exception.Message) } catch {}
    }
    if (
        $interrupt
    ) {
        Write-MotionInterruptReceived
        exit 130
    }
    throw $_
}

. (Join-Path $PSScriptRoot "motion_validation_policy.ps1")
$SelectionValidationPolicyVersion = Get-MotionSelectionValidationPolicyVersion
$RetainedSelectedRevalidationVersion = 14

if (-not $DisableStagedWaves -and $StagedWaveSize -lt 1) {
    throw "StagedWaveSize must be at least 1 when staged waves are enabled."
}

$runner = Join-Path $PSScriptRoot "run_exercise_motion_workout_plan.ps1"
$packageBuilder = Join-Path $PSScriptRoot "build_workout_plan_movement_package.ps1"
$resolvedLibraryJson = (Resolve-Path -LiteralPath $ExerciseLibraryJson).Path
$resolvedApprovedExerciseDefinitionsJson = $null
if (-not [string]::IsNullOrWhiteSpace($ApprovedExerciseDefinitionsJson)) {
    $resolvedApprovedExerciseDefinitionsJson = (Resolve-Path -LiteralPath $ApprovedExerciseDefinitionsJson).Path
}
$resolvedEquipmentJson = $null
if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $resolvedEquipmentJson = (Resolve-Path -LiteralPath $EquipmentJson).Path
}

function Resolve-MotionPythonCommand {
    param([string]$ConfiguredCommand)
    if (-not [string]::IsNullOrWhiteSpace($ConfiguredCommand)) {
        return $ConfiguredCommand
    }
    if (-not [string]::IsNullOrWhiteSpace($env:EXERCISE_MOTION_PYTHON)) {
        return $env:EXERCISE_MOTION_PYTHON
    }
    $cudaPython = "C:\Users\gabri\miniconda3\envs\mwa-motion-cuda\python.exe"
    if (Test-Path -LiteralPath $cudaPython) {
        return $cudaPython
    }
    return "python"
}

$PythonCommand = Resolve-MotionPythonCommand $PythonCommand
$definitionPreflightDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("exercise-motion-library-definition-preflight-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $definitionPreflightDirectory | Out-Null
$definitionPreflightListPath = Join-Path $definitionPreflightDirectory "exercise_library.json"
$definitionPreflightEffectivePlanPath = Join-Path $definitionPreflightDirectory "effective_workout_plan.json"
$definitionPreflightReportPath = Join-Path $definitionPreflightDirectory "definition_readiness_report.json"
$definitionPreflightArguments = @(
    "-m", "exercise_motion_pkg.cli", "list-workout-plan-exercises",
    "--workout-plan-json", $resolvedLibraryJson,
    "--definition-effective-plan-json", $definitionPreflightEffectivePlanPath,
    "--definition-readiness-report-json", $definitionPreflightReportPath,
    "--source-budget-workspace-root", ([System.IO.Path]::GetFullPath($WorkspaceRoot)),
    "--source-review-timeout-seconds", "$SourceReviewTimeoutSeconds",
    "--exercise-timeout-seconds", "$ExerciseTimeoutSeconds",
    "--max-source-window-attempts", "$MaxSourceWindowAttempts",
    "--out-json", $definitionPreflightListPath
)
if (-not [string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) {
    $definitionPreflightArguments += @("--equipment-json", $resolvedEquipmentJson)
}
if ($resolvedApprovedExerciseDefinitionsJson) {
    $definitionPreflightArguments += @("--approved-exercise-definitions-json", $resolvedApprovedExerciseDefinitionsJson)
}
& $PythonCommand @definitionPreflightArguments
if ($LASTEXITCODE -ne 0) {
    throw "Exercise-definition preflight failed with exit code $LASTEXITCODE. No reset, revalidation, or discovery was started."
}
$definitionExerciseList = Get-Content -LiteralPath $definitionPreflightListPath -Raw | ConvertFrom-Json
$definitionReadiness = $definitionExerciseList.definitionReadiness
$readyDefinitionExerciseSlugs = @(
    $definitionExerciseList.exercises |
        Where-Object { $_.definitionReadiness.status -eq "ready" } |
        ForEach-Object { [string]$_.slug } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -Unique
)
$readyDefinitionExerciseCount = $readyDefinitionExerciseSlugs.Count
$readySourceReviewExerciseCount = @(
    $definitionExerciseList.exercises |
        Where-Object { $_.definitionReadiness.status -eq "ready" -and $_.sourceReviewBudgetReadiness.ready -eq $true }
).Count
$definitionEffectivePlanSha256 = (Get-FileHash -LiteralPath $definitionPreflightEffectivePlanPath -Algorithm SHA256).Hash
if (-not $PSBoundParameters.ContainsKey("PythonCommand") -and $readySourceReviewExerciseCount -gt 0) {
    & $PythonCommand -c "import sys, torch; assert torch.cuda.is_available(), f'{sys.executable} cannot see CUDA'; print(sys.executable)" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "The automatically selected exercise-motion Python cannot see CUDA: $PythonCommand"
    }
}
Write-Verbose "Exercise-motion Python: $PythonCommand"

if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $libraryFile = Get-Item -LiteralPath $resolvedLibraryJson
    $OutputJson = Join-Path `
        $libraryFile.DirectoryName `
        "$($libraryFile.BaseName)_with_movements$($libraryFile.Extension)"
}

New-Item -ItemType Directory -Force -Path $WorkspaceRoot | Out-Null
$resolvedWorkspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$definitionEffectivePlanPath = Join-Path $resolvedWorkspaceRoot "effective_workout_plan.json"
$definitionReadinessReportPath = Join-Path $resolvedWorkspaceRoot "definition_readiness_report.json"
Copy-Item -LiteralPath $definitionPreflightEffectivePlanPath -Destination $definitionEffectivePlanPath -Force
$definitionEffectivePlanSha256 = (Get-FileHash -LiteralPath $definitionEffectivePlanPath -Algorithm SHA256).Hash
$definitionReadiness | Add-Member -NotePropertyName effectivePlanPath -NotePropertyValue $definitionEffectivePlanPath -Force
$definitionReadiness | Add-Member -NotePropertyName effectivePlanSha256 -NotePropertyValue $definitionEffectivePlanSha256 -Force
$definitionReadiness | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $definitionReadinessReportPath -Encoding UTF8
foreach ($preflightArtifactPath in @($definitionPreflightListPath, $definitionPreflightEffectivePlanPath, $definitionPreflightReportPath)) {
    Remove-Item -LiteralPath $preflightArtifactPath -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $definitionPreflightDirectory -Force -ErrorAction SilentlyContinue
$summaryPath = Join-Path $resolvedWorkspaceRoot "workout_motion_generation_summary.json"
$firstPassSummaryPath = Join-Path $resolvedWorkspaceRoot "exercise_library_first_pass_summary.json"
$deferredPassSummaryPath = Join-Path $resolvedWorkspaceRoot "exercise_library_deferred_pass_summary.json"
$statePath = Join-Path $resolvedWorkspaceRoot "exercise_library_run_state.json"
$runStartedAt = Get-Date
$logDirectory = Join-Path $resolvedWorkspaceRoot "logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$diagnosticLogPath = Join-Path $logDirectory ("library-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$showDetailedOutput = $VerbosePreference -eq 'Continue'
Write-MotionLibraryMessage -NewBlock "Movement generation"
Write-MotionLibraryMessage ("Mode: {0} | Reuse valid cached exercise contracts" -f $(if ($Fresh) { 'regenerate movements' } else { 'resume available work' }))
Write-MotionLibraryMessage "Library: $resolvedLibraryJson"
Write-MotionLibraryMessage "Output: $OutputJson"
Write-MotionLibraryMessage "Detailed log: $diagnosticLogPath"
$resumeArguments = @('-ExerciseLibraryJson', $resolvedLibraryJson, '-WorkspaceRoot', $resolvedWorkspaceRoot, '-OutputJson', $OutputJson)
foreach ($parameter in $PSBoundParameters.GetEnumerator()) {
    if ($parameter.Key -in @('Fresh', 'ExerciseLibraryJson', 'WorkspaceRoot', 'OutputJson', 'RemainingArguments', 'Verbose')) { continue }
    if ($parameter.Value -is [System.Management.Automation.SwitchParameter]) {
        if ($parameter.Value.IsPresent) { $resumeArguments += "-$($parameter.Key)" }
    } else { $resumeArguments += @("-$($parameter.Key)", "$($parameter.Value)") }
}
$resumeArguments += $RemainingArguments
$resumeCommand = "pwsh ./scripts/run_exercise_motion_library.ps1 " + (($resumeArguments | ForEach-Object { "'" + ("$_".Replace("'", "''")) + "'" }) -join ' ')
Write-MotionLibraryMessage "Resume after an interruption: $resumeCommand"


$equipmentSignature = if ([string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) {
    "library-embedded"
} else {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedEquipmentJson).Hash
}
$sourceLibrarySha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedLibraryJson).Hash
$approvedDefinitionsSha256 = if ($resolvedApprovedExerciseDefinitionsJson) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedApprovedExerciseDefinitionsJson).Hash
} else { "none" }
$equipmentInputSha256 = if ([string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) { "none" } else { $equipmentSignature }
$libraryInputIdentityBytes = [System.Text.Encoding]::UTF8.GetBytes("$sourceLibrarySha256`n$approvedDefinitionsSha256`n$definitionEffectivePlanSha256`n$equipmentInputSha256")
$libraryInputIdentitySha256 = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($libraryInputIdentityBytes))
$runSignatureSource = @(
    $sourceLibrarySha256,
    $approvedDefinitionsSha256,
    $definitionEffectivePlanSha256,
    $equipmentSignature,
    "$SelectionValidationPolicyVersion",
    "$RetainedSelectedRevalidationVersion",
    "$(-not $DisableCpuPrefetch)",
    "$(-not $SkipExistingSelectionRevalidation)",
    "$PrefetchWorkers",
    "$PrefetchQueueDepth",
    "$StagedWaveSize",
    "$MaxConcurrentStagedWaves",
    "discovery-turns-v1",
    "$FirstPassCandidateBudget", "$FirstPassReviewSeconds",
    "$DeferredCandidateBudget", "$DeferredReviewSeconds", "$StagedWaveMaxWaitSeconds",
    "$(-not $DisableStagedWaves)",
    $PythonCommand,
    ($RemainingArguments -join "`u{001f}")
) -join "`u{001e}"
$signatureBytes = [System.Text.Encoding]::UTF8.GetBytes($runSignatureSource)
$runSignature = [Convert]::ToHexString(
    [System.Security.Cryptography.SHA256]::HashData($signatureBytes)
)

function Write-AtomicJson {
    param([string]$Path, [object]$Value, [int]$Depth = 16)
    $temporaryPath = "$Path.$script:LibraryRunId.tmp"
    $Value | ConvertTo-Json -Depth $Depth | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -Force -LiteralPath $temporaryPath -Destination $Path
}

function Write-RunState {
    param(
        [string]$Phase,
        [string]$SummaryJson = "",
        [string]$Outcome = $script:LibraryRunOutcome,
        [string]$ErrorMessage = ""
    )

    if (-not $script:LibraryStateInitialized -and (Test-Path -LiteralPath $statePath)) {
        $priorStateHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $statePath).Hash.Substring(0, 12)
        $priorStateTime = (Get-Item -LiteralPath $statePath).LastWriteTimeUtc.ToString("yyyyMMddTHHmmssZ")
        $priorStateArchive = "$statePath.previous-$priorStateTime-$priorStateHash.json"
        $archiveIndex = 1
        while (Test-Path -LiteralPath $priorStateArchive) {
            $priorStateArchive = "$statePath.previous-$priorStateTime-$priorStateHash-$archiveIndex.json"
            $archiveIndex += 1
        }
        Copy-Item -LiteralPath $statePath -Destination $priorStateArchive
    }
    $script:LibraryStateInitialized = $true

    $counts = [ordered]@{}
    if (-not [string]::IsNullOrWhiteSpace($SummaryJson) -and (Test-Path -LiteralPath $SummaryJson)) {
        try {
            $summary = Get-Content -LiteralPath $SummaryJson -Raw | ConvertFrom-ReconstructionJson
            if ($summary.libraryRunId -eq $script:LibraryRunId -and $summary.inputIdentitySha256 -eq $libraryInputIdentitySha256) {
                foreach ($group in @($summary.exercises | Group-Object status)) { $counts[$group.Name] = $group.Count }
            }
        } catch { }
    }
    $terminalCount = 0
    foreach ($statusName in $counts.Keys) {
        if ($statusName -ne "postponed") { $terminalCount += [int]$counts[$statusName] }
    }
    $totalCount = 0
    try { $library = Get-Content -LiteralPath $resolvedLibraryJson -Raw | ConvertFrom-ReconstructionJson; $totalCount = @($library.exercises).Count } catch { }
    $state = [ordered]@{
        schemaVersion = 2
        runId = $script:LibraryRunId
        signature = $runSignature
        inputIdentitySha256 = $libraryInputIdentitySha256
        approvedDefinitionsSha256 = $approvedDefinitionsSha256
        effectiveDefinitionPlanSha256 = $definitionEffectivePlanSha256
        outcome = $Outcome
        startedAtUtc = $script:LibraryRunStartedAtUtc
        completedAtUtc = if ($Outcome -eq "completed") { (Get-Date).ToUniversalTime().ToString("o") } else { $null }
        stoppedAtUtc = if ($Outcome -eq "stopped") { (Get-Date).ToUniversalTime().ToString("o") } else { $null }
        failedAtUtc = if ($Outcome -eq "failed") { (Get-Date).ToUniversalTime().ToString("o") } else { $null }
        phase = $Phase
        updatedAt = (Get-Date).ToUniversalTime().ToString("o")
        sourceExerciseLibraryPath = $resolvedLibraryJson
        sourceEquipmentPath = if ([string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) { $null } else { $resolvedEquipmentJson }
        summaryPath = if ([string]::IsNullOrWhiteSpace($SummaryJson)) { $null } else { $SummaryJson }
        totalExerciseCount = $totalCount
        terminalExerciseCount = $terminalCount
        pendingExerciseCount = [Math]::Max(0, $totalCount - $terminalCount)
        counts = $counts
        errorMessage = if ([string]::IsNullOrWhiteSpace($ErrorMessage)) { $null } else { $ErrorMessage }
    }
    Write-AtomicJson -Path $statePath -Value $state
}

function Exit-IfLibraryRunInterrupted {
    param([int]$ExitCode = $LASTEXITCODE)
    if ((Test-MotionRunCancelRequested) -or $ExitCode -eq 130) {
        $script:LibraryRunOutcome = "stopped"
        $summaryForOutcome = if (Test-Path -LiteralPath $summaryPath) { $summaryPath } else { "" }
        Write-RunState -Phase "stopped" -SummaryJson $summaryForOutcome -Outcome "stopped"
        Exit-IfMotionRunInterrupted -ExitCode $ExitCode
    }
}

function Invoke-MovementPass {
    param(
        [switch]$FirstPass,
        [switch]$ReuseSelected
    )

    $runnerArguments = @(
        "-NoProfile",
        "-File", $runner,
        "-WorkoutPlanJson", $resolvedLibraryJson,
        "-WorkspaceRoot", $resolvedWorkspaceRoot
        "-IncrementalMobilePackageOutputJson", $OutputJson
        "-PythonCommand", $PythonCommand
    )
    $passRunId = [guid]::NewGuid().ToString("N")
    $runnerArguments += @("-InvocationRunId", $passRunId, "-LibraryRunId", $script:LibraryRunId)
    if (-not [string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) {
        $runnerArguments += @("-EquipmentJson", $resolvedEquipmentJson)
    }
    if ($resolvedApprovedExerciseDefinitionsJson) {
        $runnerArguments += @("-ApprovedExerciseDefinitionsJson", $resolvedApprovedExerciseDefinitionsJson)
    }
    $runnerArguments += @("-InputIdentitySha256", $libraryInputIdentitySha256)
    if ($ReuseSelected) {
        $runnerArguments += "-ReuseExistingSelected"
    }
    # Reuse selected movements, but unresolved discovery must advance on each turn.
    # Per-batch review checkpoints are independent of whole-stage resume.
    if ($Fresh -or -not $FirstPass) { $runnerArguments += "-DisableStageResume" }
    $runnerArguments += "-DeferAfterFirstAttempt"
    $candidateBudget = if ($FirstPass) { $FirstPassCandidateBudget } else { $DeferredCandidateBudget }
    $reviewSeconds = if ($FirstPass) { $FirstPassReviewSeconds } else { $DeferredReviewSeconds }
    $runnerArguments += @('-DiscoveryCandidateBudget', "$candidateBudget",
        '-DiscoveryTimeBudgetSeconds', "$reviewSeconds", '-StagedWaveMaxWaitSeconds', "$StagedWaveMaxWaitSeconds")
    if ($ExerciseTimeoutSeconds -gt 0) {
        $runnerArguments += @('-ExerciseTimeoutSeconds', "$ExerciseTimeoutSeconds")
    }
    $runnerArguments += @('-SourceReviewTimeoutSeconds', "$SourceReviewTimeoutSeconds",
        '-MaxSourceWindowAttempts', "$MaxSourceWindowAttempts")
    Write-MotionLibraryMessage "Discovery turn: up to $candidateBudget new candidates or $reviewSeconds seconds of review; finish the active batch before yielding."
    if (-not $DisableCpuPrefetch) {
        $runnerArguments += @(
            "-CpuPrefetchDuringBake",
            "-PrefetchWorkers", "$PrefetchWorkers",
            "-PrefetchQueueDepth", "$PrefetchQueueDepth"
        )
    }
    if (-not $DisableStagedWaves) {
        $runnerArguments += @(
            "-StagedWaveSize", "$StagedWaveSize",
            "-MaxConcurrentStagedWaves", "$MaxConcurrentStagedWaves",
            "-GpuDiscoveryBakeOverlap", $GpuDiscoveryBakeOverlap,
            "-WarmGvhmrWorker:`$true",
            "-KeepLlamaCppServer:`$true"
        )
    }
    $exclusiveGpuIndex = 0
    $hasExclusiveGpuLane = [int]::TryParse(
        "$env:EXERCISE_MOTION_EXCLUSIVE_GPU_DEVICE", [ref]$exclusiveGpuIndex
    ) -and $exclusiveGpuIndex -gt 0
    if (-not $DisableStagedWaves -and ($MaxConcurrentStagedWaves -gt 1 -or $hasExclusiveGpuLane)) {
        $runnerArguments += "-SharedLlamaServer"
    }
    $runnerArguments += $RemainingArguments

    for ($restartAttempt = 1; $restartAttempt -le $PassRestartAttempts; $restartAttempt += 1) {
        $passExitCode = Invoke-MotionLibraryLoggedCommand -Command pwsh -Arguments $runnerArguments -LogPath $diagnosticLogPath -ShowDetails:$showDetailedOutput
        Exit-IfLibraryRunInterrupted -ExitCode $passExitCode
        if ($passExitCode -eq 75) {
            Write-MotionLibraryMessage "Movement generation stopped: insufficient storage. Free space and resume; automatic retries are suspended."
            $script:LibraryRunOutcome = "stopped"
            Write-RunState -Phase "stopped" -Outcome "stopped" -ErrorMessage "Insufficient storage (exit code 75)."
            exit 75
        }
        if ($passExitCode -eq 0 -and (Test-Path -LiteralPath $summaryPath)) {
            try { $passSummary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-ReconstructionJson } catch { $passSummary = $null }
            if ($passSummary -and
                $passSummary.runId -eq $passRunId -and
                $passSummary.libraryRunId -eq $script:LibraryRunId -and
                $passSummary.inputIdentitySha256 -eq $libraryInputIdentitySha256 -and
                $passSummary.approvedDefinitionsSha256 -eq $approvedDefinitionsSha256 -and
                $passSummary.effectiveDefinitionPlanSha256 -eq $definitionEffectivePlanSha256) {
                return
            }
            throw "Exercise-library pass exited successfully but its summary does not match this pass ID and input identity; refusing to consume stale output at $summaryPath."
        }

        $failure = if ($passExitCode -ne 0) {
            "failed with exit code $passExitCode"
        } else {
            "finished without creating its summary: $summaryPath"
        }
        if ($restartAttempt -ge $PassRestartAttempts) {
            throw "Exercise-library movement pass $failure after $PassRestartAttempts automatic attempt(s)."
        }
        Write-MotionLibraryMessage -NewBlock ((
                "WARNING: Exercise-library movement pass {0}; restarting from its persisted checkpoint " +
                "(attempt {1}/{2})."
            ) -f $failure, ($restartAttempt + 1), $PassRestartAttempts)
        Start-Sleep -Seconds 5
    }
}

function Test-ExistingSelectionRevalidationNeeded {
    # A library run can outlive edits to the validation code, so the policy
    # version cached at script start may lag the code that is about to reuse
    # the selections. Read the authoritative version fresh for every check.
    $currentPolicyVersion = Get-MotionSelectionValidationPolicyVersion
    $exerciseSelectionFiles = @(
        Get-ChildItem -LiteralPath $resolvedWorkspaceRoot -Directory -ErrorAction SilentlyContinue |
            ForEach-Object {
                Get-Item -LiteralPath (Join-Path $_.FullName "selected\selection_manifest.json") -ErrorAction SilentlyContinue
            }
    )
    foreach ($selectionFile in $exerciseSelectionFiles) {
        try {
            $selection = Get-Content -LiteralPath $selectionFile.FullName -Raw | ConvertFrom-ReconstructionJson
            $markerPath = Join-Path $selectionFile.Directory.FullName "revalidation.json"
            if (Test-Path -LiteralPath $markerPath) {
                $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-ReconstructionJson
                if (@($marker.reasons) -contains 'final_output_validation_no_frames') {
                    return $true
                }
                if (($marker.PSObject.Properties.Name -contains 'selectedManifestSha256') -and
                    $marker.selectedManifestSha256 -ne (Get-FileHash -LiteralPath $selectionFile.FullName -Algorithm SHA256).Hash) {
                    return $true
                }
                $bakeManifestPath = Join-Path $selectionFile.Directory.Parent.FullName "bake\selection_manifest.json"
                $retainedFallbackCurrent = (
                    (Test-Path -LiteralPath $bakeManifestPath) -or
                    (
                        ($marker.PSObject.Properties.Name -contains "retainedSelectedArtifactFallbackVersion") -and
                        [int]$marker.retainedSelectedArtifactFallbackVersion -ge $RetainedSelectedRevalidationVersion
                    )
                )
                if (
                    [int]$marker.selectionValidationPolicyVersion -ge $currentPolicyVersion -and
                    $retainedFallbackCurrent
                ) {
                    continue
                }
            }
            if (
                ($selection.PSObject.Properties.Name -contains "selectionValidationPolicyVersion") -and
                [int]$selection.selectionValidationPolicyVersion -ge $currentPolicyVersion
            ) {
                continue
            }
            return $true
        } catch {
            return $true
        }
    }
    return $false
}

function Invoke-ExistingSelectionRevalidation {
    if ($Fresh -or $SkipExistingSelectionRevalidation -or -not (Test-ExistingSelectionRevalidationNeeded)) {
        return
    }
    $reportPath = Join-Path $resolvedWorkspaceRoot "exercise_library_revalidation_report.json"
    Write-MotionLibraryMessage "Revalidating existing selected movements under the current quality policy."
    $revalidateArguments = @(
        "-m", "exercise_motion_pkg.cli", "revalidate-library-workspace",
        "--workspace-root", $resolvedWorkspaceRoot,
        "--exercise-library-json", $definitionEffectivePlanPath,
        "--out-json", $reportPath
    )
    if (-not [string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) {
        $revalidateArguments += @("--equipment-json", $resolvedEquipmentJson)
    }
    foreach ($exerciseSlug in $readyDefinitionExerciseSlugs) {
        $revalidateArguments += @("--only-exercise-slug", $exerciseSlug)
    }
    $revalidateExitCode = Invoke-MotionLibraryLoggedCommand -Command $PythonCommand -Arguments $revalidateArguments -LogPath $diagnosticLogPath -ShowDetails:$showDetailedOutput
    Exit-IfLibraryRunInterrupted -ExitCode $revalidateExitCode
    if ($revalidateExitCode -ne 0) {
        throw "Existing selection revalidation failed with exit code $revalidateExitCode"
    }
    $script:CompletedRevalidationReportPath = $reportPath
}

function Invoke-PassBoundaryRevalidation {
    # Each movement pass reloads the Python validation code, and a long run can
    # outlive edits to that code. Check at every pass boundary whether retained
    # selections lag the current policy (Test-ExistingSelectionRevalidationNeeded
    # reads the authoritative version fresh) so the boundary re-audits them
    # under the current policy instead of letting the next pass silently
    # discard selections the previous pass published.
    $script:CompletedRevalidationReportPath = $null
    Invoke-ExistingSelectionRevalidation
    if (-not [string]::IsNullOrWhiteSpace($script:CompletedRevalidationReportPath)) {
        # Publish the newly audited set before starting expensive regeneration. If the
        # run is interrupted later, the durable mobile package must not retain
        # movements that this revalidation just rejected.
        Write-MovementPackage -MotionSummaryJson $script:CompletedRevalidationReportPath
    }
}

function Write-MovementPackage {
    param([string]$MotionSummaryJson)

    $packageArguments = @('-NoProfile', '-File', $packageBuilder,
        '-WorkoutPlanPackageJson', $resolvedLibraryJson, '-MotionSummaryJson', $MotionSummaryJson,
        '-OutputJson', $OutputJson, '-StrictIdMatch', '-AllowEmpty')
    $packageExitCode = Invoke-MotionLibraryLoggedCommand -Command pwsh -Arguments $packageArguments -LogPath $diagnosticLogPath -ShowDetails:$showDetailedOutput
    Exit-IfLibraryRunInterrupted -ExitCode $packageExitCode
    if ($packageExitCode -ne 0) {
        throw "Movement package creation failed with exit code $packageExitCode. Details: $diagnosticLogPath"
    }

}

$skipFirstPass = $false
if ($readyDefinitionExerciseCount -gt 0) {
    # Discovery owns policy/input invalidation; resuming must preserve its verdicts.
    Invoke-PassBoundaryRevalidation
} else {
    Write-MotionLibraryMessage "Definition preflight found no ready targets; skipping retained-selection revalidation."
}
if (-not $Fresh -and (Test-Path -LiteralPath $statePath)) {
    try {
        $existingState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-ReconstructionJson
        $skipFirstPass = (
            $existingState.signature -eq $runSignature -and
            $existingState.phase -in @("first_pass_completed", "deferred_pass_started", "deferred_pass_completed")
        )
    } catch {
        $skipFirstPass = $false
    }
}
if ($readyDefinitionExerciseCount -eq 0) { $skipFirstPass = $false }
Write-RunState -Phase "initialized" -Outcome "running"

if (-not $skipFirstPass) {
    Write-MotionLibraryMessage -NewBlock "Pass 1/2: try one candidate for each exercise; revisit unresolved exercises in pass 2."
    Write-RunState -Phase "first_pass_started"
    Invoke-MovementPass -FirstPass -ReuseSelected:(-not $Fresh)
    Copy-Item -Force -LiteralPath $summaryPath -Destination $firstPassSummaryPath
    $firstPassSummary = Get-Content -LiteralPath $firstPassSummaryPath -Raw | ConvertFrom-ReconstructionJson
    foreach ($exercise in @($firstPassSummary.exercises)) {
        if ($exercise.status -notin @("completed", "needs_definition_review")) {
            $exercise | Add-Member -NotePropertyName firstPassStatus -NotePropertyValue $exercise.status -Force
            $exercise.status = "postponed"
        }
    }
    $firstPassSummary | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $firstPassSummaryPath -Encoding UTF8
    Write-RunState -Phase "first_pass_completed" -SummaryJson $firstPassSummaryPath -Outcome "running"
    Write-MovementPackage -MotionSummaryJson $firstPassSummaryPath
    if ($readyDefinitionExerciseCount -eq 0) {
        Copy-Item -Force -LiteralPath $firstPassSummaryPath -Destination $deferredPassSummaryPath
        Write-RunState -Phase "deferred_pass_completed" -SummaryJson $deferredPassSummaryPath -Outcome "running"
    }
} else {
    Write-MotionLibraryMessage "Exercise library phase 1/2 already completed for these inputs; resuming deferred work."
}

function Get-DiscoveryReviewCount {
    $count = 0
    foreach ($directory in Get-ChildItem -LiteralPath $resolvedWorkspaceRoot -Directory) {
        foreach ($file in Get-ChildItem -LiteralPath $directory.FullName -Filter 'discovery_review_*.json' -File) {
            try {
                $checkpoint = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-ReconstructionJson
                $count += @($checkpoint.reviewed.PSObject.Properties).Count
            } catch { Write-Verbose "Cannot read discovery checkpoint $($file.FullName)." }
        }
    }
    return $count
}
function Get-SourceTurnResumeSignature {
    $entries = foreach ($directory in Get-ChildItem -LiteralPath $resolvedWorkspaceRoot -Directory) {
        $cursorPath = Join-Path $directory.FullName 'bake/source_turn_resume.json'
        if (Test-Path -LiteralPath $cursorPath) {
            "$($directory.Name):$((Get-FileHash -LiteralPath $cursorPath -Algorithm SHA256).Hash)"
        }
    }
    return (($entries | Sort-Object) -join '|')
}

$round = 0
while ($readyDefinitionExerciseCount -gt 0) {
    $round += 1
    $beforeReviewCount = Get-DiscoveryReviewCount
    $beforeSourceTurnSignature = Get-SourceTurnResumeSignature
    Write-MotionLibraryMessage -NewBlock "Pass 2 - round $round`: finish retained processing and advance source cursors; larger discovery turns for cold unresolved exercises; reuse movements already saved."
    Invoke-PassBoundaryRevalidation
    Write-RunState -Phase "deferred_pass_started" -SummaryJson $firstPassSummaryPath
    Invoke-MovementPass -ReuseSelected
    Copy-Item -Force -LiteralPath $summaryPath -Destination $deferredPassSummaryPath
    Write-MovementPackage -MotionSummaryJson $deferredPassSummaryPath
    Write-RunState -Phase "deferred_pass_completed" -SummaryJson $deferredPassSummaryPath -Outcome "running"
    $roundSummary = Get-Content -LiteralPath $deferredPassSummaryPath -Raw | ConvertFrom-ReconstructionJson
    $unresolved = @($roundSummary.exercises | Where-Object status -ne 'completed').Count
    $newReviews = (Get-DiscoveryReviewCount) - $beforeReviewCount
    $pendingSourceTurns = @(Get-ChildItem -LiteralPath $resolvedWorkspaceRoot -Directory | Where-Object {
        Test-Path -LiteralPath (Join-Path $_.FullName 'bake/source_turn_resume.json')
    }).Count
    Write-MotionLibraryMessage -NewBlock "Round $round finished: $newReviews new candidate reviews | $unresolved unresolved exercises."
    if ($unresolved -eq 0) { break }
    $sourceTurnsAdvanced = $beforeSourceTurnSignature -ne (Get-SourceTurnResumeSignature)
    if ($newReviews -le 0 -and ($pendingSourceTurns -eq 0 -or -not $sourceTurnsAdvanced)) {
        Write-MotionLibraryMessage 'Stopping automatic rounds: no new candidate reviews completed. Unresolved exercises remain available for resume; check their logs for search or runtime failures.'
        break
    }
    if ($MaxDeferredRounds -gt 0 -and $round -ge $MaxDeferredRounds) { break }
}

Write-MotionLibraryMessage -NewBlock "Exercise library with available movements: $OutputJson"
Write-MotionLibraryOutcomeSummary -SummaryPath $deferredPassSummaryPath
Write-MotionLibraryMessage ("Elapsed: {0:hh\:mm\:ss}" -f ((Get-Date) - $runStartedAt))
Write-MotionLibraryMessage "Detailed log: $diagnosticLogPath"
Write-MotionLibraryMessage "Resume unresolved work: $resumeCommand"
Write-RunState -Phase "invocation_completed" -SummaryJson $deferredPassSummaryPath -Outcome "completed"
$script:LibraryRunOutcome = "completed"
