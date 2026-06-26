param(
    [Parameter(Mandatory = $true)]
    [string]$WorkoutPlanJson,

    [string]$EquipmentJson,
    [string]$WorkspaceRoot = "build/exercise_motion/workout-plan",
    [string]$WhamRepoPath,
    [string]$BodyModelRoot,
    [string]$YouTubeCookiesPath,
    [string]$YouTubePreviewCacheDir,
    [string]$PythonCommand = "",
    [int]$ResultsPerQuery = 100,
    [int]$MaxCandidates = 8,
    [int]$MetadataCandidatePoolSize = 24,
    [int]$CandidateReviewBatchSize = 12,
    [int]$CandidateReviewTargetSuitableCount = 1,
    [Nullable[int]]$MaxCandidateReviewTargetSuitableCount = 5,
    [switch]$UseDeepSeekQueryPlanner,
    [string]$DeepSeekApiKey,
    [string]$DeepSeekBaseUrl = "https://api.deepseek.com",
    [string]$DeepSeekModel = "deepseek-v4-flash",
    [int]$DeepSeekMaxQueries = 4,
    [int]$VisionCandidatesPerExercise = 8,
    [int]$VisionFramesPerCandidate = 6,
    [int]$VisionMaxChunksPerCandidate = 0,
    [int]$VisionDownloadWorkers = 8,
    [int]$VisionLlmWorkers = 1,
    [switch]$SkipVisionRanking,
    [switch]$SemanticGateWithLlamaCpp,
    [switch]$SkipSemanticGate,
    [Nullable[int]]$SemanticGateCandidatesPerExercise = 24,
    [Nullable[int]]$SemanticGateMaxCandidatesPerExercise = 200,
    [double]$SemanticGateMinScore = 0.55,
    [switch]$PosePrefilter,
    [switch]$SkipPosePrefilter,
    [string]$PosePrefilterModel = "yolo26x-pose.pt",
    [Nullable[int]]$PosePrefilterCandidatesPerExercise,
    [double]$PosePrefilterSampleFps = 0.0,
    [double]$PosePrefilterMaxSeconds = 0.0,
    [ValidateSet("prefix", "spread", "full")]
    [string]$PosePrefilterScanStrategy = "full",
    [double]$PosePrefilterWindowSeconds = 8.0,
    [double]$PosePrefilterOverlapSeconds = 4.0,
    [double]$PosePrefilterMinScore = 0.45,
    [int]$PosePrefilterWorkers = 2,
    [string]$PosePrefilterDevice = "cuda",
    [int]$PosePrefilterBatchSize = 16,
    [int]$ExerciseWorkers = 2,
    [int]$FallbackCandidates = 12,
    [int]$MaxSelectedResults = 1,
    [int]$CandidateWorkers = 2,
    [switch]$IncludeDisabled,
    [switch]$NoWhamDocker,
    [string]$WhamDockerImage = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$WhamDockerGpus = "all",
    [string]$WhamDockerShmSize = "16g",
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
    [switch]$AdaptivePreviewSettings,
    [switch]$SkipAdaptivePreviewSettings,
    [int]$MaxAdaptivePreviewSettings = 1,
    [switch]$SkipPreviewVariantRanking,
    [switch]$ClassifySupportDominance,
    [switch]$SkipSupportDominanceClassification,
    [int]$ReviewFrames = 6,
    [int]$MaxReviewWindows = 3,
    [double]$MinSelectedScore = 0.55,
    [double]$LlamaCppRequestTimeoutSeconds = 90.0,
    [ValidateSet("debug", "full")]
    [string]$ArtifactRetention = "debug",
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

function New-OneExercisePlanJson {
    param(
        [object]$Exercise,
        [string]$OutPath
    )
    $plan = [ordered]@{
        schemaVersion = 1
        sourcePlanPath = $resolvedWorkoutPlanJson
        exercises = @(
            [ordered]@{
                id = [string]($Exercise.exerciseId ?? $Exercise.id ?? $Exercise.slug ?? $Exercise.exerciseName ?? "exercise")
                name = [string]($Exercise.exerciseName ?? $Exercise.name ?? $Exercise.id ?? "exercise")
            }
        )
    }
    $plan | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutPath -Encoding UTF8
}

function Copy-SelectedFile {
    param(
        [string]$SourcePath,
        [string]$DestinationDirectory,
        [string]$DestinationFileName
    )
    if ([string]::IsNullOrWhiteSpace($SourcePath) -or -not (Test-Path -LiteralPath $SourcePath)) {
        return $null
    }
    New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    $destinationPath = Join-Path $DestinationDirectory $DestinationFileName
    Copy-Item -LiteralPath $SourcePath -Destination $destinationPath -Force
    return $destinationPath
}

function Remove-ExerciseIntermediateArtifacts {
    param([object]$WorkItem)

    foreach ($path in @($WorkItem.bakeWorkspace)) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
    foreach ($path in @($WorkItem.exercisePlanPath, $WorkItem.exerciseCandidatesPath)) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}

function Start-BakeJob {
    param([object]$WorkItem)

    Write-Host "Starting movement generation for '$($WorkItem.exerciseName)'."
    $job = Start-Job -Name $WorkItem.exerciseSlug -ScriptBlock {
        param(
            [string]$PythonCommand,
            [string[]]$DiscoveryArguments,
            [string[]]$BakeArguments,
            [string]$LogPath,
            [string]$CandidatesPath,
            [string]$BakeWorkspace,
            [int]$InitialTargetSuitableCount,
            [int]$MaxTargetSuitableCount,
            [int]$BaseMaxCandidates,
            [int]$BaseVisionCandidates,
            [int]$MaxSelectedResults
        )

        $ErrorActionPreference = "Continue"

        function Set-ArgumentValue {
            param(
                [string[]]$Arguments,
                [string]$Name,
                [string]$Value
            )
            $result = @()
            $found = $false
            for ($index = 0; $index -lt $Arguments.Count; $index += 1) {
                $argument = $Arguments[$index]
                if ($argument -eq $Name) {
                    $result += @($Name, $Value)
                    $found = $true
                    $index += 1
                    continue
                }
                $result += $argument
            }
            if (-not $found) {
                $result += @($Name, $Value)
            }
            return [string[]]$result
        }

        function Get-RecommendedCandidateCount {
            param([string]$Path)
            if (-not (Test-Path -LiteralPath $Path)) {
                return 0
            }
            try {
                $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
                $recommended = 0
                foreach ($exercise in @($payload.exercises)) {
                    foreach ($item in @($exercise.candidates)) {
                        if ("$($item.status)".ToLowerInvariant() -eq "recommended") {
                            $recommended += 1
                        }
                    }
                }
                return $recommended
            } catch {
                return 0
            }
        }

        function Get-SelectedResultCount {
            param([string]$Workspace)
            $selectionPath = Join-Path $Workspace "selection_manifest.json"
            if (-not (Test-Path -LiteralPath $selectionPath)) {
                return 0
            }
            try {
                $selection = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-Json
                if ($selection -and $selection.PSObject.Properties.Name -contains "selectedResults" -and $selection.selectedResults) {
                    return @($selection.selectedResults).Count
                }
                if ($selection -and $selection.selected) {
                    return 1
                }
                return 0
            } catch {
                return 0
            }
        }

        function Test-SelectionManifest {
            param([string]$Workspace)
            return (Test-Path -LiteralPath (Join-Path $Workspace "selection_manifest.json"))
        }

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
        "[$(Get-Date -Format o)] movement generation started" | Set-Content -LiteralPath $LogPath -Encoding UTF8
        $targetSuitableCount = [Math]::Max(1, $InitialTargetSuitableCount)
        $attemptIndex = 1
        while ($true) {
            $attemptMaxCandidates = [Math]::Max($BaseMaxCandidates, $targetSuitableCount)
            $attemptVisionCandidates = [Math]::Max($BaseVisionCandidates, $targetSuitableCount)
            $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $DiscoveryArguments -Name "--candidate-review-target-suitable-count" -Value "$targetSuitableCount"
            $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--max-candidates" -Value "$attemptMaxCandidates"
            $attemptDiscoveryArgs = Set-ArgumentValue -Arguments $attemptDiscoveryArgs -Name "--vision-candidates-per-exercise" -Value "$attemptVisionCandidates"

            "[$(Get-Date -Format o)] discovery attempt $attemptIndex started; target suitable candidates $targetSuitableCount/$MaxTargetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            & $PythonCommand @attemptDiscoveryArgs *>> $LogPath
            $discoveryExitCode = $LASTEXITCODE
            if ($discoveryExitCode -ne 0) {
                [pscustomobject]@{
                    exitCode = $discoveryExitCode
                    stage = "discovery"
                    logPath = $LogPath
                }
                return
            }

            $recommendedCount = Get-RecommendedCandidateCount -Path $CandidatesPath
            if ($recommendedCount -le 0) {
                if ($targetSuitableCount -ge $MaxTargetSuitableCount) {
                    [pscustomobject]@{
                        exitCode = 0
                        stage = "discovery_no_recommended"
                        logPath = $LogPath
                    }
                    return
                }
                $targetSuitableCount = [Math]::Min($MaxTargetSuitableCount, $targetSuitableCount + 1)
                $attemptIndex += 1
                "[$(Get-Date -Format o)] no recommended candidates; expanding review target to $targetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                continue
            }

            "[$(Get-Date -Format o)] bake attempt $attemptIndex started with $recommendedCount recommended candidate(s)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            & $PythonCommand @BakeArguments *>> $LogPath
            $bakeExitCode = $LASTEXITCODE

            $selectedResultCount = Get-SelectedResultCount -Workspace $BakeWorkspace
            if ($selectedResultCount -gt 0) {
                if ($selectedResultCount -lt $MaxSelectedResults -and $targetSuitableCount -lt $MaxTargetSuitableCount) {
                    $targetSuitableCount = [Math]::Min($MaxTargetSuitableCount, $targetSuitableCount + 1)
                    $attemptIndex += 1
                    "[$(Get-Date -Format o)] selected $selectedResultCount/$MaxSelectedResults result(s); expanding review target to $targetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
                    continue
                }
                [pscustomobject]@{
                    exitCode = 0
                    stage = "bake"
                    logPath = $LogPath
                }
                return
            }
            if ($bakeExitCode -ne 0 -and -not (Test-SelectionManifest -Workspace $BakeWorkspace)) {
                [pscustomobject]@{
                    exitCode = $bakeExitCode
                    stage = "bake"
                    logPath = $LogPath
                }
                return
            }
            if ($bakeExitCode -ne 0) {
                "[$(Get-Date -Format o)] bake returned exit code $bakeExitCode after writing a no-selection manifest; expanding review target if possible" | Add-Content -LiteralPath $LogPath -Encoding UTF8
            }

            if ($targetSuitableCount -ge $MaxTargetSuitableCount) {
                [pscustomobject]@{
                    exitCode = 0
                    stage = "bake_no_selection"
                    logPath = $LogPath
                }
                return
            }

            $targetSuitableCount = [Math]::Min($MaxTargetSuitableCount, $targetSuitableCount + 1)
            $attemptIndex += 1
            "[$(Get-Date -Format o)] no selected Wear skeleton; expanding review target to $targetSuitableCount" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        }
    } -ArgumentList $PythonCommand, ([string[]]$WorkItem.discoveryArgs), ([string[]]$WorkItem.bakeArgs), $WorkItem.logPath, $WorkItem.exerciseCandidatesPath, $WorkItem.bakeWorkspace, $WorkItem.candidateReviewTargetSuitableCount, $WorkItem.maxCandidateReviewTargetSuitableCount, $WorkItem.maxCandidates, $WorkItem.visionCandidatesPerExercise, $WorkItem.maxSelectedResults
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
        $stage = if ($jobResult -and $jobResult.stage) { $jobResult.stage } else { "unknown" }
        $errorMessage = "python $stage command failed with exit code $exitCode. See log: $($workItem.logPath)"
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
    $selectedOptions = if ($selection -and $selection.PSObject.Properties.Name -contains "selectedResults" -and $selection.selectedResults) {
        @($selection.selectedResults)
    } elseif ($selected) {
        @($selected)
    } else {
        @()
    }
    if ($status -eq "completed" -and $selectedOptions.Count -eq 0) {
        $status = "no_selection"
        $errorMessage = "No Wear skeleton was selected."
    }
    if ($status -eq "completed") {
        $optionIndex = 1
        foreach ($option in $selectedOptions) {
            if ($option.wearSkeletonSettingsBaked -ne $true) {
                $status = "failed"
                $errorMessage = "Selected Wear skeleton option $optionIndex does not contain baked preview settings required by Wear."
                break
            }
            $optionIndex += 1
        }
    }

    $candidateCount = $workItem.candidateCount
    if (Test-Path -LiteralPath $workItem.exerciseCandidatesPath) {
        try {
            $exerciseCandidateManifest = Get-Content -LiteralPath $workItem.exerciseCandidatesPath -Raw | ConvertFrom-Json
            if ($exerciseCandidateManifest.exercises -and $exerciseCandidateManifest.exercises.Count -gt 0) {
                $candidateCount = @($exerciseCandidateManifest.exercises[0].candidates).Count
            }
        } catch {
            if ($null -eq $candidateCount) {
                $candidateCount = 0
            }
        }
    }

    $selectedOutputDir = Join-Path $workItem.exerciseWorkspace "selected"
    $selectedWearSkeletonPath = $null
    $selectedPreviewVideoPath = $null
    $selectedInputVideoPath = $null
    $selectedInputVideoSourcePath = $null
    $selectedInputVideoMissing = $false
    $selectedSelectionManifestPath = $null
    $selectedDebugDir = Join-Path $selectedOutputDir "debug"
    $selectedCandidateDebugPath = $null
    $selectedCandidateDecisionsPath = $null
    $selectedResultOutputs = @()
    if ($status -eq "completed" -and $selectedOptions.Count -gt 0) {
        $selectedFilePrefix = $workItem.exerciseSlug -replace "-", "_"
        $selectedSelectionManifestPath = Copy-SelectedFile `
            -SourcePath $selectionPath `
            -DestinationDirectory $selectedOutputDir `
            -DestinationFileName "selection_manifest.json"
        $selectedCandidateDebugPath = Copy-SelectedFile `
            -SourcePath $workItem.exerciseCandidatesPath `
            -DestinationDirectory $selectedDebugDir `
            -DestinationFileName "youtube_candidates.full.json"
        $candidateDecisionsPath = Join-Path (Split-Path -Parent $workItem.exerciseCandidatesPath) "candidate_decisions.jsonl"
        $selectedCandidateDecisionsPath = Copy-SelectedFile `
            -SourcePath $candidateDecisionsPath `
            -DestinationDirectory $selectedDebugDir `
            -DestinationFileName "candidate_decisions.jsonl"
        $optionIndex = 1
        foreach ($option in $selectedOptions) {
            $optionSuffix = if ($optionIndex -eq 1) { "" } else { "_option_{0:D2}" -f $optionIndex }
            $optionWearSkeletonPath = Copy-SelectedFile `
                -SourcePath $option.selectedWearSkeletonPath `
                -DestinationDirectory $selectedOutputDir `
                -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_wear_skeleton.json"
            $optionPreviewVideoPath = $null
            if ($option.selectedReviewVideoPath) {
                $optionPreviewVideoPath = Copy-SelectedFile `
                    -SourcePath $option.selectedReviewVideoPath `
                    -DestinationDirectory $selectedOutputDir `
                    -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_selected_preview.webm"
            }
            $optionInputVideoSourcePath = if ($option.PSObject.Properties.Name -contains "selectedInputVideoPath") {
                $option.selectedInputVideoPath
            } elseif ($option.PSObject.Properties.Name -contains "copiedInputVideoPath") {
                $option.copiedInputVideoPath
            } else {
                $null
            }
            $optionInputVideoPath = $null
            $optionInputVideoMissing = $false
            if ($optionInputVideoSourcePath) {
                $optionInputVideoPath = Copy-SelectedFile `
                    -SourcePath $optionInputVideoSourcePath `
                    -DestinationDirectory $selectedOutputDir `
                    -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_selected_input.mp4"
                if (-not $optionInputVideoPath) {
                    $optionInputVideoMissing = $true
                    Write-Warning "Selected input video option $optionIndex was not copied for '$($workItem.exerciseName)': $optionInputVideoSourcePath"
                }
            }
            $optionPreviewHtmlPath = $null
            if ($option.PSObject.Properties.Name -contains "selectedPreviewHtmlPath" -and $option.selectedPreviewHtmlPath) {
                $optionPreviewHtmlPath = Copy-SelectedFile `
                    -SourcePath $option.selectedPreviewHtmlPath `
                    -DestinationDirectory $selectedOutputDir `
                    -DestinationFileName "$($selectedFilePrefix)$($optionSuffix)_selected_preview.html"
            }
            $selectedResultOutputs += [ordered]@{
                optionIndex = $optionIndex
                label = if ($option.PSObject.Properties.Name -contains "manualSelectionLabel") { $option.manualSelectionLabel } else { "Option $optionIndex" }
                selectedWearSkeletonPath = $optionWearSkeletonPath
                selectedPreviewVideoPath = $optionPreviewVideoPath
                selectedPreviewHtmlPath = $optionPreviewHtmlPath
                selectedSourceVideoPath = $optionInputVideoPath
                selectedSourceVideoOriginalPath = $optionInputVideoSourcePath
                selectedSourceVideoMissing = $optionInputVideoMissing
                selectionScore = if ($option.PSObject.Properties.Name -contains "selectionScore") { $option.selectionScore } else { $null }
                candidateTitle = if ($option.PSObject.Properties.Name -contains "candidateTitle") { $option.candidateTitle } else { $null }
            }
            if ($optionIndex -eq 1) {
                $selectedWearSkeletonPath = $optionWearSkeletonPath
                $selectedPreviewVideoPath = $optionPreviewVideoPath
                $selectedInputVideoPath = $optionInputVideoPath
                $selectedInputVideoSourcePath = $optionInputVideoSourcePath
                $selectedInputVideoMissing = $optionInputVideoMissing
            }
            $optionIndex += 1
        }
        Remove-ExerciseIntermediateArtifacts -WorkItem $workItem
    }

    Write-Host "[$status] $($workItem.exerciseName)"
    if ($selectedWearSkeletonPath) {
        Write-Host "  Wear skeleton JSON: $selectedWearSkeletonPath"
        if ($selected.PSObject.Properties.Name -contains "wearSkeletonSettingsBaked") {
            Write-Host "  Wear skeleton settings baked: $($selected.wearSkeletonSettingsBaked)"
        }
    }
    if ($selectedPreviewVideoPath) {
        Write-Host "  Selected preview video: $selectedPreviewVideoPath"
    }
    if ($selectedInputVideoPath) {
        Write-Host "  Selected input video: $selectedInputVideoPath"
    }
    if ($selectedResultOutputs.Count -gt 1) {
        Write-Host "  Selected result options: $($selectedResultOutputs.Count)"
        foreach ($option in $selectedResultOutputs) {
            Write-Host "    Option $($option.optionIndex): $($option.selectedWearSkeletonPath)"
        }
    }

    return [ordered]@{
        exerciseId = $workItem.exerciseId
        exerciseName = $workItem.exerciseName
        status = $status
        error = $errorMessage
        candidateCount = $candidateCount
        candidatesJsonPath = if ($status -eq "completed") { $null } else { $workItem.exerciseCandidatesPath }
        selectionManifestPath = if ($status -eq "completed") { $selectedSelectionManifestPath } else { $selectionPath }
        logPath = $workItem.logPath
        selectedWearSkeletonPath = $selectedWearSkeletonPath
        selectedPreviewVideoPath = $selectedPreviewVideoPath
        selectedSourceVideoPath = $selectedInputVideoPath
        selectedSourceVideoOriginalPath = $selectedInputVideoSourcePath
        selectedSourceVideoMissing = $selectedInputVideoMissing
        selectedResults = $selectedResultOutputs
        selectedCandidateDebugPath = $selectedCandidateDebugPath
        selectedCandidateDecisionsPath = $selectedCandidateDecisionsPath
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
$PythonCommand = Resolve-MotionPythonCommand $PythonCommand
$resolvedWorkoutPlanJson = Resolve-StrictPath $WorkoutPlanJson
if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $EquipmentJson = Resolve-StrictPath $EquipmentJson
}
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $YouTubeCookiesPath = Resolve-StrictPath $YouTubeCookiesPath
}
if ($ExerciseWorkers -lt 1) {
    throw "ExerciseWorkers must be at least 1."
}
if ($ProgressIntervalSeconds -lt 1) {
    throw "ProgressIntervalSeconds must be at least 1."
}
if ($CandidateReviewTargetSuitableCount -lt 1) {
    throw "CandidateReviewTargetSuitableCount must be at least 1."
}
if ($MaxSelectedResults -lt 1) {
    throw "MaxSelectedResults must be at least 1."
}
$resolvedMaxCandidateReviewTargetSuitableCount = if ($null -ne $MaxCandidateReviewTargetSuitableCount) {
    [Math]::Max([int]$MaxCandidateReviewTargetSuitableCount, $MaxSelectedResults)
} else {
    [Math]::Max($FallbackCandidates, $CandidateReviewTargetSuitableCount, $MaxSelectedResults)
}
$initialTargetSuitableCount = [Math]::Max($CandidateReviewTargetSuitableCount, $MaxSelectedResults)
if ($resolvedMaxCandidateReviewTargetSuitableCount -lt $initialTargetSuitableCount) {
    throw "MaxCandidateReviewTargetSuitableCount must be greater than or equal to CandidateReviewTargetSuitableCount and MaxSelectedResults."
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
$sharedPreviewCachePath = if ([string]::IsNullOrWhiteSpace($YouTubePreviewCacheDir)) {
    Join-Path (Join-Path $repoRoot "build\exercise_motion") "youtube-preview-cache"
} else {
    $YouTubePreviewCacheDir
}
New-Item -ItemType Directory -Force -Path $sharedPreviewCachePath | Out-Null
$exerciseListPath = Join-Path $resolvedWorkspaceRoot "workout_plan_exercises.json"
$summaryPath = Join-Path $resolvedWorkspaceRoot "workout_motion_generation_summary.json"

$listArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "list-workout-plan-exercises",
    "--workout-plan-json", $resolvedWorkoutPlanJson,
    "--out-json", $exerciseListPath
)
if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $listArgs += @("--equipment-json", $EquipmentJson)
}
if ($IncludeDisabled) {
    $listArgs += "--include-disabled"
}
Invoke-PythonModule -Arguments $listArgs

$exerciseList = Get-Content -LiteralPath $exerciseListPath -Raw | ConvertFrom-Json
if (-not $exerciseList.exercises -or $exerciseList.exercises.Count -eq 0) {
    throw "No exercises were found in the workout plan: $resolvedWorkoutPlanJson"
}

$youtubeBaseArgs = @(
    "-m", "exercise_motion_pkg.cli",
    "find-youtube-videos",
    "--results-per-query", "$ResultsPerQuery",
    "--max-candidates", "$MaxCandidates",
    "--metadata-candidate-pool-size", "$MetadataCandidatePoolSize",
    "--candidate-review-batch-size", "$CandidateReviewBatchSize",
    "--candidate-review-target-suitable-count", "$CandidateReviewTargetSuitableCount",
    "--vision-candidates-per-exercise", "$VisionCandidatesPerExercise",
    "--vision-download-workers", "$VisionDownloadWorkers",
    "--vision-llm-workers", "$VisionLlmWorkers",
    "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds"
)
if ($VisionMaxChunksPerCandidate -gt 0) {
    $youtubeBaseArgs += @("--vision-max-chunks-per-candidate", "$VisionMaxChunksPerCandidate")
}
if (-not $SkipVisionRanking) {
    $youtubeBaseArgs += "--rank-with-vision"
}
if ($SemanticGateWithLlamaCpp -or -not $SkipSemanticGate) {
    $youtubeBaseArgs += @(
        "--semantic-gate-with-llama-cpp",
        "--semantic-gate-min-score", "$SemanticGateMinScore"
    )
    if ($null -ne $SemanticGateCandidatesPerExercise) {
        $youtubeBaseArgs += @("--semantic-gate-candidates-per-exercise", "$SemanticGateCandidatesPerExercise")
    }
    if ($null -ne $SemanticGateMaxCandidatesPerExercise) {
        $youtubeBaseArgs += @("--semantic-gate-max-candidates-per-exercise", "$SemanticGateMaxCandidatesPerExercise")
    }
}
if ($UseDeepSeekQueryPlanner) {
    $youtubeBaseArgs += @(
        "--use-deepseek-query-planner",
        "--deepseek-base-url", $DeepSeekBaseUrl,
        "--deepseek-model", $DeepSeekModel,
        "--deepseek-max-queries", "$DeepSeekMaxQueries"
    )
    if (-not [string]::IsNullOrWhiteSpace($DeepSeekApiKey)) {
        $youtubeBaseArgs += @("--deepseek-api-key", $DeepSeekApiKey)
    }
}
if ($VisionFramesPerCandidate -gt 0) {
    $youtubeBaseArgs += @("--vision-frames-per-candidate", "$VisionFramesPerCandidate")
}
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $youtubeBaseArgs += @("--youtube-cookies", $YouTubeCookiesPath)
}
if ($PosePrefilter -and -not $SkipPosePrefilter) {
    $youtubeBaseArgs += @(
        "--pose-prefilter",
        "--pose-prefilter-model", $PosePrefilterModel,
        "--pose-prefilter-sample-fps", "$PosePrefilterSampleFps",
        "--pose-prefilter-max-seconds", "$PosePrefilterMaxSeconds",
        "--pose-prefilter-scan-strategy", $PosePrefilterScanStrategy,
        "--pose-prefilter-window-seconds", "$PosePrefilterWindowSeconds",
        "--pose-prefilter-overlap-seconds", "$PosePrefilterOverlapSeconds",
        "--pose-prefilter-min-score", "$PosePrefilterMinScore",
        "--pose-prefilter-workers", "$PosePrefilterWorkers",
        "--pose-prefilter-device", $PosePrefilterDevice,
        "--pose-prefilter-batch-size", "$PosePrefilterBatchSize"
    )
    if ($null -ne $PosePrefilterCandidatesPerExercise) {
        $youtubeBaseArgs += @("--pose-prefilter-candidates-per-exercise", "$PosePrefilterCandidatesPerExercise")
    }
}

$workItems = @()
$usedSlugs = @{}
$exerciseIndex = 0
foreach ($exercise in $exerciseList.exercises) {
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
    $exercisePlanPath = Join-Path $exerciseWorkspace "exercise_plan.json"
    $exerciseCandidatesPath = Join-Path $exerciseWorkspace "youtube_candidates.json"
    $previewCachePath = $sharedPreviewCachePath
    $bakeWorkspace = Join-Path $exerciseWorkspace "bake"
    $logPath = Join-Path $exerciseWorkspace "bake.log"

    New-Item -ItemType Directory -Force -Path $exerciseWorkspace | Out-Null
    New-OneExercisePlanJson -Exercise $exercise -OutPath $exercisePlanPath

    $discoveryArgs = @($youtubeBaseArgs)
    $discoveryArgs += @(
        "--workout-plan-json", $exercisePlanPath,
        "--out-json", $exerciseCandidatesPath,
        "--youtube-preview-cache-dir", $previewCachePath
    )

    $bakeArgs = @(
        "-m", "exercise_motion_pkg.cli",
        "bake-and-rank",
        "--candidates-json", $exerciseCandidatesPath,
        "--fallback-candidates", "$FallbackCandidates",
        "--max-selected-results", "$MaxSelectedResults",
        "--candidate-workers", "$CandidateWorkers",
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
        "--llama-cpp-request-timeout-seconds", "$LlamaCppRequestTimeoutSeconds",
        "--artifact-retention", $ArtifactRetention
    )
    if ($RankPreviewVariants -and -not $SkipPreviewVariantRanking) {
        $bakeArgs += "--rank-preview-variants"
    }
    if ($AdaptivePreviewSettings -or (-not $SkipAdaptivePreviewSettings -and -not $RankPreviewVariants)) {
        $bakeArgs += @(
            "--adaptive-preview-settings",
            "--max-adaptive-preview-settings", "$MaxAdaptivePreviewSettings"
        )
    }
    if (-not $ClassifySupportDominance -or $SkipSupportDominanceClassification) {
        $bakeArgs += "--no-classify-support-dominance"
    }
    if ($null -ne $SegmentWindowSeconds) {
        $bakeArgs += @("--segment-window-seconds", "$SegmentWindowSeconds")
    }
    if ($null -ne $SegmentOverlapSeconds) {
        $bakeArgs += @("--segment-overlap-seconds", "$SegmentOverlapSeconds")
    }
    if ($null -ne $SegmentFramesPerWindow) {
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
    if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
        $bakeArgs += @("--youtube-cookies", $YouTubeCookiesPath)
    }

    $workItems += [pscustomobject]@{
        index = $exerciseIndex
        exerciseId = $exerciseId
        exerciseName = $exerciseName
        exerciseSlug = $exerciseSlug
        candidateCount = $null
        exerciseWorkspace = $exerciseWorkspace
        exercisePlanPath = $exercisePlanPath
        exerciseCandidatesPath = $exerciseCandidatesPath
        previewCachePath = $previewCachePath
        bakeWorkspace = $bakeWorkspace
        logPath = $logPath
        candidateReviewTargetSuitableCount = $initialTargetSuitableCount
        maxCandidateReviewTargetSuitableCount = $resolvedMaxCandidateReviewTargetSuitableCount
        maxSelectedResults = $MaxSelectedResults
        maxCandidates = $MaxCandidates
        visionCandidatesPerExercise = $VisionCandidatesPerExercise
        discoveryArgs = [string[]]$discoveryArgs
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
    equipmentJsonPath = if ([string]::IsNullOrWhiteSpace($EquipmentJson)) { $null } else { $EquipmentJson }
    workspaceRoot = $resolvedWorkspaceRoot
    exerciseListJsonPath = $exerciseListPath
    maxSelectedResults = $MaxSelectedResults
    exercises = $summaryItems
}
$summary | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host "Workout plan JSON: $resolvedWorkoutPlanJson"
Write-Host "Workout-plan exercises JSON: $exerciseListPath"
Write-Host "Summary JSON: $summaryPath"
