param(
    [Parameter(Mandatory = $true)]
    [string]$WorkoutPlanJson,

    [string]$WorkspaceRoot = "build/exercise_motion/workout-plan",
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [string]$PythonCommand = "python",
    [int]$ResultsPerQuery = 10,
    [int]$MaxCandidates = 8,
    [int]$MetadataCandidatePoolSize = 24,
    [switch]$UseDeepSeekQueryPlanner,
    [string]$DeepSeekApiKey,
    [string]$DeepSeekBaseUrl = "https://api.deepseek.com",
    [string]$DeepSeekModel = "deepseek-v4-flash",
    [int]$DeepSeekMaxQueries = 4,
    [int]$VisionCandidatesPerExercise = 8,
    [int]$VisionFramesPerCandidate = 6,
    [int]$VisionMaxChunksPerCandidate = 5,
    [int]$VisionDownloadWorkers = 3,
    [int]$VisionLlmWorkers = 1,
    [int]$ExerciseWorkers = 2,
    [int]$FallbackCandidates = 3,
    [switch]$IncludeDisabled,
    [switch]$NoWhamDocker,
    [string]$WhamDockerImage = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "8g",
    [switch]$FullWhamCameraSlam,
    [switch]$SkipSmplify,
    [switch]$SkipMotionTuning,
    [switch]$SkipSourceSegmentDetection,
    [string]$SegmentBaseUrl,
    [string]$SegmentModel,
    [Nullable[double]]$SegmentWindowSeconds,
    [Nullable[double]]$SegmentOverlapSeconds,
    [Nullable[int]]$SegmentFramesPerWindow,
    [double]$SegmentConfidenceThreshold = 0.45,
    [double]$SegmentPaddingSeconds = 0.35,
    [double]$SegmentEndPaddingSeconds = 0.35,
    [double]$SegmentMinSeconds = 2.0,
    [double]$SegmentMaxSeconds = 20.0,
    [int]$SegmentClassificationWorkers = 3,
    [switch]$RankPreviewVariants,
    [switch]$SkipPreviewVariantRanking,
    [switch]$SkipSupportDominanceClassification,
    [int]$ReviewFrames = 6,
    [int]$MaxReviewWindows = 3,
    [double]$MinSelectedScore = 0.55,
    [double]$LlamaCppRequestTimeoutSeconds = 90.0,
    [int]$ProgressIntervalSeconds = 15
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function ConvertTo-Slug {
    param([string]$Value)
    $slug = $Value.ToLowerInvariant() -replace "[^a-z0-9]+", "-"
    $slug = $slug.Trim("-")
    if ([string]::IsNullOrWhiteSpace($slug)) {
        return "exercise"
    }
    return $slug
}

function Invoke-PythonModule {
    param([string[]]$Arguments)
    & $PythonCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "python command failed with exit code $LASTEXITCODE."
    }
}

function New-ExerciseCandidateManifest {
    param(
        [object]$Exercise,
        [string]$OutPath
    )
    $manifest = [ordered]@{
        schemaVersion = 1
        sourcePlanPath = $resolvedWorkoutPlanJson
        generatedAt = (Get-Date).ToUniversalTime().ToString("o")
        ranking = $candidateManifest.ranking
        exercises = @($Exercise)
    }
    $manifest | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $OutPath -Encoding UTF8
}

function Start-BakeJob {
    param([object]$WorkItem)

    Write-Host "Starting movement generation for '$($WorkItem.exerciseName)'."
    $job = Start-Job -Name $WorkItem.exerciseSlug -ScriptBlock {
        param(
            [string]$PythonCommand,
            [string[]]$Arguments,
            [string]$LogPath
        )

        $ErrorActionPreference = "Continue"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
        & $PythonCommand @Arguments *> $LogPath
        [pscustomobject]@{
            exitCode = $LASTEXITCODE
            logPath = $LogPath
        }
    } -ArgumentList $PythonCommand, ([string[]]$WorkItem.bakeArgs), $WorkItem.logPath
    $job | Add-Member -MemberType NoteProperty -Name WorkItem -Value $WorkItem
    return $job
}

function Complete-BakeJob {
    param([object]$Job)

    $workItem = $Job.WorkItem
    $status = "completed"
    $errorMessage = $null
    $jobResult = $null

    try {
        $received = @(Receive-Job -Job $Job -Wait -ErrorAction Stop)
        if ($received.Count -gt 0) {
            $jobResult = $received[-1]
        }
    } catch {
        $status = "failed"
        $errorMessage = $_.Exception.Message
    } finally {
        Remove-Job -Job $Job -Force
    }

    if ($status -eq "completed" -and (-not $jobResult -or $jobResult.exitCode -ne 0)) {
        $status = "failed"
        $exitCode = if ($jobResult) { $jobResult.exitCode } else { "unknown" }
        $errorMessage = "python command failed with exit code $exitCode. See log: $($workItem.logPath)"
    }

    if ($status -eq "failed") {
        Write-Warning "Movement generation failed for '$($workItem.exerciseName)': $errorMessage"
    }

    $selectionPath = Join-Path $workItem.bakeWorkspace "selection_manifest.json"
    $selection = $null
    if (Test-Path -LiteralPath $selectionPath) {
        $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-Json
    }
    $selected = if ($selection -and $selection.selected) { $selection.selected } else { $null }
    if ($status -eq "completed" -and -not $selected) {
        $status = "no_selection"
        $errorMessage = "No Wear skeleton was selected."
    }

    Write-Host "[$status] $($workItem.exerciseName)"
    if ($selected -and $selected.selectedWearSkeletonPath) {
        Write-Host "  Wear skeleton JSON: $($selected.selectedWearSkeletonPath)"
    }
    if ($selection -and $selection.selectedPreviewHtmlPath) {
        Write-Host "  Preview HTML: $($selection.selectedPreviewHtmlPath)"
    }

    return [ordered]@{
        exerciseId = $workItem.exerciseId
        exerciseName = $workItem.exerciseName
        status = $status
        error = $errorMessage
        candidateCount = $workItem.candidateCount
        candidatesJsonPath = $workItem.exerciseCandidatesPath
        selectionManifestPath = $selectionPath
        logPath = $workItem.logPath
        selectedWearSkeletonPath = if ($selected) { $selected.selectedWearSkeletonPath } else { $null }
        selectedPreviewHtmlPath = if ($selection) { $selection.selectedPreviewHtmlPath } else { $null }
        selectedSourceVideoPath = if ($selected) { $selected.copiedInputVideoPath } else { $null }
    }
}

function Get-LatestLogLine {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $lines = @(Get-Content -LiteralPath $Path -Tail 20 -ErrorAction SilentlyContinue)
    for ($index = $lines.Count - 1; $index -ge 0; $index -= 1) {
        $line = [string]$lines[$index]
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            return $line.Trim()
        }
    }
    return $null
}

function Write-ProgressSnapshot {
    param(
        [object[]]$RunningJobs,
        [int]$CompletedCount,
        [int]$TotalCount,
        [int]$PendingCount
    )

    $activeNames = @($RunningJobs | ForEach-Object { $_.WorkItem.exerciseName })
    Write-Host ("Progress: {0}/{1} finished, {2} running, {3} queued." -f $CompletedCount, $TotalCount, $RunningJobs.Count, $PendingCount)
    if ($activeNames.Count -gt 0) {
        Write-Host ("  Active: {0}" -f ($activeNames -join ", "))
    }
    foreach ($job in $RunningJobs) {
        $latestLine = Get-LatestLogLine -Path $job.WorkItem.logPath
        if ($latestLine) {
            Write-Host ("  {0}: {1}" -f $job.WorkItem.exerciseName, $latestLine)
        }
    }
}

$repoRoot = Get-RepoRoot
$resolvedWorkoutPlanJson = Resolve-StrictPath $WorkoutPlanJson
if ($ExerciseWorkers -lt 1) {
    throw "ExerciseWorkers must be at least 1."
}
if ($ProgressIntervalSeconds -lt 1) {
    throw "ProgressIntervalSeconds must be at least 1."
}

if ([string]::IsNullOrWhiteSpace($WhamRepoPath)) {
    $WhamRepoPath = "C:\Users\gabri\Downloads\WHAM"
    if (-not (Test-Path -LiteralPath $WhamRepoPath)) {
        $WhamRepoPath = Join-Path $repoRoot "third_party\WHAM"
    }
}
if ([string]::IsNullOrWhiteSpace($BodyModelRoot)) {
    $BodyModelRoot = Join-Path $WhamRepoPath "dataset\body_models"
}

$resolvedWhamRepoPath = Resolve-StrictPath $WhamRepoPath
$resolvedBodyModelRoot = Resolve-StrictPath $BodyModelRoot

New-Item -ItemType Directory -Force -Path $WorkspaceRoot | Out-Null
$resolvedWorkspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$candidatesPath = Join-Path $resolvedWorkspaceRoot "youtube_candidates.json"
$summaryPath = Join-Path $resolvedWorkspaceRoot "workout_motion_generation_summary.json"

$youtubeArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "find-youtube-videos",
    "--workout-plan-json", $resolvedWorkoutPlanJson,
    "--out-json", $candidatesPath,
    "--results-per-query", "$ResultsPerQuery",
    "--max-candidates", "$MaxCandidates",
    "--metadata-candidate-pool-size", "$MetadataCandidatePoolSize",
    "--rank-with-vision",
    "--vision-candidates-per-exercise", "$VisionCandidatesPerExercise",
    "--vision-max-chunks-per-candidate", "$VisionMaxChunksPerCandidate",
    "--vision-download-workers", "$VisionDownloadWorkers",
    "--vision-llm-workers", "$VisionLlmWorkers",
    "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds"
)
if ($UseDeepSeekQueryPlanner) {
    $youtubeArgs += @(
        "--use-deepseek-query-planner",
        "--deepseek-base-url", $DeepSeekBaseUrl,
        "--deepseek-model", $DeepSeekModel,
        "--deepseek-max-queries", "$DeepSeekMaxQueries"
    )
    if (-not [string]::IsNullOrWhiteSpace($DeepSeekApiKey)) {
        $youtubeArgs += @("--deepseek-api-key", $DeepSeekApiKey)
    }
}
if ($VisionFramesPerCandidate -gt 0) {
    $youtubeArgs += @("--vision-frames-per-candidate", "$VisionFramesPerCandidate")
}
if ($IncludeDisabled) {
    $youtubeArgs += "--include-disabled"
}

Invoke-PythonModule -Arguments $youtubeArgs

$candidateManifest = Get-Content -LiteralPath $candidatesPath -Raw | ConvertFrom-Json
if (-not $candidateManifest.exercises -or $candidateManifest.exercises.Count -eq 0) {
    throw "No exercises were found in the workout plan candidate manifest: $candidatesPath"
}

$workItems = @()
$usedSlugs = @{}
$exerciseIndex = 0
foreach ($exercise in $candidateManifest.exercises) {
    $exerciseName = [string]($exercise.exerciseName ?? $exercise.name ?? $exercise.id ?? "exercise")
    $exerciseId = [string]($exercise.exerciseId ?? $exercise.id ?? (ConvertTo-Slug $exerciseName))
    $slugSource = [string]($exercise.slug ?? $exerciseId ?? $exerciseName)
    $exerciseSlug = ConvertTo-Slug $slugSource
    if ($usedSlugs.ContainsKey($exerciseSlug)) {
        $usedSlugs[$exerciseSlug] += 1
        $exerciseSlug = "$exerciseSlug-$($usedSlugs[$exerciseSlug])"
    } else {
        $usedSlugs[$exerciseSlug] = 1
    }
    $exerciseWorkspace = Join-Path $resolvedWorkspaceRoot $exerciseSlug
    $exerciseCandidatesPath = Join-Path $exerciseWorkspace "youtube_candidates.json"
    $bakeWorkspace = Join-Path $exerciseWorkspace "bake"
    $logPath = Join-Path $exerciseWorkspace "bake.log"
    $candidateCount = if ($exercise.candidates) { @($exercise.candidates).Count } else { 0 }

    New-Item -ItemType Directory -Force -Path $exerciseWorkspace | Out-Null
    New-ExerciseCandidateManifest -Exercise $exercise -OutPath $exerciseCandidatesPath

    $bakeArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "bake-and-rank",
        "--candidates-json", $exerciseCandidatesPath,
        "--fallback-candidates", "$FallbackCandidates",
        "--workspace", $bakeWorkspace,
        "--wham-repo-path", $resolvedWhamRepoPath,
        "--body-model-root", $resolvedBodyModelRoot,
        "--wham-python", "python",
        "--segment-confidence-threshold", "$SegmentConfidenceThreshold",
        "--segment-padding-seconds", "$SegmentPaddingSeconds",
        "--segment-end-padding-seconds", "$SegmentEndPaddingSeconds",
        "--segment-min-seconds", "$SegmentMinSeconds",
        "--segment-max-seconds", "$SegmentMaxSeconds",
        "--segment-classification-workers", "$SegmentClassificationWorkers",
        "--review-frames", "$ReviewFrames",
        "--max-review-windows", "$MaxReviewWindows",
        "--min-selected-score", "$MinSelectedScore",
        "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds"
    )
    if (-not $SkipPreviewVariantRanking) {
        $bakeArgs += "--rank-preview-variants"
    }
    if ($SkipSupportDominanceClassification) {
        $bakeArgs += "--no-classify-support-dominance"
    }
    if ($SegmentWindowSeconds.HasValue) {
        $bakeArgs += @("--segment-window-seconds", "$SegmentWindowSeconds")
    }
    if ($SegmentOverlapSeconds.HasValue) {
        $bakeArgs += @("--segment-overlap-seconds", "$SegmentOverlapSeconds")
    }
    if ($SegmentFramesPerWindow.HasValue) {
        $bakeArgs += @("--segment-frames-per-window", "$SegmentFramesPerWindow")
    }
    if (-not $NoWhamDocker) {
        $bakeArgs += @(
            "--use-wham-docker",
            "--wham-docker-image", $WhamDockerImage,
            "--wham-docker-gpus", $WhamDockerGpus,
            "--wham-docker-shm-size", $WhamDockerShmSize
        )
    }
    if (-not $FullWhamCameraSlam) {
        $bakeArgs += "--estimate-local-only"
    }
    if ($SkipSmplify) {
        $bakeArgs += "--skip-smplify"
    }
    if ($SkipMotionTuning) {
        $bakeArgs += "--skip-motion-tuning"
    }
    if (-not [string]::IsNullOrWhiteSpace($SegmentBaseUrl)) {
        $bakeArgs += @("--segment-base-url", $SegmentBaseUrl)
    }
    if (-not [string]::IsNullOrWhiteSpace($SegmentModel)) {
        $bakeArgs += @("--segment-model", $SegmentModel)
    }
    if ($SkipSourceSegmentDetection) {
        $bakeArgs += "--skip-source-segment-detection"
    }

    $workItems += [pscustomobject]@{
        index = $exerciseIndex
        exerciseId = $exerciseId
        exerciseName = $exerciseName
        exerciseSlug = $exerciseSlug
        candidateCount = $candidateCount
        exerciseCandidatesPath = $exerciseCandidatesPath
        bakeWorkspace = $bakeWorkspace
        logPath = $logPath
        bakeArgs = [string[]]$bakeArgs
    }
    $exerciseIndex += 1
}

$pendingWorkItems = [System.Collections.Queue]::new()
foreach ($workItem in $workItems) {
    $pendingWorkItems.Enqueue($workItem)
}

$runningJobs = @()
$summaryByIndex = @{}
$completedCount = 0
$lastProgressAt = [datetime]::MinValue
Write-Host "Generating movements with $ExerciseWorkers exercise worker(s)."
while ($pendingWorkItems.Count -gt 0 -or $runningJobs.Count -gt 0) {
    while ($pendingWorkItems.Count -gt 0 -and $runningJobs.Count -lt $ExerciseWorkers) {
        $runningJobs += Start-BakeJob -WorkItem ($pendingWorkItems.Dequeue())
    }

    if ($runningJobs.Count -eq 0) {
        continue
    }

    $now = Get-Date
    if (($now - $lastProgressAt).TotalSeconds -ge $ProgressIntervalSeconds) {
        Write-ProgressSnapshot -RunningJobs $runningJobs -CompletedCount $completedCount -TotalCount $workItems.Count -PendingCount $pendingWorkItems.Count
        $lastProgressAt = $now
    }

    $finishedJobs = @(Wait-Job -Job $runningJobs -Any -Timeout 2)
    if ($finishedJobs.Count -eq 0) {
        continue
    }
    foreach ($job in $finishedJobs) {
        $summaryByIndex[$job.WorkItem.index] = Complete-BakeJob -Job $job
        $completedCount += 1
    }
    $finishedJobIds = @($finishedJobs | ForEach-Object { $_.Id })
    $runningJobs = @($runningJobs | Where-Object { $_.Id -notin $finishedJobIds })
}

$summaryItems = @()
for ($index = 0; $index -lt $workItems.Count; $index += 1) {
    $summaryItems += $summaryByIndex[$index]
}

$summary = [ordered]@{
    schemaVersion = 1
    generatedAt = (Get-Date).ToUniversalTime().ToString("o")
    sourceWorkoutPlanPath = $resolvedWorkoutPlanJson
    workspaceRoot = $resolvedWorkspaceRoot
    youtubeCandidatesJsonPath = $candidatesPath
    exercises = $summaryItems
}
$summary | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host "Workout plan JSON: $resolvedWorkoutPlanJson"
Write-Host "YouTube candidates JSON: $candidatesPath"
Write-Host "Summary JSON: $summaryPath"
