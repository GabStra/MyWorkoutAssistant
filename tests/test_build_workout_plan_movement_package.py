import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from exercise_motion_pkg.artifact_state import (
    FULL_CLIP_BAKE,
    baked_payload_identity,
    build_artifact_state,
    validate_packaged_artifact_state,
)
from exercise_motion_pkg.review_window import (
    artifact_review_selection,
    frame_timestamps_for_indices,
    sample_review_frame_indices,
)


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "build_workout_plan_movement_package.py"
SPEC = importlib.util.spec_from_file_location("build_movement_package", SCRIPT_PATH)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def write_reviewed_movement(movement_path: Path, manifest_path: Path) -> dict:
    movement_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "wear_skeleton_v1",
        "title": "Reviewed exercise",
        "source": {"kind": "test"},
        "fps": 30,
        "frameCount": 2,
        "jointNames": ["root"],
        "rootJoint": "root",
        "loop": {"enabled": False},
        "frames": [{"root": [0, 0, 0]}, {"root": [0, 0.1, 0]}],
    }
    payload["artifactState"] = build_artifact_state(
        artifact_class=FULL_CLIP_BAKE,
        selection_class=FULL_CLIP_BAKE,
        required_class=FULL_CLIP_BAKE,
        selection_evidence={"fullClipBake": baked_payload_identity(payload)},
    )
    review_indices = sample_review_frame_indices(payload, 2)
    review_window = {
        "schemaVersion": 1,
        "frameCount": len(payload["frames"]),
        "frameIndices": review_indices,
        "frameTimesSec": frame_timestamps_for_indices(payload, review_indices),
        "sampling": {"policy": "evenly_spaced_v1", "requestedFrameCount": 2},
        "selection": artifact_review_selection(payload["artifactState"], payload),
    }
    movement_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    review_identity = {
        "sha256": hashlib.sha256(movement_path.read_bytes()).hexdigest(),
        "frameCount": len(payload["frames"]),
    }
    manifest_path.write_text(
        json.dumps(
            {
                "selectionStatus": "selected",
                "selected": {
                    "artifactState": payload["artifactState"],
                    "selectedSkeletonIdentity": review_identity,
                    "ranking": {
                        "payload": {
                            "finalOutputValidation": {
                                "passed": True,
                                "artifactClassGate": {
                                    "passed": True,
                                    "artifactClass": FULL_CLIP_BAKE,
                                },
                                "renderEvidence": {
                                    "available": True,
                                    "passed": True,
                                    "skeletonIdentity": review_identity,
                                    "reviewWindow": review_window,
                                },
                            }
                        }
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return payload


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
    manifest_path = tmp_path / "selection_manifest.json"
    write_reviewed_movement(movement_path, manifest_path)
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
                        "status": "completed",
                        "selectedWearSkeletonPath": str(movement_path),
                        "selectionManifestPath": str(manifest_path),
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
    packaged_state = output["exerciseMovements"][0]["packagedArtifactState"]
    validate_packaged_artifact_state(
        packaged_state,
        movement_state=json.loads(movement_path.read_text(encoding="utf-8"))["artifactState"],
    )
    assert packaged_state["history"] == ["full_clip_bake", "packaged_movement"]


def test_summary_without_explicit_success_status_is_not_approved():
    assert not BUILDER.is_approved_summary_item(
        {"selectedWearSkeletonPath": "movement.json"}
    )


def test_explicitly_unapproved_results_are_not_packaged(tmp_path, monkeypatch):
    approved_movement_path = tmp_path / "approved.json"
    approved_manifest_path = tmp_path / "approved-selection-manifest.json"
    write_reviewed_movement(approved_movement_path, approved_manifest_path)
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
                        "selectionManifestPath": str(approved_manifest_path),
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
    write_reviewed_movement(movement_path, selected_dir / "selection_manifest.json")
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


def test_packager_rejects_skeleton_that_differs_from_reviewed_bytes(tmp_path, monkeypatch):
    movement_path = tmp_path / "movement.json"
    manifest_path = tmp_path / "selection_manifest.json"
    payload = write_reviewed_movement(movement_path, manifest_path)
    payload["title"] = "Changed after review"
    movement_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    package_path = tmp_path / "library.json"
    package_path.write_text(
        json.dumps({"exerciseDefinitions": [{"id": "definition-a", "name": "Exercise A"}]}),
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
                        "status": "completed",
                        "selectedWearSkeletonPath": str(movement_path),
                        "selectionManifestPath": str(manifest_path),
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

    with pytest.raises(ValueError, match="differs from the final reviewed artifact"):
        BUILDER.main()


def test_packager_rejects_manifest_without_selected_disposition(tmp_path):
    movement_path = tmp_path / "movement.json"
    manifest_path = tmp_path / "selection_manifest.json"
    write_reviewed_movement(movement_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["selectionStatus"] = "needs_manual_review"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="does not approve a selected movement"):
        BUILDER.validate_selected_movement(
            movement_path,
            {"selectionManifestPath": str(manifest_path)},
            summary_path=tmp_path / "summary.json",
            summary={},
        )


@pytest.mark.parametrize("failed_gate", ["final_validation", "render_evidence"])
def test_packager_rejects_manifest_without_passing_final_render_validation(
    tmp_path,
    failed_gate: str,
) -> None:
    movement_path = tmp_path / "movement.json"
    manifest_path = tmp_path / "selection_manifest.json"
    write_reviewed_movement(movement_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    final_validation = manifest["selected"]["ranking"]["payload"]["finalOutputValidation"]
    if failed_gate == "final_validation":
        final_validation["passed"] = False
    else:
        final_validation["renderEvidence"]["passed"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="no passing final render validation"):
        BUILDER.validate_selected_movement(
            movement_path,
            {"selectionManifestPath": str(manifest_path)},
            summary_path=tmp_path / "summary.json",
            summary={},
        )


@pytest.mark.parametrize("defect", ["missing", "invalid_frame", "wrong_interval"])
def test_packager_rejects_manifest_with_invalid_final_review_window(
    tmp_path,
    defect: str,
) -> None:
    movement_path = tmp_path / "movement.json"
    manifest_path = tmp_path / "selection_manifest.json"
    write_reviewed_movement(movement_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review_window = manifest["selected"]["ranking"]["payload"]["finalOutputValidation"]["renderEvidence"]["reviewWindow"]
    if defect == "missing":
        review_window.pop("frameIndices")
    elif defect == "invalid_frame":
        review_window["frameIndices"][-1] = 2
    else:
        review_window["selection"]["interval"]["endFrame"] = 99
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="final review window"):
        BUILDER.validate_selected_movement(
            movement_path,
            {"selectionManifestPath": str(manifest_path)},
            summary_path=tmp_path / "summary.json",
            summary={},
        )
