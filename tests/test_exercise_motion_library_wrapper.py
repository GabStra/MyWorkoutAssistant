import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[1]


def test_library_run_state_counts_the_normalized_exercise_inventory():
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", r'''
$ErrorActionPreference = 'Stop'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path (Get-Location) 'scripts/run_exercise_motion_library.ps1'), [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Write-RunState')) {
    $node = $ast.Find({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name
    }.GetNewClosure(), $true)
    . ([scriptblock]::Create($node.Extent.Text))
}
function Write-AtomicJson { param($Path, $Value); $script:state = $Value }
$script:LibraryStateInitialized = $true
$script:LibraryRunOutcome = 'running'
$definitionExerciseList = [pscustomobject]@{ exercises = @(1..306 | ForEach-Object { @{ id = $_ } }) }
$resolvedLibraryJson = 'must-not-reparse-the-raw-library-format.json'
$statePath = 'unused.json'
Write-RunState -Phase 'first_pass_started'
$script:state | ConvertTo-Json -Depth 8 -Compress
'''],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True, timeout=30,
    )
    state = json.loads(result.stdout)
    assert state["totalExerciseCount"] == 306
    assert state["pendingExerciseCount"] == 306
    assert state["terminalExerciseCount"] == 0


@pytest.mark.parametrize("exclusive_gpu_device, shared_server", [("", False), ("1", True)])
def test_library_wrapper_shares_vision_for_split_gpu_with_one_wave(
    monkeypatch, exclusive_gpu_device, shared_server
):
    monkeypatch.setenv("EXERCISE_MOTION_EXCLUSIVE_GPU_DEVICE", exclusive_gpu_device)
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", r'''
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path (Get-Location) 'scripts/run_exercise_motion_library.ps1'), [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$nodes = $ast.FindAll({ param($node)
    ($node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -in @('$exclusiveGpuIndex', '$hasExclusiveGpuLane')) -or
    ($node -is [System.Management.Automation.Language.IfStatementAst] -and
        $node.Clauses[0].Item1.Extent.Text.Contains('$hasExclusiveGpuLane'))
}, $true)
if ($nodes.Count -ne 3) { throw 'Missing library GPU residency forwarding branch.' }
$MaxConcurrentStagedWaves = 1
$DisableStagedWaves = $false
$code = '$runnerArguments = @()' + "`n" + (($nodes | ForEach-Object { $_.Extent.Text }) -join "`n")
$code += "`n" + 'ConvertTo-Json -InputObject @($runnerArguments) -Compress'
& ([scriptblock]::Create($code))
'''],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True, timeout=30,
    )
    assert ("-SharedLlamaServer" in json.loads(result.stdout)) is shared_server


def _copy_library_wrapper_scripts(scripts_dir: Path) -> None:
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "run_exercise_motion_library.ps1",
        "motion_library_logging.ps1",
        "motion_run_interrupt.ps1",
        "motion_validation_policy.ps1",
        "reconstruction_compat.ps1",
    ):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts_dir / name)
    package_dir = scripts_dir.parent / "exercise_motion_pkg"
    package_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / "exercise_motion_pkg" / "bake_and_rank.py",
        package_dir / "bake_and_rank.py",
    )


def test_library_wrapper_acknowledges_ctrl_c_immediately() -> None:
    script = (REPO_ROOT / "scripts" / "run_exercise_motion_library.ps1").read_text(encoding="utf-8")
    interrupt = (REPO_ROOT / "scripts" / "motion_run_interrupt.ps1").read_text(encoding="utf-8")

    assert "motion_run_interrupt.ps1" in script
    assert "MotionRunInterrupt" in interrupt
    assert "RegisterOnce" in interrupt
    assert "Register-MotionInterruptHandler -Silent" in script
    assert "[switch]$Silent" in interrupt
    assert "TryAcknowledge" in interrupt
    assert "Ctrl+C received. Stopping the motion run" in interrupt
    assert "Exit-IfMotionRunInterrupted" in script
    assert "exit 130" in script


def test_library_wrapper_runs_bounded_then_deferred_and_resumes_phase(tmp_path):
    scripts_dir = tmp_path / "scripts"
    _copy_library_wrapper_scripts(scripts_dir)
    (scripts_dir / "run_exercise_motion_workout_plan.ps1").write_text(
        r'''param(
    [string]$WorkoutPlanJson,
    [string]$EquipmentJson,
    [string]$WorkspaceRoot,
    [string]$IncrementalMobilePackageOutputJson,
    [switch]$ReuseExistingSelected,
    [switch]$DeferAfterFirstAttempt,
    [switch]$CpuPrefetchDuringBake,
    [int]$PrefetchWorkers,
    [int]$PrefetchQueueDepth,
    [int]$StagedWaveSize,
    [int]$DiscoveryCandidateBudget,
    [int]$DiscoveryTimeBudgetSeconds,
    [string]$GpuDiscoveryBakeOverlap,
    [bool]$WarmGvhmrWorker,
    [bool]$KeepLlamaCppServer,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArguments = @()
)
New-Item -ItemType Directory -Force -Path $WorkspaceRoot | Out-Null
$call = [ordered]@{
    defer = [bool]$DeferAfterFirstAttempt
    reuse = [bool]$ReuseExistingSelected
    cpuPrefetch = [bool]$CpuPrefetchDuringBake
    prefetchWorkers = $PrefetchWorkers
    prefetchQueueDepth = $PrefetchQueueDepth
    stagedWaveSize = $StagedWaveSize
    discoveryCandidateBudget = $DiscoveryCandidateBudget
    discoveryTimeBudgetSeconds = $DiscoveryTimeBudgetSeconds
    gpuDiscoveryBakeOverlap = $GpuDiscoveryBakeOverlap
    warmGvhmrWorker = $WarmGvhmrWorker
    keepLlamaCppServer = $KeepLlamaCppServer
    incrementalMobilePackageOutputJson = $IncrementalMobilePackageOutputJson
}
$call | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $WorkspaceRoot 'calls.jsonl')
$status = if ($DeferAfterFirstAttempt) { 'no_selection' } else { 'completed' }
$summary = [ordered]@{
    exercises = @([ordered]@{
        exerciseId = 'exercise-a'
        exerciseName = 'Exercise A'
        status = $status
        selectedWearSkeletonPath = if ($status -eq 'completed') { 'movement.json' } else { $null }
    })
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $WorkspaceRoot 'workout_motion_generation_summary.json')
''',
        encoding="utf-8",
    )
    (scripts_dir / "build_workout_plan_movement_package.ps1").write_text(
        r'''param(
    [string]$WorkoutPlanPackageJson,
    [string]$MotionSummaryJson,
    [string]$OutputJson,
    [switch]$StrictIdMatch,
    [switch]$AllowEmpty
)
Copy-Item -Force -LiteralPath $MotionSummaryJson -Destination $OutputJson
''',
        encoding="utf-8",
    )
    library_path = tmp_path / "library.json"
    equipment_path = tmp_path / "equipment.json"
    library_path.write_text('{"exerciseDefinitions": []}', encoding="utf-8")
    equipment_path.write_text('{"equipments": []}', encoding="utf-8")
    workspace = tmp_path / "workspace"
    output_path = tmp_path / "library_with_movements.json"
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(scripts_dir / "run_exercise_motion_library.ps1"),
        "-ExerciseLibraryJson",
        str(library_path),
        "-EquipmentJson",
        str(equipment_path),
        "-WorkspaceRoot",
        str(workspace),
        "-OutputJson",
        str(output_path),
    ]

    subprocess.run(command, check=True, capture_output=True, text=True)

    calls = [json.loads(line) for line in (workspace / "calls.jsonl").read_text().splitlines()]
    assert calls == [
        {"defer": True, "reuse": True, "cpuPrefetch": True, "prefetchWorkers": 8, "prefetchQueueDepth": 40, "stagedWaveSize": 8, "discoveryCandidateBudget": 24, "discoveryTimeBudgetSeconds": 300, "gpuDiscoveryBakeOverlap": "auto", "warmGvhmrWorker": True, "keepLlamaCppServer": True, "incrementalMobilePackageOutputJson": str(output_path)},
        {"defer": True, "reuse": True, "cpuPrefetch": True, "prefetchWorkers": 8, "prefetchQueueDepth": 40, "stagedWaveSize": 8, "discoveryCandidateBudget": 96, "discoveryTimeBudgetSeconds": 900, "gpuDiscoveryBakeOverlap": "auto", "warmGvhmrWorker": True, "keepLlamaCppServer": True, "incrementalMobilePackageOutputJson": str(output_path)},
    ]
    first_pass = json.loads((workspace / "exercise_library_first_pass_summary.json").read_text())
    assert first_pass["exercises"][0]["status"] == "postponed"
    assert first_pass["exercises"][0]["firstPassStatus"] == "no_selection"
    state = json.loads((workspace / "exercise_library_run_state.json").read_text())
    assert state["phase"] == "deferred_pass_completed"
    assert output_path.exists()

    subprocess.run(command, check=True, capture_output=True, text=True)

    resumed_calls = [
        json.loads(line) for line in (workspace / "calls.jsonl").read_text().splitlines()
    ]
    assert resumed_calls[-1] == {
        "defer": True,
        "reuse": True,
        "cpuPrefetch": True,
        "prefetchWorkers": 8,
        "prefetchQueueDepth": 40,
        "stagedWaveSize": 8,
        "discoveryCandidateBudget": 96,
        "discoveryTimeBudgetSeconds": 900,
        "gpuDiscoveryBakeOverlap": "auto",
        "warmGvhmrWorker": True,
        "keepLlamaCppServer": True,
        "incrementalMobilePackageOutputJson": str(output_path),
    }
    assert len(resumed_calls) == 3


def test_library_wrapper_phase_resume_is_invalidated_by_quality_policy_change(tmp_path):
    scripts_dir = tmp_path / "scripts"
    _copy_library_wrapper_scripts(scripts_dir)
    wrapper_path = scripts_dir / "run_exercise_motion_library.ps1"
    (scripts_dir / "run_exercise_motion_workout_plan.ps1").write_text(
        r'''param(
    [string]$WorkoutPlanJson,
    [string]$EquipmentJson,
    [string]$WorkspaceRoot,
    [string]$IncrementalMobilePackageOutputJson,
    [switch]$ReuseExistingSelected,
    [switch]$DeferAfterFirstAttempt,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArguments = @()
)
New-Item -ItemType Directory -Force -Path $WorkspaceRoot | Out-Null
[ordered]@{ defer = [bool]$DeferAfterFirstAttempt } |
    ConvertTo-Json -Compress |
    Add-Content -LiteralPath (Join-Path $WorkspaceRoot 'calls.jsonl')
[ordered]@{ exercises = @() } |
    ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath (Join-Path $WorkspaceRoot 'workout_motion_generation_summary.json')
''',
        encoding="utf-8",
    )
    (scripts_dir / "build_workout_plan_movement_package.ps1").write_text(
        r'''param(
    [string]$WorkoutPlanPackageJson,
    [string]$MotionSummaryJson,
    [string]$OutputJson,
    [switch]$StrictIdMatch,
    [switch]$AllowEmpty
)
Copy-Item -Force -LiteralPath $MotionSummaryJson -Destination $OutputJson
''',
        encoding="utf-8",
    )
    library_path = tmp_path / "library.json"
    equipment_path = tmp_path / "equipment.json"
    library_path.write_text('{"exerciseDefinitions": []}', encoding="utf-8")
    equipment_path.write_text('{"equipments": []}', encoding="utf-8")
    workspace = tmp_path / "workspace"
    output_path = tmp_path / "library_with_movements.json"
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(wrapper_path),
        "-ExerciseLibraryJson",
        str(library_path),
        "-EquipmentJson",
        str(equipment_path),
        "-WorkspaceRoot",
        str(workspace),
        "-OutputJson",
        str(output_path),
    ]

    subprocess.run(command, check=True, capture_output=True, text=True)
    assert len((workspace / "calls.jsonl").read_text().splitlines()) == 2

    wrapper_text = wrapper_path.read_text(encoding="utf-8")
    current_policy_match = re.search(
        r"\$SelectionValidationPolicyVersion = (\d+)",
        wrapper_text,
    )
    assert current_policy_match is not None
    current_policy = int(current_policy_match.group(1))
    wrapper_path.write_text(
        wrapper_text.replace(
            f"$SelectionValidationPolicyVersion = {current_policy}",
            f"$SelectionValidationPolicyVersion = {current_policy + 1}",
        ),
        encoding="utf-8",
    )
    subprocess.run(command, check=True, capture_output=True, text=True)

    calls = [json.loads(line) for line in (workspace / "calls.jsonl").read_text().splitlines()]
    assert [call["defer"] for call in calls] == [True, False, True, False]


def test_library_wrapper_publishes_revalidation_before_regeneration(tmp_path):
    scripts_dir = tmp_path / "scripts"
    _copy_library_wrapper_scripts(scripts_dir)
    (scripts_dir / "run_exercise_motion_workout_plan.ps1").write_text(
        "exit 1\n",
        encoding="utf-8",
    )
    (scripts_dir / "build_workout_plan_movement_package.ps1").write_text(
        r'''param(
    [string]$WorkoutPlanPackageJson,
    [string]$MotionSummaryJson,
    [string]$OutputJson,
    [switch]$StrictIdMatch,
    [switch]$AllowEmpty
)
Copy-Item -Force -LiteralPath $MotionSummaryJson -Destination $OutputJson
''',
        encoding="utf-8",
    )
    fake_python = scripts_dir / "fake_python.ps1"
    fake_python.write_text(
        r'''param([Parameter(ValueFromRemainingArguments = $true)][object[]]$Arguments)
$outputIndex = [Array]::IndexOf($Arguments, '--out-json')
$reportPath = [string]$Arguments[$outputIndex + 1]
[ordered]@{
    selectionValidationPolicyVersion = 43
    results = @([ordered]@{
        exerciseId = 'exercise-a'
        exerciseName = 'Exercise A'
        status = 'invalid'
    })
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
''',
        encoding="utf-8",
    )
    fake_python_command = scripts_dir / "fake_python.cmd"
    fake_python_command.write_text(
        '@echo off\r\npwsh -NoProfile -File "%~dp0fake_python.ps1" %*\r\nexit /b %ERRORLEVEL%\r\n',
        encoding="utf-8",
    )
    library_path = tmp_path / "library.json"
    equipment_path = tmp_path / "equipment.json"
    library_path.write_text('{"exerciseDefinitions": []}', encoding="utf-8")
    equipment_path.write_text('{"equipments": []}', encoding="utf-8")
    workspace = tmp_path / "workspace"
    selected_dir = workspace / "exercise-a" / "selected"
    selected_dir.mkdir(parents=True)
    (selected_dir / "selection_manifest.json").write_text("{}", encoding="utf-8")
    (selected_dir / "revalidation.json").write_text(
        json.dumps(
            {
                "selectionValidationPolicyVersion": 30,
                "retainedSelectedArtifactFallbackVersion": 2,
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "library_with_movements.json"
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(scripts_dir / "run_exercise_motion_library.ps1"),
        "-ExerciseLibraryJson",
        str(library_path),
        "-EquipmentJson",
        str(equipment_path),
        "-WorkspaceRoot",
        str(workspace),
        "-OutputJson",
        str(output_path),
        "-PythonCommand",
        str(fake_python_command),
    ]

    completed = subprocess.run(command, capture_output=True, text=True)

    assert completed.returncode != 0
    package = json.loads(output_path.read_text(encoding="utf-8-sig"))
    assert package["results"][0]["status"] == "invalid"


def test_library_wrapper_omits_equipment_json_when_library_embeds_it(tmp_path):
    scripts_dir = tmp_path / "scripts"
    _copy_library_wrapper_scripts(scripts_dir)
    (scripts_dir / "run_exercise_motion_workout_plan.ps1").write_text(
        r'''param(
    [string]$WorkoutPlanJson,
    [string]$EquipmentJson,
    [string]$WorkspaceRoot,
    [string]$IncrementalMobilePackageOutputJson,
    [switch]$ReuseExistingSelected,
    [switch]$DeferAfterFirstAttempt,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArguments = @()
)
New-Item -ItemType Directory -Force -Path $WorkspaceRoot | Out-Null
[ordered]@{
    defer = [bool]$DeferAfterFirstAttempt
    equipmentJson = $EquipmentJson
} | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $WorkspaceRoot 'calls.jsonl')
[ordered]@{ exercises = @() } |
    ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath (Join-Path $WorkspaceRoot 'workout_motion_generation_summary.json')
''',
        encoding="utf-8",
    )
    (scripts_dir / "build_workout_plan_movement_package.ps1").write_text(
        r'''param(
    [string]$WorkoutPlanPackageJson,
    [string]$MotionSummaryJson,
    [string]$OutputJson,
    [switch]$StrictIdMatch,
    [switch]$AllowEmpty
)
Copy-Item -Force -LiteralPath $MotionSummaryJson -Destination $OutputJson
''',
        encoding="utf-8",
    )
    library_path = tmp_path / "library.json"
    library_path.write_text(
        json.dumps(
            {
                "exerciseDefinitions": [],
                "equipments": [{"id": "bar", "name": "Barbell", "type": "BARBELL"}],
                "accessoryEquipments": [],
            }
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    output_path = tmp_path / "library_with_movements.json"
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(scripts_dir / "run_exercise_motion_library.ps1"),
        "-ExerciseLibraryJson",
        str(library_path),
        "-WorkspaceRoot",
        str(workspace),
        "-OutputJson",
        str(output_path),
    ]

    subprocess.run(command, check=True, capture_output=True, text=True)

    calls = [json.loads(line) for line in (workspace / "calls.jsonl").read_text().splitlines()]
    assert all(not call.get("equipmentJson") for call in calls)
    state = json.loads((workspace / "exercise_library_run_state.json").read_text())
    assert state["sourceEquipmentPath"] is None
    assert output_path.exists()
