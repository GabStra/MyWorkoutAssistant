import hashlib
import importlib.util
import json
import subprocess
import sys
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
from exercise_motion_pkg import bake_and_rank as bake


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "build_workout_plan_movement_package.py"
SPEC = importlib.util.spec_from_file_location("build_movement_package", SCRIPT_PATH)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def write_reviewed_movement(movement_path: Path, manifest_path: Path) -> dict:
    movement_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    source_workspace = movement_path.parent / "source_candidate"
    segment_dir = source_workspace / "segment_detection"
    segment_dir.mkdir(parents=True, exist_ok=True)
    source_segment_path = movement_path.parent / "selected_input.mp4"
    source_segment_path.write_bytes(b"retained source segment")
    contact_sheet_path = segment_dir / "source_review_contact_sheet.jpg"
    sample_first_path = segment_dir / "source_review_first.jpg"
    sample_last_path = segment_dir / "source_review_last.jpg"
    contact_sheet_path.write_bytes(b"review contact sheet")
    sample_first_path.write_bytes(b"first sampled frame")
    sample_last_path.write_bytes(b"last sampled frame")
    review_candidate = bake.SourceCutCandidate(
        "A", bake.DetectionWindow(0, 0.0, 8.0), [contact_sheet_path],
        sample_frame_paths=[sample_first_path, sample_last_path],
    )
    candidate = bake.source_cut_candidates_payload([review_candidate])[0]
    frame_evidence = bake.source_cut_review_frame_evidence(
        [review_candidate], source_frame_count=8,
    )
    scorecard = {
        "id": "A", "passed": True, "score": 0.9, "confidence": 0.9,
        "identityMatch": "match", "rejectionReasons": [],
    }
    source_ranking = bake.ranking_to_manifest(bake.LoopRanking(
        score=0.9,
        reasons=[],
        raw_response="reviewed source cut",
        payload={
            "sourceCutScorecardBackend": "clef-systemone",
            "sourceCutReviewVideoPath": str(source_segment_path.resolve()),
            "sourceCutReviewVideoSha256": hashlib.sha256(source_segment_path.read_bytes()).hexdigest(),
            "sourceCutReviewVideoSha256After": hashlib.sha256(source_segment_path.read_bytes()).hexdigest(),
            "sourceCutOriginalVideoPath": str(source_segment_path.resolve()),
            "sourceCutOriginalVideoSha256": hashlib.sha256(source_segment_path.read_bytes()).hexdigest(),
            "sourceCutOriginalVideoSha256After": hashlib.sha256(source_segment_path.read_bytes()).hexdigest(),
            "sourceCutCandidates": [candidate],
            "sourceCutReviewFrameInputs": frame_evidence,
            "sourceCutReviewFrameInputsAfter": frame_evidence,
            "sourceCutScorecardCandidates": [scorecard],
            "selectedCandidateId": "A",
            "selectedScorecard": scorecard,
        },
    ))
    source_manifest = {
        "sourceSelectionPolicyVersion": BUILDER.SOURCE_SELECTION_POLICY_VERSION,
        "preReconstructionSourceValidationEnabled": True,
        "sourcePrepReason": "pre_reconstruction_source_window_choice",
        "exerciseName": "Reviewed exercise",
        "sourceVideoPath": str(source_segment_path),
        "detectionSourceVideoPath": str(source_segment_path),
        "selectedSegmentPath": str(source_segment_path),
        "selectedSegmentSha256": hashlib.sha256(source_segment_path.read_bytes()).hexdigest(),
        "selectedSpan": {"startSeconds": 0.0, "endSeconds": 8.0},
        "exerciseMotionContractEnabled": False,
        "exactSourcePhaseValidation": {
            "validationPolicyVersion": bake.EXACT_SOURCE_PHASE_VALIDATION_POLICY_VERSION,
            "passed": True,
            "sourceVideoPath": str(source_segment_path),
            "sourceVideoSha256": hashlib.sha256(source_segment_path.read_bytes()).hexdigest(),
        },
        "sourceCutRanking": source_ranking,
    }
    source_manifest_path = segment_dir / "segment_selection.json"
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")
    clearance = BUILDER.source_selection_clearance_for_workspace(
        source_workspace,
        required=True,
        expected_exercise_name="Reviewed exercise",
        expected_contract=None,
    )
    assert clearance["status"] == "cleared"
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
                "sourceSelectionPolicyVersion": BUILDER.SOURCE_SELECTION_POLICY_VERSION,
                "preReconstructionSourceValidationEnabled": True,
                "selected": {
                    "exerciseName": "Reviewed exercise",
                    "sourceCandidateWorkspace": str(source_workspace),
                    "selectedInputVideoPath": str(source_segment_path),
                    "sourceSelectionClearance": clearance,
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


@pytest.mark.parametrize("referenced_plan", [False, True])
def test_library_definition_can_receive_movement_ref_and_backup(tmp_path, monkeypatch, referenced_plan):
    movement_path = tmp_path / "movement.json"
    manifest_path = tmp_path / "selection_manifest.json"
    write_reviewed_movement(movement_path, manifest_path)
    package_path = tmp_path / "library.json"
    source = {
        "format": "myworkoutassistant.exercise-library",
        "exerciseDefinitions": [{"id": "definition-a", "name": "Exercise A"}],
    }
    if referenced_plan:
        source["exerciseDefinitions"].append({"id": "unused", "name": "Exercise A"})
        source["workouts"] = [{"workoutComponents": [
            {"type": "Exercise", "id": "one", "exerciseDefinitionId": "definition-a", "sets": [{"reps": 8}]},
            {"type": "Superset", "exercises": [
                {"type": "Exercise", "id": "two", "exerciseDefinitionId": "definition-a", "sets": [{"reps": 12}]},
            ]},
        ]}]
    package_path.write_text(
        json.dumps(
            source
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
    if referenced_plan:
        assert "movementRef" not in output["exerciseDefinitions"][1]
        occurrences = [exercise for exercise, location in BUILDER.iter_package_exercises(output)
                       if not location.startswith("exerciseDefinitions[")]
        assert len(occurrences) == 2
        assert all(exercise.pop("movementRef") == movement_ref for exercise in occurrences)
        output["exerciseDefinitions"][0].pop("movementRef")
        output.pop("exerciseMovements")
        assert output == source


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


def test_packager_never_promotes_raw_not_required_source_clearance(tmp_path):
    movement_path = tmp_path / "movement.json"
    manifest_path = tmp_path / "selection_manifest.json"
    write_reviewed_movement(movement_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preReconstructionSourceValidationEnabled"] = False
    manifest["preReconstructionSourceValidationExplicitlyDisabled"] = True
    manifest["selected"]["sourceSelectionClearance"]["status"] = "not_required"
    manifest["selected"]["sourceSelectionClearance"]["sourcePrepReason"] = "ranked_best_chunk"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="no current source-selection clearance"):
        BUILDER.validate_selected_movement(
            movement_path,
            {"selectionManifestPath": str(manifest_path)},
            summary_path=tmp_path / "summary.json",
            summary={},
        )


@pytest.mark.parametrize(
    "contract",
    [
        {"contractPolicyVersion": bake.EXERCISE_MOTION_CONTRACT_POLICY_VERSION - 1},
        {},
    ],
)
def test_packager_rejects_stale_or_unversioned_advisory_contract_policy(tmp_path, contract):
    movement_path = tmp_path / "movement.json"
    manifest_path = tmp_path / "selection_manifest.json"
    write_reviewed_movement(movement_path, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["selected"]["ranking"]["payload"]["exerciseMotionContract"] = contract
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="exercise motion contract policy version"):
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


def reference_binding_fixture(tmp_path):
    source = {'id': 'source', 'name': 'Reference action', 'exerciseType': 'BODY_WEIGHT',
              'equipmentId': None, 'bodyWeightPercentage': 100,
              'requiredAccessoryEquipmentIds': ['setup'],
              'motionContext': {'exerciseDefinition': {'definingAction': 'Unloaded action',
                  'completionMode': 'return_to_start', 'requiredPhases': ['lower', 'return'],
                  'bilateralExecution': {'legs': 'mirrored'}}}}
    target = json.loads(json.dumps(source))
    target.update(id='target', name='Loaded action', equipmentId='load')
    target['motionContext']['exerciseDefinition']['definingAction'] = 'Loaded action'
    setup = {'id': 'setup', 'type': 'ACCESSORY', 'name': 'Nordic Curl Setup'}
    package = {'exerciseDefinitions': [target], 'equipments': [{'id': 'load', 'type': 'WEIGHTVEST'}],
               'accessoryEquipments': [setup]}
    source_path = tmp_path / 'source.json'
    source_path.write_text(json.dumps({'exerciseDefinitions': [source], 'accessoryEquipments': [setup]}))
    approval_path = tmp_path / 'approval.json'
    approval_path.write_text(json.dumps({'authority': 'explicit_user_approval',
        'exportedExerciseUnchanged': True, 'exerciseName': target['name'],
        'sourceReferenceExerciseName': source['name'], 'allowedDifference': 'External load absent',
        'userAnswer': 'Approved'}))
    binding = {'sourceReferenceDefinitionId': 'source', 'targetDefinitionId': 'target',
        'sourcePlanPath': str(source_path), 'approvalPath': str(approval_path),
        'approvalSha256': hashlib.sha256(approval_path.read_bytes()).hexdigest(),
        'motionReferenceOnly': True, 'allowedDifference': 'external_load_not_shown'}
    for label, value in [('sourceDefinition', source), ('targetDefinition', target),
                         ('sourceMotionContext', source['motionContext']), ('targetMotionContext', target['motionContext'])]:
        binding[label + 'Sha256'] = BUILDER.json_identity(value)
    mapping = tmp_path / 'mapping.json'
    mapping.write_text(json.dumps({'bindings': [binding]}))
    return package, source, binding, mapping


@pytest.mark.parametrize('fault', [None, 'stale_definition', 'stale_approval', 'different_phases', 'duplicate'])
def test_source_reference_binding_validates_identity_and_requirements(tmp_path, fault):
    package, source, binding, mapping = reference_binding_fixture(tmp_path)
    if fault == 'stale_definition':
        package['exerciseDefinitions'][0]['name'] = 'Changed'
    elif fault == 'stale_approval':
        Path(binding['approvalPath']).write_text('{}')
    elif fault == 'different_phases':
        target = package['exerciseDefinitions'][0]
        target['motionContext']['exerciseDefinition']['requiredPhases'] = ['different', 'return']
        binding['targetDefinitionSha256'] = BUILDER.json_identity(target)
        binding['targetMotionContextSha256'] = BUILDER.json_identity(target['motionContext'])
        mapping.write_text(json.dumps({'bindings': [binding]}))
    elif fault == 'duplicate':
        mapping.write_text(json.dumps({'bindings': [binding, binding]}))
    if fault:
        with pytest.raises(ValueError):
            BUILDER.load_source_reference_bindings(mapping, package)
    else:
        assert BUILDER.load_source_reference_bindings(mapping, package)['source']['targetDefinitionId'] == 'target'


def test_source_reference_generation_preserves_target_and_nested_prescriptions(tmp_path):
    package, source, binding, mapping = reference_binding_fixture(tmp_path)
    package['workouts'] = [{'components': [{'exercises': [
        {'id': 'prescription', 'exerciseDefinitionId': 'target', 'equipmentId': 'load', 'reps': 8}]}]}]
    original = json.loads(json.dumps(package))
    generated = BUILDER.source_reference_generation_plan(package, mapping)
    assert package == original
    assert generated['exerciseDefinitions'] == [source]
    assert generated['workouts'][0]['components'][0]['exercises'] == [
        {'id': 'prescription', 'exerciseDefinitionId': 'source', 'equipmentId': None, 'reps': 8}]
    assert generated['motionSourceReferenceBindings'][0]['targetDefinitionId'] == 'target'
    reference_binding = generated['motionSourceReferenceBindings'][0]
    assert reference_binding['sourceReferenceDefinitionId'] == 'source'
    assert reference_binding['sourceMotionContext'] == source['motionContext']
    assert reference_binding['targetMotionContext'] == original['exerciseDefinitions'][0]['motionContext']
    assert reference_binding['motionReferenceOnly'] is True
    assert reference_binding['allowedDifference'] == 'external_load_not_shown'
    assert reference_binding['targetDefinition']['id'] == 'target'
    assert reference_binding['sourceExerciseMotionContext']['exerciseDefinition'] == source['motionContext']['exerciseDefinition']
    assert reference_binding['sourceExerciseMotionContext']['exerciseType'] == 'BODY_WEIGHT'
    assert reference_binding['sourceExerciseMotionContext']['requiredAccessories'] == [
        {'id': 'setup', 'type': 'ACCESSORY', 'name': 'Nordic Curl Setup'}
    ]
    assert reference_binding['sourceExerciseMotionContextSha256'] == BUILDER.json_identity(
        reference_binding['sourceExerciseMotionContext']
    )
    generated['exerciseDefinitions'][0]['name'] = 'changed'
    assert package == original


def test_source_reference_runner_preflight_and_partial_export(tmp_path, monkeypatch):
    package, source, binding, mapping = reference_binding_fixture(tmp_path)
    package_path = tmp_path / 'package.json'
    package_path.write_text(json.dumps(package))
    # A relative approval remains resolvable after the runner persists the mapping.
    binding['sourcePlanPath'] = 'source.json'
    binding['approvalPath'] = 'approval.json'
    mapping.write_text(json.dumps({'bindings': [binding]}))
    harness = tmp_path / 'preflight.ps1'
    harness.write_text(r'''
param($Root, $Target, $Mapping, $Out, $Python)
$ErrorActionPreference = 'Stop'
. (Join-Path $Root 'scripts/reconstruction_compat.ps1')
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $Root 'scripts/run_exercise_motion_workout_plan.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw $errors[0] }
foreach ($name in @('ConvertTo-Slug', 'ConvertTo-StringSet', 'ConvertTo-SlugSet')) {
    $definition = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)[0]
    . ([scriptblock]::Create($definition.Extent.Text))
}
function Resolve-StrictPath($Path) { (Resolve-Path -LiteralPath $Path).Path }
function Invoke-PythonModule { param($Arguments) & $Python @Arguments; if ($LASTEXITCODE) { throw 'Python preflight failed' } }
$resolvedWorkoutPlanJson = $Target; $SourceReferenceMappingJson = $Mapping
$definitionPreflightDirectory = Join-Path $Out 'preflight'; $testScriptRoot = Join-Path $Root 'scripts'
New-Item -ItemType Directory -Path $definitionPreflightDirectory | Out-Null
$onlyExerciseIdSet = ConvertTo-StringSet @('target')
$onlyExerciseNameSet = ConvertTo-StringSet @('Loaded action')
$onlyExerciseSlugSet = ConvertTo-SlugSet @('loaded-action')
$text = $ast.Extent.Text
$start = $text.IndexOf('$resolvedGenerationPlanJson = $resolvedWorkoutPlanJson')
$end = $text.IndexOf('$listArgs = @(', $start)
. ([scriptblock]::Create($text.Substring($start, $end - $start).Replace('$PSScriptRoot', '$testScriptRoot')))
if (-not $onlyExerciseIdSet.Contains('source') -or -not $onlyExerciseNameSet.Contains('reference action') -or -not $onlyExerciseSlugSet.Contains('reference-action')) { throw 'Target filters lost reference identity' }
if (-not $sourceReferenceBuilderArguments.SourceReferenceMappingJson -or -not $sourceReferenceMappingSha256) { throw 'Packaging approval missing' }
Copy-Item -LiteralPath $resolvedGenerationPlanJson -Destination (Join-Path $Out 'generation-plan.json')
$resolvedWorkspaceRoot = Join-Path $Out 'workspace'
New-Item -ItemType Directory -Path $resolvedWorkspaceRoot | Out-Null
$persist = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text.Contains('Workspace source-reference approval mapping differs from this invocation.')
}, $true)
. ([scriptblock]::Create($persist.Extent.Text))
$definitionPreflightListPath = Join-Path $definitionPreflightDirectory 'workout_plan_exercises.json'
$definitionPreflightEffectivePlanPath = Join-Path $definitionPreflightDirectory 'effective_workout_plan.json'
$definitionPreflightReportPath = Join-Path $definitionPreflightDirectory 'definition_readiness_report.json'
$start = $text.IndexOf('$preflightArtifactPaths = @(')
$end = $text.IndexOf('$youtubeBaseArgs = @(', $start)
. ([scriptblock]::Create($text.Substring($start, $end - $start)))
if (Test-Path -LiteralPath $definitionPreflightDirectory) { throw 'Preflight temporary files survived cleanup' }
if (-not (Test-Path -LiteralPath $sourceReferenceBuilderArguments.SourceReferenceMappingJson)) { throw 'Packaging lost its approval mapping during cleanup' }
''')
    result = subprocess.run(['pwsh', '-NoProfile', '-File', str(harness),
        str(SCRIPT_PATH.parents[1]), str(package_path), str(mapping), str(tmp_path), sys.executable],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    normalized = json.loads((tmp_path / 'workspace/source_reference_mapping.json').read_text())
    assert Path(normalized['bindings'][0]['approvalPath']).is_absolute()
    assert json.loads((tmp_path / 'generation-plan.json').read_text())['exerciseDefinitions'] == [source]
    summary = tmp_path / 'summary.json'
    summary.write_text(json.dumps({'exercises': []}))
    output = tmp_path / 'partial.json'
    monkeypatch.setattr('sys.argv', [str(SCRIPT_PATH), '--workout-plan-package-json', str(package_path),
        '--motion-summary-json', str(summary), '--output-json', str(output),
        '--source-reference-mapping-json', str(mapping), '--strict-id-match', '--allow-empty'])
    assert BUILDER.main() == 0
    assert json.loads(output.read_text())['exerciseDefinitions'] == package['exerciseDefinitions']


@pytest.mark.parametrize("selected_time, matches", [
    ("2026-11-12T01:03:18.404851+01:00", True),
    ("2026-11-12T01:03:18.404851+00:00", False),
    ("2026-11-12T00:03:18.404851", False),
    ("not-a-timestamp", False),
])
def test_source_reference_context_keeps_approval_instant_and_other_fields_exact(selected_time, matches):
    expected = {"exerciseDefinition": {"definingAction": "Pull and lower", "review": {
        "approvedAtUtc": "2026-11-12T00:03:18.404851+00:00", "authority": "user",
    }}}
    actual = json.loads(json.dumps(expected))
    actual["exerciseDefinition"]["review"]["approvedAtUtc"] = selected_time
    assert BUILDER.approved_motion_context_matches(actual, expected) is matches
    assert actual["exerciseDefinition"]["review"]["approvedAtUtc"] == selected_time
    actual["exerciseDefinition"]["review"]["authority"] = "different"
    assert not BUILDER.approved_motion_context_matches(actual, expected)


@pytest.mark.parametrize(
    ("exercise_id_is_present", "selected_exercise_id", "rejected"),
    [
        pytest.param(False, None, False, id="missing"),
        pytest.param(True, None, False, id="none"),
        pytest.param(True, "", False, id="empty"),
        pytest.param(True, "other-source", True, id="wrong-id"),
        pytest.param(True, 123, True, id="wrong-type"),
    ],
)
def test_source_reference_attachment_preserves_reviewed_identity_and_target(
    tmp_path, monkeypatch, exercise_id_is_present, selected_exercise_id, rejected
):
    package, source, binding, mapping = reference_binding_fixture(tmp_path)
    movement, manifest = tmp_path / 'movement.json', tmp_path / 'selection_manifest.json'
    write_reviewed_movement(movement, manifest)
    selected_document = json.loads(manifest.read_text())
    selected_document['selected'].update(exerciseName=source['name'],
        candidate={'exerciseMotionContract': {'motionContext': source['motionContext']}})
    if exercise_id_is_present:
        selected_document['selected']['exerciseId'] = selected_exercise_id
    manifest.write_text(json.dumps(selected_document))
    summary = {'exercises': [{'exerciseId': source['id'], 'exerciseName': source['name'],
        'status': 'completed', 'selectedWearSkeletonPath': str(movement), 'selectionManifestPath': str(manifest)}]}
    package_path, summary_path, output = tmp_path / 'package.json', tmp_path / 'summary.json', tmp_path / 'output.json'
    package_path.write_text(json.dumps(package)); summary_path.write_text(json.dumps(summary))
    # The existing independent artifact validator remains mandatory and receives the original source result.
    calls = []
    def validate(path, item, **kwargs):
        calls.append(item['exerciseId'])
        return json.loads(path.read_text())
    monkeypatch.setattr(BUILDER, 'validate_selected_movement', validate)
    monkeypatch.setattr('sys.argv', [str(SCRIPT_PATH), '--workout-plan-package-json', str(package_path),
        '--motion-summary-json', str(summary_path), '--output-json', str(output),
        '--source-reference-mapping-json', str(mapping), '--strict-id-match'])
    if rejected:
        with pytest.raises(ValueError, match='approved source definition/context'):
            BUILDER.main()
        assert not output.exists()
        assert json.loads(manifest.read_text()) == selected_document
        return
    assert BUILDER.main() == 0
    result = json.loads(output.read_text())
    assert calls == ['source']
    definition = result['exerciseDefinitions'][0]
    assert definition.pop('movementRef')['movementId'] == 'exercise-motion:target'
    assert definition == package['exerciseDefinitions'][0]
    assert result['sourceReferenceAttachmentAudit'][0]['sourceReferenceDefinitionId'] == 'source'
    assert json.loads(manifest.read_text()) == selected_document
    summary['exercises'] = []
    summary_path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match='Unused'):
        BUILDER.main()
