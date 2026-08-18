[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)]
    [string]$ExerciseLibraryJson,

    [string]$EquipmentJson,

    [string]$WorkspaceRoot = "build/exercise_motion/exercise-library",

    [string]$OutputJson = "",

    [switch]$Fresh,

    [switch]$DisableCpuPrefetch,

    [switch]$SkipExistingSelectionRevalidation,

    [int]$PrefetchWorkers = 2,

    [int]$PrefetchQueueDepth = 6,

    [int]$StagedWaveSize = 8,

    [switch]$DisableStagedWaves,

    [string]$PythonCommand = "",

    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArguments = @()
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "motion_run_interrupt.ps1")
trap {
    if (
        $_.Exception -is [System.Management.Automation.PipelineStoppedException] -or
        (Test-MotionRunCancelRequested)
    ) {
        Write-MotionInterruptReceived
        exit 130
    }
    throw
}

$SelectionValidationPolicyVersion = 47
$RetainedSelectedRevalidationVersion = 3

if (-not $DisableStagedWaves -and $StagedWaveSize -lt 1) {
    throw "StagedWaveSize must be at least 1 when staged waves are enabled."
}

$runner = Join-Path $PSScriptRoot "run_exercise_motion_workout_plan.ps1"
$packageBuilder = Join-Path $PSScriptRoot "build_workout_plan_movement_package.ps1"
$resolvedLibraryJson = (Resolve-Path -LiteralPath $ExerciseLibraryJson).Path
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
if (-not $PSBoundParameters.ContainsKey("PythonCommand")) {
    & $PythonCommand -c "import sys, torch; assert torch.cuda.is_available(), f'{sys.executable} cannot see CUDA'; print(sys.executable)" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "The automatically selected exercise-motion Python cannot see CUDA: $PythonCommand"
    }
}
Write-Host "Exercise-motion Python: $PythonCommand"

if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $libraryFile = Get-Item -LiteralPath $resolvedLibraryJson
    $OutputJson = Join-Path `
        $libraryFile.DirectoryName `
        "$($libraryFile.BaseName)_with_movements$($libraryFile.Extension)"
}

New-Item -ItemType Directory -Force -Path $WorkspaceRoot | Out-Null
$resolvedWorkspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$summaryPath = Join-Path $resolvedWorkspaceRoot "workout_motion_generation_summary.json"
$firstPassSummaryPath = Join-Path $resolvedWorkspaceRoot "exercise_library_first_pass_summary.json"
$deferredPassSummaryPath = Join-Path $resolvedWorkspaceRoot "exercise_library_deferred_pass_summary.json"
$statePath = Join-Path $resolvedWorkspaceRoot "exercise_library_run_state.json"

$equipmentSignature = if ([string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) {
    "library-embedded"
} else {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedEquipmentJson).Hash
}
$runSignatureSource = @(
    (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedLibraryJson).Hash,
    $equipmentSignature,
    "$SelectionValidationPolicyVersion",
    "$RetainedSelectedRevalidationVersion",
    "$(-not $DisableCpuPrefetch)",
    "$(-not $SkipExistingSelectionRevalidation)",
    "$PrefetchWorkers",
    "$PrefetchQueueDepth",
    "$StagedWaveSize",
    "$(-not $DisableStagedWaves)",
    $PythonCommand,
    ($RemainingArguments -join "`u{001f}")
) -join "`u{001e}"
$signatureBytes = [System.Text.Encoding]::UTF8.GetBytes($runSignatureSource)
$runSignature = [Convert]::ToHexString(
    [System.Security.Cryptography.SHA256]::HashData($signatureBytes)
)

function Write-RunState {
    param(
        [string]$Phase,
        [string]$SummaryJson = ""
    )

    $counts = [ordered]@{}
    if (-not [string]::IsNullOrWhiteSpace($SummaryJson) -and (Test-Path -LiteralPath $SummaryJson)) {
        $summary = Get-Content -LiteralPath $SummaryJson -Raw | ConvertFrom-Json
        foreach ($group in @($summary.exercises | Group-Object status)) {
            $counts[$group.Name] = $group.Count
        }
    }
    $state = [ordered]@{
        schemaVersion = 1
        signature = $runSignature
        phase = $Phase
        updatedAt = (Get-Date).ToUniversalTime().ToString("o")
        sourceExerciseLibraryPath = $resolvedLibraryJson
        sourceEquipmentPath = if ([string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) { $null } else { $resolvedEquipmentJson }
        summaryPath = if ([string]::IsNullOrWhiteSpace($SummaryJson)) { $null } else { $SummaryJson }
        counts = $counts
    }
    $temporaryStatePath = "$statePath.tmp"
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryStatePath -Encoding UTF8
    Move-Item -Force -LiteralPath $temporaryStatePath -Destination $statePath
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
    if (-not [string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) {
        $runnerArguments += @("-EquipmentJson", $resolvedEquipmentJson)
    }
    if ($ReuseSelected) {
        $runnerArguments += "-ReuseExistingSelected"
    }
    if ($Fresh) {
        $runnerArguments += "-DisableStageResume"
    }
    if ($FirstPass) {
        $runnerArguments += "-DeferAfterFirstAttempt"
    }
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
            "-GpuDiscoveryBakeOverlap", "avoid",
            "-WarmWhamWorker:`$true",
            "-KeepLlamaCppServer:`$true"
        )
    }
    $runnerArguments += $RemainingArguments

    & pwsh @runnerArguments
    $passExitCode = $LASTEXITCODE
    Exit-IfMotionRunInterrupted -ExitCode $passExitCode
    if ($passExitCode -ne 0) {
        throw "Exercise-library movement pass failed with exit code $passExitCode"
    }
    if (-not (Test-Path -LiteralPath $summaryPath)) {
        throw "Movement pass did not create its summary: $summaryPath"
    }
}

function Test-ExistingSelectionRevalidationNeeded {
    $exerciseSelectionFiles = @(
        Get-ChildItem -LiteralPath $resolvedWorkspaceRoot -Directory -ErrorAction SilentlyContinue |
            ForEach-Object {
                Get-Item -LiteralPath (Join-Path $_.FullName "selected\selection_manifest.json") -ErrorAction SilentlyContinue
            }
    )
    foreach ($selectionFile in $exerciseSelectionFiles) {
        try {
            $selection = Get-Content -LiteralPath $selectionFile.FullName -Raw | ConvertFrom-Json
            $markerPath = Join-Path $selectionFile.Directory.FullName "revalidation.json"
            if (Test-Path -LiteralPath $markerPath) {
                $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
                $bakeManifestPath = Join-Path $selectionFile.Directory.Parent.FullName "bake\selection_manifest.json"
                $retainedFallbackCurrent = (
                    (Test-Path -LiteralPath $bakeManifestPath) -or
                    (
                        ($marker.PSObject.Properties.Name -contains "retainedSelectedArtifactFallbackVersion") -and
                        [int]$marker.retainedSelectedArtifactFallbackVersion -ge $RetainedSelectedRevalidationVersion
                    )
                )
                if (
                    [int]$marker.selectionValidationPolicyVersion -ge $SelectionValidationPolicyVersion -and
                    $retainedFallbackCurrent
                ) {
                    continue
                }
            }
            if (
                ($selection.PSObject.Properties.Name -contains "selectionValidationPolicyVersion") -and
                [int]$selection.selectionValidationPolicyVersion -ge $SelectionValidationPolicyVersion
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
    Write-Host "Revalidating existing selected movements under the current quality policy."
    $revalidateArguments = @(
        "-m", "exercise_motion_pkg.cli", "revalidate-library-workspace",
        "--workspace-root", $resolvedWorkspaceRoot,
        "--exercise-library-json", $resolvedLibraryJson,
        "--out-json", $reportPath
    )
    if (-not [string]::IsNullOrWhiteSpace($resolvedEquipmentJson)) {
        $revalidateArguments += @("--equipment-json", $resolvedEquipmentJson)
    }
    & $PythonCommand @revalidateArguments
    $revalidateExitCode = $LASTEXITCODE
    Exit-IfMotionRunInterrupted -ExitCode $revalidateExitCode
    if ($revalidateExitCode -ne 0) {
        throw "Existing selection revalidation failed with exit code $revalidateExitCode"
    }
    $script:CompletedRevalidationReportPath = $reportPath
}

function Write-MovementPackage {
    param([string]$MotionSummaryJson)

    & pwsh -NoProfile -File $packageBuilder `
        -WorkoutPlanPackageJson $resolvedLibraryJson `
        -MotionSummaryJson $MotionSummaryJson `
        -OutputJson $OutputJson `
        -StrictIdMatch `
        -AllowEmpty
    if ($LASTEXITCODE -ne 0) {
        throw "Exercise-library movement package creation failed with exit code $LASTEXITCODE"
    }
}

$skipFirstPass = $false
$script:CompletedRevalidationReportPath = $null
Invoke-ExistingSelectionRevalidation
if (-not [string]::IsNullOrWhiteSpace($script:CompletedRevalidationReportPath)) {
    # Publish the newly audited set before starting expensive regeneration. If the
    # run is interrupted later, the durable mobile package must not retain
    # movements that this revalidation just rejected.
    Write-MovementPackage -MotionSummaryJson $script:CompletedRevalidationReportPath
}
if (-not $Fresh -and (Test-Path -LiteralPath $statePath)) {
    try {
        $existingState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $skipFirstPass = (
            $existingState.signature -eq $runSignature -and
            $existingState.phase -in @("first_pass_completed", "deferred_pass_started", "deferred_pass_completed")
        )
    } catch {
        $skipFirstPass = $false
    }
}

if (-not $skipFirstPass) {
    Write-Host "Exercise library phase 1/2: one quality-validated candidate per unresolved definition."
    Write-RunState -Phase "first_pass_started"
    Invoke-MovementPass -FirstPass -ReuseSelected:(-not $Fresh)
    Copy-Item -Force -LiteralPath $summaryPath -Destination $firstPassSummaryPath
    $firstPassSummary = Get-Content -LiteralPath $firstPassSummaryPath -Raw | ConvertFrom-Json
    foreach ($exercise in @($firstPassSummary.exercises)) {
        if ($exercise.status -ne "completed") {
            $exercise | Add-Member -NotePropertyName firstPassStatus -NotePropertyValue $exercise.status -Force
            $exercise.status = "postponed"
        }
    }
    $firstPassSummary | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $firstPassSummaryPath -Encoding UTF8
    Write-RunState -Phase "first_pass_completed" -SummaryJson $firstPassSummaryPath
    Write-MovementPackage -MotionSummaryJson $firstPassSummaryPath
} else {
    Write-Host "Exercise library phase 1/2 already completed for these inputs; resuming deferred work."
}

Write-Host "Exercise library phase 2/2: deeper retry for definitions still without a selected movement."
Write-RunState -Phase "deferred_pass_started" -SummaryJson $firstPassSummaryPath
Invoke-MovementPass -ReuseSelected
Copy-Item -Force -LiteralPath $summaryPath -Destination $deferredPassSummaryPath
Write-MovementPackage -MotionSummaryJson $deferredPassSummaryPath
Write-RunState -Phase "deferred_pass_completed" -SummaryJson $deferredPassSummaryPath

Write-Host "Exercise library with available movements: $OutputJson"
Write-Host "Resumable run state: $statePath"
