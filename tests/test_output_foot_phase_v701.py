import math

import pytest

from exercise_motion_pkg import bake_and_rank


SPEC = {
    "primaryMovingRegions": ["feet"],
    "referenceRegions": ["knees"],
    "primaryAxis": "vertical",
    "motionPattern": "distal_limb_vertical",
}
CONTRACT = {
    "exerciseName": "Calf output phase regression",
    "requiresReturnToStart": True,
    "observableMotionSpec": {**SPEC, "requiresReturnToStart": True},
}


def _payload(pitches, *, body_offset=0.0, ankle_offset=0.0):
    frames = []
    for pitch in pitches:
        forward = [math.cos(pitch), math.sin(pitch), 0.0]
        ankle_y = 0.1 + body_offset + ankle_offset
        foot = [0.1 + 0.12 * forward[0], ankle_y + 0.12 * forward[1], 0.0]
        mirror_foot = [-0.1 + 0.12 * forward[0], ankle_y + 0.12 * forward[1], 0.0]
        frames.append({
            "joints": {
                "pelvis": [0.0, body_offset, 0.0],
                "head": [0.0, 1.7 + body_offset, 0.0],
                "left_knee": [0.1, 0.5 + body_offset, 0.0],
                "right_knee": [-0.1, 0.5 + body_offset, 0.0],
                "left_ankle": [0.1, ankle_y, 0.0],
                "right_ankle": [-0.1, ankle_y, 0.0],
                "left_foot": foot,
                "right_foot": mirror_foot,
            },
            "shoeOrientation": {
                "left": {"forward": list(forward), "side": [0.0, 0.0, 1.0]},
                "right": {"forward": list(forward), "side": [0.0, 0.0, 1.0]},
            },
        })
    return {
        "frames": frames,
        "frameCount": len(frames),
        "jointNames": [
            "pelvis", "head", "left_knee", "right_knee",
            "left_ankle", "right_ankle", "left_foot", "right_foot",
        ],
        "rootJoint": "pelvis",
        "fps": 30,
    }


def _phase(pitches, **kwargs):
    payload = _payload(pitches, **kwargs)
    return bake_and_rank.full_repetition_phase_completeness_metrics_from_payload(
        payload,
        exercise_name="",
        ranking_payload={"exerciseMotionContract": CONTRACT},
    )


def test_genuine_planted_toe_calf_articulation_is_measured_and_passes():
    high = 0.77
    pitches = [0.0, 0.05, 0.35, 0.62, high, high, 0.62, 0.35,
               0.12, 0.03, 0.0, 0.02, 0.01, 0.0, 0.0, 0.0]
    metrics = _phase(pitches)

    assert metrics["dominantJointSelection"] == "observable_output_foot_orientation"
    assert metrics["dominantMotionRange"] == pytest.approx(high, abs=1e-6)
    assert metrics["observableMotionMetrics"]["footOrientationRangeRatio"] == pytest.approx(
        high / math.pi, abs=1e-6
    )
    assert metrics["passed"] is True
    assert metrics["hasSingleMajorCycle"] is True


def test_genuine_articulation_passes_through_retained_camera_projection():
    high = 0.77
    payload = _payload([0.0, 0.05, 0.35, 0.62, high, high, 0.62, 0.35,
                        0.12, 0.03, 0.0, 0.02, 0.01, 0.0, 0.0, 0.0])
    payload["sourcePoseCameraReference"] = {
        "camera": {"cameraRotation": [[1.0, 0.0, 0.0],
                                      [0.0, 1.0, 0.0],
                                      [0.0, 0.0, 1.0]]}
    }
    tracks = bake_and_rank.output_foot_orientation_phase_tracks(payload)
    assert set(tracks) == {"left", "right"}
    for track in tracks.values():
        assert track["projection"] == "source_camera"
        assert track["unit"] == "aspect_corrected_image_plane_radian"
        assert track["range"] == pytest.approx(high, abs=1e-6)

    metrics = bake_and_rank.full_repetition_phase_completeness_metrics_from_payload(
        payload,
        exercise_name="",
        ranking_payload={"exerciseMotionContract": CONTRACT},
    )
    assert metrics["dominantJointSelection"] == "observable_output_foot_orientation"
    assert metrics["passed"] is True


def test_flat_footed_body_translation_is_not_calf_articulation():
    metrics = _phase([0.0] * 16, body_offset=0.0)
    assert metrics["passed"] is False

    translated = _phase([0.0] * 16, body_offset=0.12)
    assert translated["passed"] is False
    assert "output_foot_orientation" in translated["reason"] or (
        translated["reason"] == "dominant_motion_too_small_for_phase_gate"
    )


def test_tiny_three_degree_foot_rotation_stays_rejected():
    small = math.radians(3.0)
    pitches = [0.0, small * 0.2, small * 0.7, small, small, small * 0.7,
               small * 0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    metrics = _phase(pitches)
    assert metrics["passed"] is False


def test_unavailable_foot_observable_is_distinct_from_measured_zero():
    frames = _payload([0.0] * 16)["frames"]
    unavailable = bake_and_rank.materialized_observable_motion_spec_metrics(
        frames, spec=SPEC, body_span=1.7,
    )
    assert unavailable["footOrientationRangeRatio"] is None

    zero_track = {
        "left": {
            "joint": "left_foot_orientation",
            "values": [0.0] * 16,
            "range": 0.0,
            "rangeRatio": 0.0,
            "sampleFrameIndices": list(range(16)),
        }
    }
    measured_zero = bake_and_rank.materialized_observable_motion_spec_metrics(
        frames, spec=SPEC, body_span=1.7, foot_orientation_tracks=zero_track,
    )
    assert measured_zero["footOrientationRangeRatio"] == pytest.approx(0.0)


def test_degenerate_camera_projection_omits_the_foot_track():
    payload = _payload([0.0] * 16)
    for frame in payload["frames"]:
        # Ankle-to-toe parallel to the camera depth axis has no image heading.
        frame["joints"]["left_foot"] = [0.1, 0.1, 0.12]
        frame["joints"]["right_foot"] = [-0.1, 0.1, 0.12]
    payload["sourcePoseCameraReference"] = {
        "camera": {"cameraRotation": [[1.0, 0.0, 0.0],
                                      [0.0, 1.0, 0.0],
                                      [0.0, 0.0, 1.0]]}
    }
    assert bake_and_rank.output_foot_orientation_phase_tracks(payload) == {}
