[CmdletBinding(PositionalBinding = $false)]
param(
    # Substring matches (case-insensitive) against exercise names, e.g.
    #   -ExerciseNames "side lunge","bench dips","deadlift"
    [Parameter(Mandatory = $true)]
    [string[]]$ExerciseNames,

    [string]$ExerciseLibraryJson = "C:\Users\gabri\Downloads\my_exercise_library.json",

    # Separate workspace root so verification never touches the live run's
    # per-exercise resume state. WHAM/YouTube caches are global and shared,
    # so a fresh verify workspace does not re-download or re-run inference
    # for already-seen segments.
    [string]$WorkspaceRoot = "build/exercise_motion/exercise-library-verify",

    [string]$OutputJson = "build/exercise_motion/targeted_movements_output.json",

    [string]$MotionReconstructor = "gvhmr",

    # Write only the filtered library JSON and print the command that would
    # run; skips -BuildLibraryOnly when you want to inspect the selection
    # without starting GPU/CPU work.
    [switch]$BuildLibraryOnly,

    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArguments = @()
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ExerciseLibraryJson)) {
    throw "Exercise library not found: $ExerciseLibraryJson"
}

$library = Get-Content -LiteralPath $ExerciseLibraryJson -Raw | ConvertFrom-Json
$definitions = @($library.exerciseDefinitions)

$namePatterns = @($ExerciseNames | ForEach-Object { $_.ToLowerInvariant() })
$selected = @(
    $definitions | Where-Object {
        $name = [string]$_.name
        $lowered = $name.ToLowerInvariant()
        foreach ($pattern in $namePatterns) {
            if ($lowered.Contains($pattern)) { return $true }
        }
        return $false
    }
)

if ($selected.Count -lt 1) {
    $known = ($definitions | Select-Object -First 40 -ExpandProperty name) -join ", "
    throw "No exercises matched [$($ExerciseNames -join ', ')]. Example names: $known ..."
}

Write-Host "Selected $($selected.Count) exercise(s):"
$selected | ForEach-Object { Write-Host "  - $($_.name)" }

$selectedIds = [System.Collections.Generic.HashSet[string]]::new()
foreach ($exercise in $selected) { [void]$selectedIds.Add([string]$exercise.id) }

$equipmentIds = [System.Collections.Generic.HashSet[string]]::new()
foreach ($exercise in $selected) {
    foreach ($id in @($exercise.equipmentId)) { if ($id) { [void]$equipmentIds.Add([string]$id) } }
    foreach ($id in @($exercise.requiredAccessoryEquipmentIds)) { if ($id) { [void]$equipmentIds.Add([string]$id) } }
}

$filtered = [ordered]@{
    format = $library.format
    schemaVersion = $library.schemaVersion
    exerciseDefinitions = $selected
    exerciseMovements = @(
        @($library.exerciseMovements) | Where-Object { $selectedIds.Contains([string]$_.id) }
    )
    equipments = @(
        @($library.equipments) | Where-Object { $equipmentIds.Contains([string]$_.id) }
    )
    accessoryEquipments = @(
        @($library.accessoryEquipments) | Where-Object { $equipmentIds.Contains([string]$_.id) }
    )
}

$filteredPath = Join-Path $WorkspaceRoot "targeted-library.json"
$filteredDir = Split-Path -Parent $filteredPath
if (-not (Test-Path -LiteralPath $filteredDir)) {
    New-Item -ItemType Directory -Path $filteredDir -Force | Out-Null
}
$filtered | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $filteredPath -Encoding UTF8
Write-Host "Filtered library written: $filteredPath"

if ($BuildLibraryOnly) { return }

$arguments = @(
    "-ExerciseLibraryJson", $filteredPath,
    "-WorkspaceRoot", $WorkspaceRoot,
    "-OutputJson", $OutputJson,
    "-MotionReconstructor", $MotionReconstructor
) + $RemainingArguments

Write-Host "Invoking: pwsh ./scripts/run_exercise_motion_library.ps1 $($arguments -join ' ')"
& (Join-Path $PSScriptRoot "run_exercise_motion_library.ps1") @arguments
exit $LASTEXITCODE
