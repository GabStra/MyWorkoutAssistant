"""Stationary joint pivots must not hide observed limb movement."""
from exercise_motion_pkg import bake_and_rank, pose_prefilter
from exercise_motion_pkg.source_observability import associated_observable_moving_regions
from exercise_motion_pkg.video_utils import BasicVideoMetadata

BODY = 300.0
SPEC = {
    "primaryMovingRegions": ["shoulders"],
    "referenceRegions": ["torso"],
    "primaryAxis": "horizontal",
    "motionPattern": "limb_away_from_body",
}
MOVING = [0.0, 7.2, 14.4, 21.6, 28.8, 36.0]
STATIC = [0.0] * len(MOVING)


def _keypoints(arm_offset: float) -> dict[str, tuple[float, float, float]]:
    return {
        "left_shoulder": (100.0, 100.0, 0.95),
        "right_shoulder": (200.0, 100.0, 0.95),
        "left_hip": (100.0, 200.0, 0.95),
        "right_hip": (200.0, 200.0, 0.95),
        "left_elbow": (80.0 + arm_offset, 140.0, 0.95),
        "left_wrist": (60.0 + arm_offset, 170.0, 0.95),
        "right_elbow": (220.0, 140.0, 0.95),
        "right_wrist": (240.0, 170.0, 0.95),
    }


def _pose_detections(offsets):
    return [
        pose_prefilter.PoseDetection(
            bbox=(0.0, 0.0, 300.0, BODY), keypoints=_keypoints(offset), confidence=0.95)
        for offset in offsets
    ]


def _materialized_frame(arm_offset: float):
    return {
        "joints": {
            name: [point[0], point[1], 0.0]
            for name, point in _keypoints(arm_offset).items()
        }
    }


def test_associated_regions_are_pattern_scoped():
    assert associated_observable_moving_regions(["shoulders"], "limb_away_from_body") == [
        "shoulders", "upper_limb",
    ]
    assert associated_observable_moving_regions(["hips"], "limb_away_from_body") == [
        "hips", "lower_limb",
    ]
    assert associated_observable_moving_regions(["shoulders"], "other") == ["shoulders"]


def test_source_pose_prefilter_measures_moving_arm_for_stationary_shoulders():
    metrics = pose_prefilter.target_pose_observable_motion_spec_observability(
        _pose_detections(MOVING),
        metadata=BasicVideoMetadata(fps=30., frame_count=len(MOVING), width=300, height=300),
        spec=SPEC
    )
    assert metrics["passed"], metrics
    assert metrics["measuredPrimaryMotionRegions"] == ["shoulders", "upper_limb"]
    assert metrics["targetMotionRangeRatio"] >= metrics["minTargetMotionRangeRatio"]


def test_source_pose_prefilter_rejects_repeated_static_pose():
    metrics = pose_prefilter.target_pose_observable_motion_spec_observability(
        _pose_detections(STATIC),
        metadata=BasicVideoMetadata(fps=30., frame_count=len(STATIC), width=300, height=300),
        spec=SPEC
    )
    assert not metrics["passed"]
    assert "weak_observable_target_motion" in metrics["failureReasons"]


def test_materialized_metrics_use_same_associated_mapping():
    frames = [_materialized_frame(offset) for offset in MOVING]
    metrics = bake_and_rank.materialized_observable_motion_spec_metrics(
        frames, spec=SPEC, body_span=BODY
    )
    assert metrics["passed"], metrics
    assert metrics["measuredPrimaryMotionRegions"] == ["shoulders", "upper_limb"]
    track = bake_and_rank.dominant_observable_motion_phase_track(
        frames, spec=SPEC, body_span=BODY
    )
    assert track is not None
    assert float(track.get("range") or 0.0) > 0.0


def test_materialized_metrics_reject_repeated_static_pose():
    frames = [_materialized_frame(offset) for offset in STATIC]
    metrics = bake_and_rank.materialized_observable_motion_spec_metrics(
        frames, spec=SPEC, body_span=BODY
    )
    assert not metrics["passed"]
    assert "weak_observable_target_motion" in metrics["failureReasons"]


def test_reference_shoulders_keep_literal_marker_semantics():
    spec = {**SPEC, "referenceRegions": ["shoulders"]}
    frames = [_materialized_frame(offset) for offset in MOVING]
    metrics = bake_and_rank.materialized_observable_motion_spec_metrics(
        frames, spec=spec, body_span=BODY
    )
    assert metrics["passed"], metrics
    assert metrics["referenceRegions"] == ["shoulders"]
    assert metrics["relativeMotionRangeRatio"] > 0.05


def test_unrelated_motion_pattern_is_unchanged():
    spec = {**SPEC, "motionPattern": "other"}
    frames = [_materialized_frame(offset) for offset in MOVING]
    metrics = bake_and_rank.materialized_observable_motion_spec_metrics(
        frames, spec=spec, body_span=BODY
    )
    assert not metrics["passed"]
    assert metrics["measuredPrimaryMotionRegions"] == ["shoulders"]


def test_static_challenge_focus_includes_associated_limb_only_when_present():
    regions = bake_and_rank._static_challenge_focus_regions(
        {"observableMotionSpec": SPEC}
    )
    assert regions == ("shoulders", "upper_limb", "torso")
    other = bake_and_rank._static_challenge_focus_regions(
        {"observableMotionSpec": {**SPEC, "motionPattern": "other"}}
    )
    assert other == ("shoulders", "torso")
