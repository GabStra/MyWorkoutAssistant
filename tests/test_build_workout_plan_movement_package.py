import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "build_workout_plan_movement_package.py"
SPEC = importlib.util.spec_from_file_location("build_movement_package", SCRIPT_PATH)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_iter_package_exercises_includes_library_definitions():
    package = {
        "exerciseDefinitions": [
            {"id": "definition-a", "name": "Exercise A"},
            {"id": "definition-b", "name": "Exercise B"},
        ]
    }

    entries = list(BUILDER.iter_package_exercises(package))

    assert entries == [
        (package["exerciseDefinitions"][0], "exerciseDefinitions[0]"),
        (package["exerciseDefinitions"][1], "exerciseDefinitions[1]"),
    ]


def test_library_definition_can_receive_movement_ref_and_backup(tmp_path, monkeypatch):
    movement_path = tmp_path / "movement.json"
    movement_path.write_text(json.dumps({"frames": []}), encoding="utf-8")
    package_path = tmp_path / "library.json"
    package_path.write_text(
        json.dumps(
            {
                "format": "myworkoutassistant.exercise-library",
                "exerciseDefinitions": [{"id": "definition-a", "name": "Exercise A"}],
            }
        ),
        encoding="utf-8",
    )
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "exercises": [
                    {
                        "exerciseId": "definition-a",
                        "exerciseName": "Exercise A",
                        "selectedWearSkeletonPath": str(movement_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "library-with-movements.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT_PATH),
            "--workout-plan-package-json",
            str(package_path),
            "--motion-summary-json",
            str(summary_path),
            "--output-json",
            str(output_path),
            "--strict-id-match",
        ],
    )

    assert BUILDER.main() == 0

    output = json.loads(output_path.read_text(encoding="utf-8"))
    movement_ref = output["exerciseDefinitions"][0]["movementRef"]
    assert movement_ref["movementId"] == "exercise-motion:definition-a"
    assert output["exerciseMovements"][0]["movementRef"] == movement_ref


def test_explicitly_unapproved_results_are_not_packaged(tmp_path, monkeypatch):
    approved_movement_path = tmp_path / "approved.json"
    approved_movement_path.write_text(json.dumps({"frames": ["approved"]}), encoding="utf-8")
    manual_movement_path = tmp_path / "manual.json"
    manual_movement_path.write_text(json.dumps({"frames": ["manual"]}), encoding="utf-8")
    package_path = tmp_path / "library.json"
    package_path.write_text(
        json.dumps(
            {
                "exerciseDefinitions": [
                    {"id": "approved", "name": "Approved Exercise"},
                    {"id": "manual", "name": "Manual Exercise"},
                ]
            }
        ),
        encoding="utf-8",
    )
    summary_path = tmp_path / "checkpoint.json"
    summary_path.write_text(
        json.dumps(
            {
                "exercises": [
                    {
                        "exerciseId": "approved",
                        "exerciseName": "Approved Exercise",
                        "status": "completed",
                        "selectedWearSkeletonPath": str(approved_movement_path),
                    },
                    {
                        "exerciseId": "manual",
                        "exerciseName": "Manual Exercise",
                        "status": "needs_manual_review",
                        "selectedWearSkeletonPath": str(manual_movement_path),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "library-with-movements.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT_PATH),
            "--workout-plan-package-json",
            str(package_path),
            "--motion-summary-json",
            str(summary_path),
            "--output-json",
            str(output_path),
            "--strict-id-match",
        ],
    )

    assert BUILDER.main() == 0

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert "movementRef" in output["exerciseDefinitions"][0]
    assert "movementRef" not in output["exerciseDefinitions"][1]
    assert len(output["exerciseMovements"]) == 1
    assert not list(tmp_path.glob(".library-with-movements.json.*.tmp"))


def test_revalidation_report_packages_only_valid_selected_workspace(tmp_path, monkeypatch):
    exercise_workspace = tmp_path / "workspace" / "exercise-a"
    selected_dir = exercise_workspace / "selected"
    selected_dir.mkdir(parents=True)
    movement_path = selected_dir / "exercise_a_wear_skeleton.json"
    movement_path.write_text(json.dumps({"frames": ["valid"]}), encoding="utf-8")
    package_path = tmp_path / "library.json"
    package_path.write_text(
        json.dumps(
            {
                "exerciseDefinitions": [
                    {"id": "definition-a", "name": "Exercise A"},
                    {"id": "definition-b", "name": "Exercise B"},
                ]
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "revalidation.json"
    report_path.write_text(
        json.dumps(
            {
                "workspaceRoot": str(tmp_path / "workspace"),
                "results": [
                    {
                        "exerciseId": "definition-a",
                        "status": "valid",
                        "workspace": str(exercise_workspace),
                    },
                    {
                        "exerciseId": "definition-b",
                        "status": "needs_manual_review",
                        "workspace": str(tmp_path / "workspace" / "exercise-b"),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "library-with-movements.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT_PATH),
            "--workout-plan-package-json",
            str(package_path),
            "--motion-summary-json",
            str(report_path),
            "--output-json",
            str(output_path),
            "--strict-id-match",
        ],
    )

    assert BUILDER.main() == 0

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["exerciseDefinitions"][0]["movementRef"]["movementId"] == (
        "exercise-motion:definition-a"
    )
    assert "movementRef" not in output["exerciseDefinitions"][1]
    assert len(output["exerciseMovements"]) == 1
