from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def test_skipped_segment_detection_still_validates_exact_source_without_transcoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from exercise_motion_pkg import bake_and_rank as bake_module
    from exercise_motion_pkg.bake_and_rank import (
        BakeAndRankRequest,
        RankedCandidate,
        exact_source_phase_validation_cache_key,
        prepare_candidate_input_video,
    )
    from exercise_motion_pkg.video_utils import BasicVideoMetadata
    from exercise_motion_pkg.youtube import ExerciseEntry, normalize_exercise_motion_contract

    exercise = ExerciseEntry(
        exercise_id="dumbbell-overhead-press",
        name="Dumbbell Overhead Press",
        slug="dumbbell-overhead-press",
    )
    pose_constraints = {
        "supportMode": "standing",
        "handHeight": "shoulder_chest",
        "torsoOrientation": "upright",
        "kneeState": "extended",
        "stance": "shoulder_width",
    }
    contract = normalize_exercise_motion_contract(
        {
            "movementType": "repetition",
            "groundContactMode": "intermittent",
            "implementSupportMode": "hands_only",
            "completionMode": "return_to_start",
            "requiresReturnToStart": True,
            "startPoseConstraints": pose_constraints,
            "endPoseConstraints": pose_constraints,
            "validStartState": "Standing with dumbbells at shoulder height.",
            "validEndState": "Standing with dumbbells at shoulder height.",
            "requiredPhases": ["Press dumbbells overhead", "Lower dumbbells to shoulders"],
            "primaryMovingRegions": ["elbows", "shoulders"],
            "referenceRegions": ["torso"],
            "mustBeVisibleRegions": ["hands", "elbows", "shoulders", "torso"],
            "primaryAxis": "vertical",
            "motionPattern": "limb_away_from_body",
            "motionContext": {
                "primaryEquipment": {"type": "DUMBBELLS", "name": "Dumbbell Pair"}
            },
        },
        exercise=exercise,
        source="bake_and_rank_llm",
    )

    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"source bytes kept intact")
    source_digest = hashlib.sha256(source_video.read_bytes()).hexdigest()
    reference_path = tmp_path / "retained_exact_source_pose_reference.json"
    reference_path.write_text(
        json.dumps({"schemaVersion": 1, "sourceVideoSha256": source_digest, "pose": {}}),
        encoding="utf-8",
    )
    candidate = RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id=exercise.exercise_id,
        exercise_name=exercise.name,
        exercise_slug=exercise.slug,
        candidate={
            "videoPath": str(source_video),
            "videoId": "local-fixture",
            "title": "Complete press cycle",
            "sourceWindowHint": {"startSeconds": 0.0, "endSeconds": 5.0, "score": 0.99},
            "exerciseMotionContract": contract,
        },
    )
    request = BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=tmp_path / "workspace",
        body_model_root=None,
        detect_source_segment=False,
        pre_reconstruction_source_validation=True,
        reuse_reconstruction_cache=False,
    )
    monkeypatch.setattr(
        bake_module,
        "read_basic_video_metadata",
        lambda _path: BasicVideoMetadata(fps=30.0, frame_count=150, width=640, height=480),
    )
    _payload, cache_key = exact_source_phase_validation_cache_key(
        source_video_path=source_video,
        exercise_name=exercise.name,
        exercise_motion_contract=contract,
    )
    shared_cache_dir = request.workspace / "source-review-cache" / "exact-source-phase"
    bake_module.write_exact_source_phase_validation_cache(
        cache_path=shared_cache_dir / cache_key / "exact_source_phase_validation.json",
        cache_key=cache_key,
        metrics={
            "required": True,
            "passed": True,
            "validationPolicyVersion": bake_module.EXACT_SOURCE_PHASE_VALIDATION_POLICY_VERSION,
            "observableMotionSpec": contract["observableMotionSpec"],
            "sourceVideoPath": str(source_video.resolve()),
            "sourceVideoSha256": source_digest,
            "sourcePoseReferencePath": str(reference_path.resolve()),
        },
    )

    prepared_video = prepare_candidate_input_video(
        candidate,
        request=request,
        source_cut_caption_images=lambda **_kwargs: pytest.fail(
            "a valid exact-source cache entry should avoid model work"
        ),
        exercise_motion_contract_resolver=lambda _candidate: contract,
    )

    assert hashlib.sha256(prepared_video.read_bytes()).hexdigest() == source_digest
    candidate_workspace = request.workspace / candidate.workspace_slug
    promoted_reference = (
        candidate_workspace / "segment_detection" / "exact_source_pose_reference.json"
    )
    assert promoted_reference.is_file()
    selection_manifest = json.loads(
        (candidate_workspace / "segment_detection" / "segment_selection.json").read_text(
            encoding="utf-8"
        )
    )
    assert selection_manifest["selectedSegmentMaterialization"] == "source_copy_full_range"
    assert selection_manifest["exactSourcePhaseValidation"]["cacheStatus"] == "reused"
    assert selection_manifest["exactSourcePhaseValidationPassed"] is True
