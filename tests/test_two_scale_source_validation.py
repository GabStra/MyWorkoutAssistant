from __future__ import annotations

import json
from pathlib import Path

from exercise_motion_pkg import bake_and_rank, youtube


def make_review_item(tmp_path: Path, exercise_name: str = "Dumbbell Shrug") -> bake_and_rank.ReviewItem:
    placeholder = tmp_path / "placeholder"
    contract = {
        "status": "generated",
        "contractPolicyVersion": youtube.EXERCISE_MOTION_CONTRACT_POLICY_VERSION,
        "exerciseName": exercise_name,
        "advisoryText": "Source: exercise-specific start. Complete: phase one; phase two.",
        "movementType": "repetition",
        "groundContactMode": "continuous",
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
        "observableMotionSpec": {
            "schemaVersion": 1,
            "primaryMovingRegions": ["hands"],
            "referenceRegions": ["torso"],
            "primaryAxis": "vertical",
            "motionPattern": "joint_travel",
            "requiresReturnToStart": True,
            "oneWayPartialIsInvalid": True,
            "mustShowFullCycle": True,
            "mustBeVisibleRegions": ["hands", "torso"],
        },
        "startPoseConstraints": {
            "supportMode": "standing",
            "handHeight": "hip",
            "torsoOrientation": "upright",
            "kneeState": "extended",
            "stance": "shoulder_width",
        },
        "endPoseConstraints": {
            "supportMode": "standing",
            "handHeight": "hip",
            "torsoOrientation": "upright",
            "kneeState": "extended",
            "stance": "shoulder_width",
        },
        "movementTopology": {
            "schemaVersion": 1,
            "completionMode": "return_to_start",
            "startState": {"id": "start_state", "label": "exercise-specific start posture"},
            "phases": [
                {"id": "phase_01", "label": "exercise-specific outward phase"},
                {"id": "phase_02", "label": "exercise-specific return phase"},
            ],
            "endState": {"id": "end_state", "label": "exercise-specific start posture"},
        },
    }
    return bake_and_rank.ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name=exercise_name,
        candidate_title=exercise_name,
        candidate_workspace=tmp_path,
        preview_html_path=placeholder,
        skeleton_path=placeholder,
        review_video_path=placeholder,
        duration_sec=4.0,
        loop_start_seconds=0.0,
        loop_end_seconds=4.0,
        candidate={"exerciseMotionContract": contract},
    )


def test_two_scale_peak_selector_captures_single_frame_spike_deterministically() -> None:
    scores = [0.0] * 300
    scores[20] = 10.0
    scores[137] = 100.0
    scores[260] = 8.0

    first = bake_and_rank.select_two_scale_motion_peak_indices(scores, 60.0)
    second = bake_and_rank.select_two_scale_motion_peak_indices(scores, 60.0)

    assert 137 in first
    assert first == second


def test_two_scale_source_gate_rejects_when_any_uniform_sheet_has_contamination(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheets = [tmp_path / "uniform-1.jpg", tmp_path / "uniform-2.jpg"]
    motion_sheets = [tmp_path / "motion-1.jpg", tmp_path / "motion-2.jpg"]
    for path in [*uniform_sheets, *motion_sheets]:
        path.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: motion_sheets,
    )
    responses = iter(
        [
            {"verdict": "match", "observedAction": "shrug", "evidence": "visible"},
            {"unrelatedActionVisible": False, "unrelatedTileNumbers": [], "evidence": "clean"},
            {"unrelatedActionVisible": True, "unrelatedTileNumbers": [9], "evidence": "gesture"},
            {"targetExerciseActionVisible": True, "namedEquipmentEngagedStatus": "engaged", "evidence": "visible"},
            {"targetExerciseActionVisible": False, "namedEquipmentEngagedStatus": "absent", "evidence": "absent"},
            {
                "observedExercise": "dumbbell shrug",
                "visibleEquipment": ["dumbbell"],
                "startStateVisible": True,
                "actionPhaseVisible": True,
                "turningPointVisible": True,
                "returnOrFinishVisible": True,
                "complete": True,
                "evidence": "complete",
            },
            {
                "visibleEquipment": ["dumbbell"],
                "orderedPhases": ["shoulders rise", "shoulders lower"],
                "evidence": "dumbbells move with the shoulders",
            },
            topology_response(),
            {
                "corroboratedConflict": False,
                "targetIdentitySupported": "false",
                "requiredEquipmentSupported": "true",
                "completeExecutionSupported": "false",
                "corroboratedContradictions": [],
            },
        ]
    )

    def caption_images(**_kwargs: object) -> str:
        return json.dumps(next(responses))

    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path),
        uniform_sheet_paths=uniform_sheets,
        output_dir=tmp_path / "validation",
        caption_images=caption_images,
    )

    assert result["passed"] is False
    assert "two_scale_source_contamination_detected" in result["rejectionReasons"]


def test_two_scale_source_gate_accepts_when_all_independent_gates_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheets = [tmp_path / "uniform.jpg"]
    motion_sheets = [tmp_path / "motion.jpg"]
    for path in [*uniform_sheets, *motion_sheets]:
        path.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: motion_sheets,
    )
    responses = iter(
        [
            {"verdict": "match", "observedAction": "press", "evidence": "visible"},
            {"unrelatedActionVisible": False, "unrelatedTileNumbers": [], "evidence": "clean"},
            {"targetExerciseActionVisible": True, "namedEquipmentEngagedStatus": "engaged", "evidence": "visible"},
            {
                "observedExercise": "dumbbell bench press",
                "visibleEquipment": ["dumbbell"],
                "startStateVisible": True,
                "actionPhaseVisible": True,
                "turningPointVisible": True,
                "returnOrFinishVisible": True,
                "complete": True,
                "evidence": "complete",
            },
            {
                "visibleEquipment": ["dumbbell"],
                "orderedPhases": ["weights lower", "weights press upward"],
                "evidence": "dumbbells move above the torso",
            },
            topology_response(),
            {
                "corroboratedConflict": False,
                "targetIdentitySupported": "true",
                "requiredEquipmentSupported": "true",
                "completeExecutionSupported": "true",
                "corroboratedContradictions": [],
            },
        ]
    )

    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path, "Dumbbell Bench Press"),
        uniform_sheet_paths=uniform_sheets,
        output_dir=tmp_path / "validation",
        caption_images=lambda **_kwargs: json.dumps(next(responses)),
    )

    assert result["passed"] is True
    assert result["rejectionReasons"] == []


def test_two_scale_source_gate_rejects_vlm_approval_that_contradicts_pose_endpoints(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheet = tmp_path / "uniform.jpg"
    motion_sheet = tmp_path / "motion.jpg"
    uniform_sheet.write_bytes(b"image")
    motion_sheet.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: [motion_sheet],
    )

    responses = iter(
        [
            {"verdict": "match", "observedAction": "jerk", "evidence": "visible"},
            {"unrelatedActionVisible": False, "unrelatedTileNumbers": [], "evidence": "clean"},
            {"targetExerciseActionVisible": True, "namedEquipmentEngagedStatus": "engaged", "evidence": "visible"},
            {"visibleEquipment": ["barbell"], "startState": "start", "orderedPhases": ["phase", "return"], "endState": "end", "startStateVisible": True, "actionPhaseVisible": True, "turningPointVisible": True, "returnOrFinishVisible": True, "complete": True, "evidence": "complete"},
            {"visibleEquipment": ["barbell"], "orderedPhases": ["phase", "return"], "evidence": "complete"},
            {
                "startStateMatch": "match",
                "phaseEvidence": [
                    {"phaseId": "phase_01", "visible": True, "position": 0.25, "evidence": "phase one"},
                    {"phaseId": "phase_02", "visible": True, "position": 0.75, "evidence": "phase two"},
                ],
                "endStateMatch": "match",
                "requiredEquipmentMatch": "match",
                "complete": True,
                "evidence": "complete ordered movement",
            },
            {"corroboratedConflict": False, "targetIdentitySupported": "true", "requiredEquipmentSupported": "true", "completeExecutionSupported": "true", "corroboratedContradictions": []},
        ]
    )
    endpoint_features = {
        "available": True,
        "start": {"available": True, "supportMode": "standing", "handHeight": "above_head", "torsoOrientation": "upright", "kneeState": "flexed", "stance": "split"},
        "end": {"available": True, "supportMode": "standing", "handHeight": "hip", "torsoOrientation": "upright", "kneeState": "extended", "stance": "shoulder_width"},
    }
    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path, "Barbell Split Jerk"),
        uniform_sheet_paths=[uniform_sheet],
        output_dir=tmp_path / "validation",
        caption_images=lambda **_kwargs: json.dumps(next(responses)),
        source_pose_endpoint_features=endpoint_features,
    )

    assert result["gates"]["topology"]["passed"] is True
    assert result["gates"]["deterministicPoseEndpoints"]["passed"] is False
    assert "two_scale_source_pose_contract_mismatch" in result["rejectionReasons"]


def test_two_scale_source_gate_does_not_let_one_blind_outlier_override_corroborated_match(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheets = [tmp_path / "uniform.jpg"]
    motion_sheets = [tmp_path / "motion.jpg"]
    for path in [*uniform_sheets, *motion_sheets]:
        path.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: motion_sheets,
    )


def topology_response(*, equipment_match: str = "match", complete: bool = True) -> dict[str, object]:
    return {
        "startStateMatch": "match" if complete else "mismatch",
        "phaseEvidence": [
            {"phaseId": "phase_01", "visible": complete, "position": 0.25, "evidence": "phase one"},
            {"phaseId": "phase_02", "visible": complete, "position": 0.75, "evidence": "phase two"},
        ],
        "endStateMatch": "match" if complete else "mismatch",
        "requiredEquipmentMatch": equipment_match,
        "complete": complete,
        "evidence": "complete ordered movement" if complete else "required phases are missing",
    }
    responses = iter(
        [
            {"verdict": "match", "observedAction": "rack pull", "evidence": "bar rises to thighs"},
            {"unrelatedActionVisible": False, "unrelatedTileNumbers": [], "evidence": "rack pull"},
            {
                "targetExerciseActionVisible": True,
                "namedEquipmentEngagedStatus": "engaged",
                "evidence": "barbell rises from rack height to standing",
            },
            {
                "visibleEquipment": ["barbell"],
                "orderedPhases": ["bar moves overhead"],
                "startStateVisible": True,
                "actionPhaseVisible": True,
                "turningPointVisible": True,
                "returnOrFinishVisible": True,
                "complete": True,
                "evidence": "outlying clean and jerk description",
            },
            {
                "visibleEquipment": ["barbell"],
                "orderedPhases": ["bar rises from below knees", "body stands", "bar lowers"],
                "evidence": "bar remains below the hips",
            },
            topology_response(),
            {
                "corroboratedConflict": False,
                "targetIdentitySupported": "false",
                "requiredEquipmentSupported": "true",
                "completeExecutionSupported": "false",
                "corroboratedContradictions": [],
            },
        ]
    )

    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path, "Barbell Rack Pull"),
        uniform_sheet_paths=uniform_sheets,
        output_dir=tmp_path / "validation",
        caption_images=lambda **_kwargs: json.dumps(next(responses)),
    )

    assert result["passed"] is True


def test_two_scale_source_gate_rejects_conflicting_exercise_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheets = [tmp_path / "uniform.jpg"]
    motion_sheets = [tmp_path / "motion.jpg"]
    for path in [*uniform_sheets, *motion_sheets]:
        path.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: motion_sheets,
    )
    responses = iter(
        [
            {
                "verdict": "match",
                "observedAction": "barbell split jerk",
                "evidence": "athlete recovers from a split stance",
            },
            {"unrelatedActionVisible": False, "unrelatedTileNumbers": [], "evidence": "clean"},
            {
                "targetExerciseActionVisible": True,
                "namedEquipmentEngagedStatus": "engaged",
                "evidence": "bar held overhead during recovery",
            },
            {
                "observedExercise": "overhead squat to snatch transition",
                "visibleEquipment": ["barbell"],
                "startStateVisible": True,
                "actionPhaseVisible": True,
                "turningPointVisible": True,
                "returnOrFinishVisible": True,
                "complete": True,
                "evidence": "overhead squat to snatch transition",
            },
            {
                "visibleEquipment": ["barbell"],
                "orderedPhases": ["overhead split recovery", "bar lowers"],
                "evidence": "No front-rack dip or drive is visible.",
            },
            topology_response(complete=False),
            {
                "corroboratedConflict": True,
                "targetIdentitySupported": "uncertain",
                "requiredEquipmentSupported": "true",
                "completeExecutionSupported": "false",
                "corroboratedContradictions": [
                    "Two observations lack the split-jerk dip and drive."
                ],
            },
        ]
    )

    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path, "Barbell Split Jerk"),
        uniform_sheet_paths=uniform_sheets,
        output_dir=tmp_path / "validation",
        caption_images=lambda **_kwargs: json.dumps(next(responses)),
    )

    assert result["passed"] is False
    assert "two_scale_source_topology_not_verified" in result["rejectionReasons"]


def test_two_scale_source_gate_requires_target_blind_equipment_observation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheets = [tmp_path / "uniform.jpg"]
    motion_sheets = [tmp_path / "motion.jpg"]
    for path in [*uniform_sheets, *motion_sheets]:
        path.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: motion_sheets,
    )
    responses = iter(
        [
            {"verdict": "match", "observedAction": "push press", "evidence": "arms press overhead"},
            {"unrelatedActionVisible": False, "unrelatedTileNumbers": [], "evidence": "clean"},
            {
                "targetExerciseActionVisible": True,
                "namedEquipmentEngagedStatus": "engaged",
                "evidence": "hands move as if pressing",
            },
            {
                "observedExercise": "unloaded overhead press demonstration",
                "visibleEquipment": ["none"],
                "startState": "standing with empty hands at shoulders",
                "orderedPhases": ["arms extend overhead", "arms lower"],
                "endState": "standing with empty hands at shoulders",
                "startStateVisible": True,
                "actionPhaseVisible": True,
                "turningPointVisible": True,
                "returnOrFinishVisible": True,
                "complete": True,
                "evidence": "No implement is visibly held.",
            },
            {
                "visibleEquipment": ["none"],
                "orderedPhases": ["empty arms extend", "empty arms lower"],
                "evidence": "Hands remain empty.",
            },
            topology_response(equipment_match="mismatch", complete=False),
            {
                "corroboratedConflict": True,
                "targetIdentitySupported": "uncertain",
                "requiredEquipmentSupported": "false",
                "completeExecutionSupported": "true",
                "corroboratedContradictions": [
                    "Both target-blind observations show empty hands."
                ],
            },
        ]
    )

    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path, "Barbell Push Press"),
        uniform_sheet_paths=uniform_sheets,
        output_dir=tmp_path / "validation",
        caption_images=lambda **_kwargs: json.dumps(next(responses)),
    )

    assert result["passed"] is False
    assert "two_scale_source_required_equipment_not_observed" in result["rejectionReasons"]


def test_two_scale_source_gate_accepts_corroborated_target_aware_equipment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheets = [tmp_path / "uniform.jpg"]
    motion_sheets = [tmp_path / "motion-1.jpg", tmp_path / "motion-2.jpg"]
    for path in [*uniform_sheets, *motion_sheets]:
        path.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: motion_sheets,
    )
    responses = iter(
        [
            {
                "verdict": "match",
                "observedAction": "barbell lying triceps extension",
                "evidence": "elbows extend while the bar moves above the face",
            },
            {
                "unrelatedActionVisible": False,
                "unrelatedTileNumbers": [],
                "evidence": "single exercise only",
            },
            {
                "targetExerciseActionVisible": True,
                "namedEquipmentEngagedStatus": "engaged",
                "evidence": "both hands hold one rigid bar",
            },
            {
                "targetExerciseActionVisible": True,
                "namedEquipmentEngagedStatus": "engaged",
                "evidence": "the same rigid bar moves through elbow extension",
            },
            {
                "observedExercise": "lying triceps extension",
                "visibleEquipment": ["dumbbells"],
                "startStateVisible": True,
                "actionPhaseVisible": True,
                "turningPointVisible": True,
                "returnOrFinishVisible": True,
                "complete": True,
                "evidence": "full extension and return are visible",
            },
            {
                "visibleEquipment": ["dumbbells"],
                "orderedPhases": ["elbows flex", "elbows extend"],
                "evidence": "the low-resolution sheet makes the implement ends ambiguous",
            },
            topology_response(equipment_match="match", complete=True),
            {
                "corroboratedConflict": False,
                "targetIdentitySupported": "true",
                "requiredEquipmentSupported": "true",
                "completeExecutionSupported": "true",
                "corroboratedContradictions": [],
            },
        ]
    )

    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path, "Barbell Lying Triceps Extension"),
        uniform_sheet_paths=uniform_sheets,
        output_dir=tmp_path / "validation",
        caption_images=lambda **_kwargs: json.dumps(next(responses)),
    )

    completeness_gate = result["gates"]["completeness"]
    assert completeness_gate["blindRequiredEquipmentObserved"] is False
    assert completeness_gate["targetAwareEquipmentSupportCount"] == 2
    assert completeness_gate["corroboratedTargetAwareEquipmentObserved"] is True
    assert "two_scale_source_required_equipment_not_observed" not in result["rejectionReasons"]
    assert result["passed"] is True


def test_two_scale_endpoint_gate_uses_deterministic_return_cycle_when_identity_is_outlier(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uniform_sheet = tmp_path / "uniform.jpg"
    motion_sheet = tmp_path / "motion.jpg"
    uniform_sheet.write_bytes(b"image")
    motion_sheet.write_bytes(b"image")
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: [motion_sheet],
    )
    responses = iter(
        [
            {
                "verdict": "mismatch",
                "observedAction": "hip bridge with a dumbbell",
                "evidence": "implement was misclassified",
            },
            {
                "unrelatedActionVisible": False,
                "unrelatedTileNumbers": [],
                "evidence": "clean",
            },
            {
                "targetExerciseActionVisible": True,
                "namedEquipmentEngagedStatus": "engaged",
                "evidence": "hips lift while the barbell remains on the hips",
            },
            {
                "visibleEquipment": ["barbell"],
                "startState": "hips low",
                "orderedPhases": ["hips rise", "hips lower"],
                "endState": "hips low",
                "startStateVisible": True,
                "actionPhaseVisible": True,
                "turningPointVisible": True,
                "returnOrFinishVisible": True,
                "complete": True,
                "evidence": "complete return cycle",
            },
            {
                "visibleEquipment": ["barbell"],
                "orderedPhases": ["hips rise", "hips lower"],
                "evidence": "complete return cycle",
            },
            topology_response(),
            {
                "corroboratedConflict": False,
                "targetIdentitySupported": "true",
                "requiredEquipmentSupported": "true",
                "completeExecutionSupported": "true",
                "corroboratedContradictions": [],
            },
        ]
    )
    endpoint_features = {
        "available": True,
        "start": {
            "available": True,
            "supportMode": "standing",
            "handHeight": "hip",
            "torsoOrientation": "upright",
            "kneeState": "extended",
            "stance": "wide",
        },
        "end": {
            "available": True,
            "supportMode": "standing",
            "handHeight": "hip",
            "torsoOrientation": "upright",
            "kneeState": "extended",
            "stance": "wide",
        },
    }

    result = bake_and_rank.validate_two_scale_source_with_caption_images(
        make_review_item(tmp_path, "Barbell Glute Bridge"),
        uniform_sheet_paths=[uniform_sheet],
        output_dir=tmp_path / "validation",
        caption_images=lambda **_kwargs: json.dumps(next(responses)),
        source_pose_endpoint_features=endpoint_features,
        source_phase_metrics={
            "required": True,
            "passed": True,
            "hasCompleteMajorCycle": True,
            "hasSingleMajorCycle": True,
        },
    )

    assert result["gates"]["deterministicPoseEndpoints"]["passed"] is True
    assert result["rejectionReasons"] == ["two_scale_source_identity_failed"]
