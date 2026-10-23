import json
import hashlib
from pathlib import Path
import subprocess

import pytest

from exercise_motion_pkg.definition_review import approve_definition_review, export_definition_review
from exercise_motion_pkg.youtube import (
    exercise_motion_action_definition_review_reason,
    load_workout_plan_exercises,
    normalize_definition_exercise_motion_contract_response,
)


@pytest.fixture
def files(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"exerciseDefinitions": [
        {"id": "pull", "name": "High Pull", "equipmentId": "bar", "motionContext": {"extra": "preserved"}},
        {"id": "other", "name": "Squat"},
    ]}))
    target = load_workout_plan_exercises(plan)[0]
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"exercises": [{
        "exerciseId": target.exercise_id, "exerciseName": target.name, "motionContext": target.motion_context,
        "status": "needs_definition_review",
        "exerciseMotionContract": {
            "status": "generated", "actionDefinitionAuthority": "unresolved",
            "definingAction": "A provisional target action.", "completionMode": "distinct_end_state",
        },
    }]}))
    return dict(plan_path=plan, candidates_path=candidates, exercise_id="pull",
                review_path=tmp_path / "review.json"), tmp_path / "approved-plan.json"


def test_export_edit_approve_reload_and_resume_target_admission(files):
    arguments, output = files
    original = arguments["plan_path"].read_bytes()
    review = export_definition_review(**arguments)
    assert review["status"] == "pending"
    assert "exerciseDefinition" not in load_workout_plan_exercises(arguments["plan_path"])[0].motion_context
    review["definition"]["definingAction"] = "Reviewed defining action and finish."
    arguments["review_path"].write_text(json.dumps(review))
    result = approve_definition_review(**{k: v for k, v in arguments.items() if k != "candidates_path"}, output_path=output)
    assert result["updatedOccurrences"] == 1
    assert arguments["plan_path"].read_bytes() == original
    before, after = json.loads(original), json.loads(output.read_text())
    assert after["exerciseDefinitions"][1] == before["exerciseDefinitions"][1]
    exercise = load_workout_plan_exercises(output)[0]
    assert exercise.motion_context["extra"] == "preserved"
    assert exercise.motion_context["exerciseDefinition"]["review"]["status"] == "approved"
    contract = normalize_definition_exercise_motion_contract_response({
        "movementType": "repetition", "completionMode": "return_to_start",
        "definingAction": "Conflicting model proposal.",
    }, exercise=exercise, source="llm")
    assert contract["definingAction"] == review["definition"]["definingAction"]
    assert contract["completionMode"] == "distinct_end_state"
    assert exercise_motion_action_definition_review_reason(contract) is None


@pytest.mark.parametrize("mutation", ["equipment", "invalid_definition", "wrong_exercise"])
def test_stale_or_invalid_review_never_writes_a_plan(files, mutation):
    arguments, output = files
    review = export_definition_review(**arguments)
    if mutation == "equipment":
        payload = json.loads(arguments["plan_path"].read_text())
        payload["exerciseDefinitions"][0]["equipmentId"] = "different-equipment"
        arguments["plan_path"].write_text(json.dumps(payload))
    elif mutation == "invalid_definition":
        review["definition"]["completionMode"] = "unknown"
    else:
        review["exerciseId"] = "other"
    arguments["review_path"].write_text(json.dumps(review))
    with pytest.raises(ValueError):
        approve_definition_review(**{k: v for k, v in arguments.items() if k != "candidates_path"}, output_path=output)
    assert not output.exists()


def test_existing_review_and_original_plan_cannot_be_overwritten(files):
    arguments, _output = files
    export_definition_review(**arguments)
    with pytest.raises(FileExistsError):
        export_definition_review(**arguments)
    with pytest.raises(FileExistsError):
        approve_definition_review(**{k: v for k, v in arguments.items() if k != "candidates_path"}, output_path=arguments["plan_path"])


def test_cli_requires_explicit_approval_to_persist(files, monkeypatch):
    from exercise_motion_pkg.cli import main

    arguments, output = files
    command = ["exercise-motion", "review-motion-definition",
               "--workout-plan-json", str(arguments["plan_path"]),
               "--exercise-id", arguments["exercise_id"], "--review-json", str(arguments["review_path"])]
    monkeypatch.setattr("sys.argv", [*command, "--candidates-json", str(arguments["candidates_path"])])
    main()
    assert arguments["review_path"].is_file()
    assert not output.exists()
    monkeypatch.setattr("sys.argv", [*command, "--approve", "--out-plan-json", str(output)])
    main()
    approved = load_workout_plan_exercises(output)[0].motion_context["exerciseDefinition"]
    assert approved["review"]["status"] == "approved"


def test_resume_reopens_definition_review_after_target_approval(files, tmp_path):
    arguments, output = files
    export_definition_review(**arguments)
    approve_definition_review(**{k: v for k, v in arguments.items() if k != "candidates_path"}, output_path=output)
    before = hashlib.sha256(arguments["plan_path"].read_bytes()).hexdigest()
    after = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = tmp_path / "pending-discovery.json"
    manifest.write_text(json.dumps({
        "exercises": [{"status": "needs_definition_review", "reason": "target_action_definition_unresolved"}],
        "wrapperDiscoverySignature": {"schemaVersion": 1, "policyVersion": 1,
            "argumentsSha256": "args", "exercisePlanSha256": before, "equipmentSha256": ""},
    }))
    script = tmp_path / "check-resume.ps1"
    script.write_text('''param($Runner, $Candidates, $Before, $After)
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Runner, [ref]$null, [ref]$null)
foreach ($name in @('Get-DefinitionReviewReason', 'Test-DiscoveryStageReady')) {
    $node = $ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}.GetNewClosure(), $true)
    . ([scriptblock]::Create($node.Extent.Text))
}
$discoveryStagePolicyVersion = 1
$item = [pscustomobject]@{exerciseCandidatesPath=$Candidates; discoveryArgumentsSha256='args'; exercisePlanSha256=$Before; equipmentSha256=''}
$payload = Get-Content -LiteralPath $Candidates -Raw | ConvertFrom-Json
if (-not (Test-DiscoveryStageReady -WorkItem $item -Payload $payload)) { throw 'Unchanged pending review was not reusable' }
$item.exercisePlanSha256 = $After
if (Test-DiscoveryStageReady -WorkItem $item -Payload $payload) { throw 'Approved definition did not reopen discovery' }
''')
    runner = Path(__file__).resolve().parents[1] / "scripts/run_exercise_motion_workout_plan.ps1"
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(runner), str(manifest), before, after],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
