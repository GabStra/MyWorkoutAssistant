[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)]
    [Alias("PreviousWorkspaceRoots", "FromWorkspaceRoot", "FromWorkspaceRoots")]
    [string[]]$PreviousWorkspaceRoot,

    [string]$WorkoutPlanJson,
    [string]$EquipmentJson,
    [string]$YouTubeCookiesPath,
    [string]$WorkspaceRoot,
    [Alias("OnlyExerciseName", "ExerciseNames", "Exercises")]
    [string[]]$ExerciseName = @(),
    [Alias("OnlyExerciseSlug", "ExerciseSlugs")]
    [string[]]$ExerciseSlug = @(),
    [Alias("OnlyExerciseId", "ExerciseIds")]
    [string[]]$ExerciseId = @(),
    [int]$ProgressIntervalSeconds = 60,
    [switch]$ListExercises,
    [switch]$PrintCommandOnly,

    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArguments = @()
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

function Get-ObjectProperty {
    param(
        [object]$ObjectValue,
        [string]$PropertyName
    )
    if ($null -eq $ObjectValue) {
        return $null
    }
    if ($ObjectValue.PSObject.Properties.Name -contains $PropertyName) {
        return $ObjectValue.$PropertyName
    }
    return $null
}

function Get-ObjectStringProperty {
    param(
        [object]$ObjectValue,
        [string]$PropertyName
    )
    $value = Get-ObjectProperty -ObjectValue $ObjectValue -PropertyName $PropertyName
    if ($null -eq $value) {
        return ""
    }
    return [string]$value
}

function Get-ObjectStringArrayProperty {
    param(
        [object]$ObjectValue,
        [string]$PropertyName
    )
    $value = Get-ObjectProperty -ObjectValue $ObjectValue -PropertyName $PropertyName
    if ($null -eq $value) {
        return [string[]]@()
    }
    return [string[]]@($value | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | ForEach-Object { [string]$_ })
}

function Expand-DelimitedValues {
    param([string[]]$Values)
    $expanded = @()
    foreach ($value in @($Values)) {
        if ([string]::IsNullOrWhiteSpace($value)) {
            continue
        }
        foreach ($part in ([string]$value -split "\s*[;|]\s*")) {
            if (-not [string]::IsNullOrWhiteSpace($part)) {
                $expanded += $part.Trim()
            }
        }
    }
    return [string[]]$expanded
}

function Read-WorkspaceSummary {
    param([string]$WorkspaceRoot)
    $summaryPath = Join-Path $WorkspaceRoot "workout_motion_generation_summary.json"
    if (-not (Test-Path -LiteralPath $summaryPath -PathType Leaf)) {
        throw "Previous workspace does not contain workout_motion_generation_summary.json: $WorkspaceRoot"
    }
    return Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
}

function Add-UniquePath {
    param(
        [System.Collections.Generic.List[string]]$Paths,
        [hashtable]$Seen,
        [string]$PathValue
    )
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return
    }
    if (-not (Test-Path -LiteralPath $PathValue)) {
        Write-Warning "Skipping missing previous workspace path '$PathValue'."
        return
    }
    $resolved = Resolve-StrictPath $PathValue
    $key = $resolved.ToLowerInvariant()
    if (-not $Seen.ContainsKey($key)) {
        $Seen[$key] = $true
        $Paths.Add($resolved) | Out-Null
    }
}

function Get-LatestYouTubeCookiesPath {
    $downloads = Join-Path $env:USERPROFILE "Downloads"
    if (-not (Test-Path -LiteralPath $downloads -PathType Container)) {
        return ""
    }
    $latest = Get-ChildItem -LiteralPath $downloads -Filter "www.youtube.com_cookies*.txt" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        return ""
    }
    return $latest.FullName
}

function Get-SummaryExerciseFilter {
    param([object]$Summary)
    $exercises = @((Get-ObjectProperty -ObjectValue $Summary -PropertyName "exercises") | Where-Object { $null -ne $_ })
    if ($exercises.Count -ne 1) {
        throw "Previous workspace has $($exercises.Count) exercises. Pass -ExerciseName, -ExerciseSlug, or -ExerciseId to choose the subset to retry. Use -ListExercises to inspect available exercises."
    }
    $exercise = $exercises[0]
    foreach ($propertyName in @("exerciseName", "name", "exerciseId", "id")) {
        $value = Get-ObjectStringProperty -ObjectValue $exercise -PropertyName $propertyName
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }
    throw "Could not infer the exercise name from the previous workspace summary. Pass -ExerciseName explicitly."
}

function Write-SummaryExerciseList {
    param([object[]]$PreviousSummaries)

    $rows = @()
    foreach ($entry in @($PreviousSummaries)) {
        $summary = $entry.summary
        foreach ($exercise in @((Get-ObjectProperty -ObjectValue $summary -PropertyName "exercises") | Where-Object { $null -ne $_ })) {
            $rows += [pscustomobject]@{
                workspace = $entry.root
                exerciseName = Get-ObjectStringProperty -ObjectValue $exercise -PropertyName "exerciseName"
                exerciseId = Get-ObjectStringProperty -ObjectValue $exercise -PropertyName "exerciseId"
                exerciseSlug = Get-ObjectStringProperty -ObjectValue $exercise -PropertyName "exerciseSlug"
                status = Get-ObjectStringProperty -ObjectValue $exercise -PropertyName "status"
                selectedPreviewVideoPath = Get-ObjectStringProperty -ObjectValue $exercise -PropertyName "selectedPreviewVideoPath"
            }
        }
    }
    $rows | Format-Table -AutoSize
}

$repoRoot = Get-RepoRoot
$previousSummaries = @()
$excludeRoots = [System.Collections.Generic.List[string]]::new()
$seenExcludeRoots = @{}

foreach ($rootValue in @($PreviousWorkspaceRoot)) {
    $resolvedRoot = Resolve-StrictPath $rootValue
    $summary = Read-WorkspaceSummary -WorkspaceRoot $resolvedRoot
    $previousSummaries += [pscustomobject]@{
        root = $resolvedRoot
        summary = $summary
    }
    Add-UniquePath -Paths $excludeRoots -Seen $seenExcludeRoots -PathValue $resolvedRoot
    foreach ($priorRoot in Get-ObjectStringArrayProperty -ObjectValue $summary -PropertyName "excludeCandidatesFromWorkspaceRoots") {
        Add-UniquePath -Paths $excludeRoots -Seen $seenExcludeRoots -PathValue $priorRoot
    }
}

if ($previousSummaries.Count -eq 0) {
    throw "At least one previous workspace root is required."
}

$primarySummary = $previousSummaries[0].summary

if ($ListExercises) {
    Write-SummaryExerciseList -PreviousSummaries $previousSummaries
    exit 0
}

$ExerciseName = Expand-DelimitedValues -Values $ExerciseName
$ExerciseSlug = Expand-DelimitedValues -Values $ExerciseSlug
$ExerciseId = Expand-DelimitedValues -Values $ExerciseId

if ([string]::IsNullOrWhiteSpace($WorkoutPlanJson)) {
    $WorkoutPlanJson = Get-ObjectStringProperty -ObjectValue $primarySummary -PropertyName "sourceWorkoutPlanPath"
}
if ([string]::IsNullOrWhiteSpace($WorkoutPlanJson)) {
    throw "WorkoutPlanJson was not provided and could not be inferred from the previous workspace summary."
}
$WorkoutPlanJson = Resolve-StrictPath $WorkoutPlanJson

if ([string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $EquipmentJson = Get-ObjectStringProperty -ObjectValue $primarySummary -PropertyName "equipmentJsonPath"
}
if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $EquipmentJson = Resolve-StrictPath $EquipmentJson
}

if ([string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $YouTubeCookiesPath = Get-LatestYouTubeCookiesPath
}
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $YouTubeCookiesPath = Resolve-StrictPath $YouTubeCookiesPath
}

$hasExerciseFilter = (
    $ExerciseName.Count -gt 0 -or
    $ExerciseSlug.Count -gt 0 -or
    $ExerciseId.Count -gt 0
)
if (-not $hasExerciseFilter) {
    $ExerciseName = @((Get-SummaryExerciseFilter -Summary $primarySummary))
}

if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    $filterCount = @($ExerciseSlug).Count + @($ExerciseName).Count + @($ExerciseId).Count
    $slugSource = if ($filterCount -gt 1) {
        "subset"
    } elseif ($ExerciseSlug.Count -gt 0) {
        [string]$ExerciseSlug[0]
    } elseif ($ExerciseName.Count -gt 0) {
        [string]$ExerciseName[0]
    } elseif ($ExerciseId.Count -gt 0) {
        [string]$ExerciseId[0]
    } else {
        "exercise"
    }
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $WorkspaceRoot = Join-Path (Join-Path $repoRoot "build\exercise_motion") ("reattempt-{0}-{1}" -f (ConvertTo-Slug $slugSource), $timestamp)
}

$runArgs = @(
    "-WorkoutPlanJson", $WorkoutPlanJson,
    "-WorkspaceRoot", $WorkspaceRoot,
    "-ProgressIntervalSeconds", "$ProgressIntervalSeconds"
)
if (-not [string]::IsNullOrWhiteSpace($EquipmentJson)) {
    $runArgs += @("-EquipmentJson", $EquipmentJson)
}
if (-not [string]::IsNullOrWhiteSpace($YouTubeCookiesPath)) {
    $runArgs += @("-YouTubeCookiesPath", $YouTubeCookiesPath)
}
foreach ($value in @($ExerciseName)) {
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        $runArgs += @("-OnlyExerciseName", $value)
    }
}
foreach ($value in @($ExerciseSlug)) {
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        $runArgs += @("-OnlyExerciseSlug", $value)
    }
}
foreach ($value in @($ExerciseId)) {
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        $runArgs += @("-OnlyExerciseId", $value)
    }
}
foreach ($value in @($excludeRoots)) {
    $runArgs += @("-ExcludeCandidatesFromWorkspaceRoot", $value)
}
$runArgs += @($RemainingArguments | ForEach-Object { [string]$_ })

$runScriptPath = Join-Path $PSScriptRoot "run_exercise_motion_workout_plan.ps1"
if ($PrintCommandOnly) {
    [ordered]@{
        scriptPath = $runScriptPath
        arguments = $runArgs
        workspaceRoot = $WorkspaceRoot
        excludedWorkspaceRoots = [string[]]$excludeRoots
        exerciseNames = [string[]]$ExerciseName
        exerciseSlugs = [string[]]$ExerciseSlug
        exerciseIds = [string[]]$ExerciseId
    } | ConvertTo-Json -Depth 16
    exit 0
}

Write-Host "Retry workspace: $WorkspaceRoot"
Write-Host "Previous workspaces excluded: $($excludeRoots.Count)"
if ($ExerciseName.Count -gt 0) {
    Write-Host "Exercise name filter: $($ExerciseName -join ', ')"
}
if ($ExerciseSlug.Count -gt 0) {
    Write-Host "Exercise slug filter: $($ExerciseSlug -join ', ')"
}
if ($ExerciseId.Count -gt 0) {
    Write-Host "Exercise id filter: $($ExerciseId -join ', ')"
}

& $runScriptPath @runArgs
exit $LASTEXITCODE
