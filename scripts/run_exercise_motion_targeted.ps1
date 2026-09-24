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

    # Workspace root to seed per-exercise discovery review checkpoints from
    # (e.g. the live run's "build/exercise_motion/exercise-library"). The
    # checkpoints are signature-gated: stale entries are ignored by the
    # discovery budget, so seeding already-reviewed candidates only skips
    # re-running identical VLM reviews.
    [string]$SeedDiscoveryCacheFrom = "build/exercise_motion/exercise-library",

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

# Seed discovery review checkpoints so already-reviewed source windows are not
# re-reviewed in the fresh verify workspace. Copy only when the target has no
# checkpoint yet so the verify workspace's own newer history always wins.
$seeded = 0
if (-not [string]::IsNullOrWhiteSpace($SeedDiscoveryCacheFrom)) {
    foreach ($exercise in $selected) {
        $slug = ([string]$exercise.name).ToLowerInvariant() -replace '[^a-z0-9]+', '-'
        $slug = $slug.Trim('-')
        $sourceDir = Join-Path $SeedDiscoveryCacheFrom $slug
        $targetDir = Join-Path $WorkspaceRoot $slug
        if (-not (Test-Path -LiteralPath $sourceDir)) { continue }
        if (-not (Test-Path -LiteralPath $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }
        foreach ($checkpoint in (Get-ChildItem -LiteralPath $sourceDir -Filter "discovery_review_*.json" -File -ErrorAction SilentlyContinue)) {
            $target = Join-Path $targetDir $checkpoint.Name
            if (Test-Path -LiteralPath $target) { continue }
            Copy-Item -LiteralPath $checkpoint.FullName -Destination $target
            $seeded += 1
        }
    }
}
if ($seeded -gt 0) {
    Write-Host "Seeded $seeded discovery review checkpoint(s) from $SeedDiscoveryCacheFrom"
}

if ($BuildLibraryOnly) { return }


Write-Host "Invoking: pwsh ./scripts/run_exercise_motion_library.ps1 -ExerciseLibraryJson $filteredPath -WorkspaceRoot $WorkspaceRoot -OutputJson $OutputJson -MotionReconstructor $MotionReconstructor $($RemainingArguments -join ' ')"
# Named parameters must be passed individually: array splatting binds
# positionally and the library runner disables positional binding.
& (Join-Path $PSScriptRoot "run_exercise_motion_library.ps1") `
    -ExerciseLibraryJson $filteredPath `
    -WorkspaceRoot $WorkspaceRoot `
    -OutputJson $OutputJson `
    -MotionReconstructor $MotionReconstructor `
    @RemainingArguments
exit $LASTEXITCODE
