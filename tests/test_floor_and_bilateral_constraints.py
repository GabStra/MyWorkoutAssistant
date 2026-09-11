import copy
from dataclasses import replace

import numpy as np
import pytest

from exercise_motion_pkg.bilateral_evidence import source_arm_symmetry_evidence, exported_arm_symmetry_metrics
from exercise_motion_pkg.cleanup import _authoritative_world_floor_normal
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.video_world_alignment import floor_only_alignment_fallback, apply_rigid_transform_to_clip


def bilateral_source():
    joints = {"left_shoulder": [-.2, 1, 0], "right_shoulder": [.2, 1, 0],
              "left_elbow": [-.4, 1.4, 0], "right_elbow": [.4, 1.4, 0],
              "left_wrist": [-.6, 1.8, 0], "right_wrist": [.6, 1.8, 0],
              "left_hip": [-.15, .4, 0], "right_hip": [.15, .4, 0]}
    return {"frames": [{"joints": copy.deepcopy(joints)} for _ in range(12)]}


def test_stationary_bilateral_hold_needs_no_motion_correlation():
    assert source_arm_symmetry_evidence(bilateral_source())["accepted"]


def test_intentional_asymmetry_and_missing_evidence_are_not_symmetrized():
    source = bilateral_source()
    for frame in source["frames"]:
        frame["joints"]["right_wrist"] = [.1, 1, 0]
    assert not source_arm_symmetry_evidence(source)["accepted"]
    assert not source_arm_symmetry_evidence(None)["accepted"]
    assert not source_arm_symmetry_evidence({"frames": source["frames"][:2]})["accepted"]


def test_side_view_is_insufficient_evidence():
    source = bilateral_source()
    for frame in source["frames"]:
        for point in frame["joints"].values():
            point[0] *= .02
    assert not source_arm_symmetry_evidence(source)["accepted"]


def test_export_validator_detects_pose_corruption_despite_stable_hand_spacing():
    output = bilateral_source()
    for frame in output["frames"]:
        frame["joints"]["right_elbow"] = [.7, 1.2, .4]
    assert exported_arm_symmetry_metrics(output)["severe"]
    assert not exported_arm_symmetry_metrics(bilateral_source())["severe"]


def test_source_confirmed_asymmetry_cannot_be_overruled_by_vision_approval(tmp_path, monkeypatch):
    from exercise_motion_pkg import bake_and_rank as b

    item = b.ReviewItem(
        exercise_index=0, candidate_rank=0, loop_index=-1, exercise_name="Example",
        candidate_title="Example", candidate_workspace=tmp_path, preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json", review_video_path=tmp_path / "review.webm",
        duration_sec=1, loop_start_seconds=0, loop_end_seconds=1, candidate={},
    )
    reason = "materialized_source_confirmed_arm_asymmetry"
    monkeypatch.setattr(b, "materialized_output_acceptance_metrics", lambda *args: {
        "passed": False, "rejectionReasons": [reason],
    })
    monkeypatch.setattr(b, "validate_final_output_with_caption_images",
                        lambda *args, **kwargs: pytest.fail("Hard constraint must block before vision approval"))
    _, ranking = b.apply_materialized_output_acceptance_gate(
        (item, b.LoopRanking(score=.95, reasons=[], payload={}, model_score=.95)),
        request=b.BakeAndRankRequest(candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
                                    wham_repo_path=None, body_model_root=None, final_output_validation=True),
        final_output_caption_images=lambda **kwargs: "{}",
    )
    assert ranking.payload["materializedOutputRejected"]
    assert reason in ranking.payload["materializedHardRejectionReasons"]


def camera_clip():
    frames = []
    for index, lean in enumerate([0, .1, .2, .1, 0]):
        joints = {"left_ankle": (-.1, 0, 0), "right_ankle": (.1, 0, 0),
                  "left_shoulder": (-.2, -1, lean), "right_shoulder": (.2, -1, lean),
                  "pelvis": (0, -.5, 0), "neck": (0, -1.1, lean)}
        frames.append(MotionFrame(index / 30, joints))
    return MotionClip(30, list(joints), frames)


def rotation(degrees):
    angle = np.radians(degrees)
    return np.array([[1, 0, 0], [0, np.cos(angle), -np.sin(angle)], [0, np.sin(angle), np.cos(angle)]])


def test_floor_fallback_removes_camera_pitch_preserving_real_lean_and_distances():
    original = camera_clip()
    tilted = apply_rigid_transform_to_clip(original, rotation=rotation(-15), translation=np.zeros(3))
    result = floor_only_alignment_fallback(tilted, rotation(15))
    assert result is not None
    for expected, actual in zip(original.frames, result.frames):
        for name in original.joint_names:
            assert actual.joints[name] == pytest.approx(expected.joints[name])
    assert floor_only_alignment_fallback(original, rotation(-30)) is None


def test_cleanup_uses_output_floor_coordinates_and_ignores_rejected_transform():
    clip = camera_clip()
    alignment = {"applied": True, "cameraGroundPlane": {"normal": [0, -.9, -.2]},
                 "outputGroundPlane": {"normal": [0, -1, 0]}}
    clip = replace(clip, metadata={"videoWorldAlignment": alignment,
                                  "coordinateNormalization": {"target": "canonical_y_up_world"}})
    assert _authoritative_world_floor_normal(clip) == (0, 1, 0)
    alignment["applied"] = False
    assert _authoritative_world_floor_normal(clip) is None


def test_rigid_implement_uses_rolled_shoulder_plane_without_changing_limb_lengths():
    from exercise_motion_pkg.structural_refinement import _stabilize_rigid_paired_hand_spacing

    source = bilateral_source()
    points = source["frames"][0]["joints"]
    for side, sign in (("left", -1), ("right", 1)):
        points[f"{side}_elbow"] = [sign * .45, 1.25, .12]
        points[f"{side}_hand"] = [sign * .65, 1.88, 0]
    angle = np.radians(25)
    roll = np.array([[np.cos(angle), -np.sin(angle), 0],
                     [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    points = {name: tuple(roll @ point) for name, point in points.items()}
    clip = MotionClip(30, list(points), [MotionFrame(i / 30, dict(points)) for i in range(12)])
    result, _ = _stabilize_rigid_paired_hand_spacing(clip, supported_bilateral=True)
    metrics = exported_arm_symmetry_metrics({"frames": [{"joints": f.joints} for f in result.frames]})
    assert metrics["medianElbowDifferenceDegrees"] < 1e-5
    for before, after in zip(clip.frames, result.frames):
        for side in ("left", "right"):
            for parent, child in (("shoulder", "elbow"), ("elbow", "wrist"), ("wrist", "hand")):
                def length(frame):
                    return np.linalg.norm(np.asarray(frame.joints[f"{side}_{parent}"]) - frame.joints[f"{side}_{child}"])
                assert length(after) == pytest.approx(length(before), abs=1e-7)
