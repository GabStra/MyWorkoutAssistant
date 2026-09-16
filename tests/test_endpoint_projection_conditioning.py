"""Endpoint projection conditioning: same-space angles + soft demotion policy."""

from exercise_motion_pkg import pose_fidelity as fidelity
from exercise_motion_pkg import bake_and_rank as bake


def _standing_source_joints():
    return {
        "left_shoulder": (0.0, 0.0),
        "right_shoulder": (1.0, 0.0),
        "left_hip": (0.0, 1.0),
        "right_hip": (1.0, 1.0),
        "left_knee": (0.0, 2.0),
        "right_knee": (1.0, 2.0),
        "left_elbow": (-0.5, 0.0),
        "left_wrist": (-1.0, 0.0),
        "right_elbow": (1.5, 0.0),
        "right_wrist": (2.0, 0.0),
    }


def test_endpoint_angles_use_camera_frame_3d_lifted_source_space():
    joints = _standing_source_joints()
    source = [{"time": i / 9, "joints": joints} for i in range(10)]
    output = [
        {
            "time": i / 9,
            "joints": {name: (x, -y, 0.0) for name, (x, y) in joints.items()},
        }
        for i in range(10)
    ]
    metrics = fidelity._projection_metrics(
        source, output, horizontal_vector=(1.0, 0.0), mirror=False, swap_bilateral=False
    )
    assert metrics["angleComparisonSpace"] == "camera_frame_3d_lifted_source"
    elbow = metrics["perAngleEndpointMetrics"]["left_elbow"]
    assert elbow["conditionedSampleCount"] == 10
    assert elbow["available"]
    assert not elbow["mismatch"]
    assert (metrics["p90JointAngleErrorDegrees"] or 0.0) < 1.0


def test_degenerate_3d_limb_is_unresolved_not_a_confident_angle_mismatch():
    joints = _standing_source_joints()
    source = [{"time": i / 9, "joints": joints} for i in range(10)]
    output_joints = {name: (x, -y, 0.0) for name, (x, y) in joints.items()}
    # Collapse the 3D elbow chain so bone-length conditioning fails in camera frame.
    output_joints["left_elbow"] = output_joints["left_shoulder"]
    output_joints["left_wrist"] = output_joints["left_shoulder"]
    output = [{"time": i / 9, "joints": output_joints} for i in range(10)]
    metrics = fidelity._projection_metrics(
        source, output, horizontal_vector=(1.0, 0.0), mirror=False, swap_bilateral=False
    )
    elbow = metrics["perAngleEndpointMetrics"]["left_elbow"]
    assert elbow["comparisonUnresolved"]
    assert not elbow["mismatch"]
    assert elbow["outputForeshortenedSampleCount"] == 10
    assert elbow["conditionedSampleCount"] == 0


def test_image_foreshortened_but_valid_3d_limb_stays_comparable():
    """Depth-heavy limbs must still compare in camera-frame 3D, not 2D projection."""
    joints = _standing_source_joints()
    source = [{"time": i / 9, "joints": joints} for i in range(10)]
    output_joints = {name: (x, -y, 0.0) for name, (x, y) in joints.items()}
    # End-on in the image plane, but still a real 3D limb.
    output_joints["left_elbow"] = (-0.01, -0.01, 0.5)
    output = [{"time": i / 9, "joints": output_joints} for i in range(10)]
    metrics = fidelity._projection_metrics(
        source, output, horizontal_vector=(1.0, 0.0), mirror=False, swap_bilateral=False
    )
    elbow = metrics["perAngleEndpointMetrics"]["left_elbow"]
    assert metrics["angleComparisonSpace"] == "camera_frame_3d_lifted_source"
    assert elbow["conditionedSampleCount"] == 10
    assert not elbow["comparisonUnresolved"]


def test_visible_persistent_angle_error_still_fails():
    assert fidelity._endpoint_angle_metrics([(90.0, 140.0)] * 10)["mismatch"]


def test_foreshortened_endpoint_mismatch_is_not_a_hard_kill():
    metrics = {
        "perJointMedianErrorBodyRatio": {
            "right_shoulder": 0.014,
            "right_elbow": 0.038,
            "right_wrist": 0.048,
        },
        "perAngleEndpointMetrics": {
            "right_elbow": {
                "mismatch": True,
                "maxEndpointMedianErrorDegrees": 36.9,
                "conditionedSampleCount": 20,
                "outputForeshortenedSampleCount": 7,
            }
        },
    }
    assert not bake.materialized_source_endpoint_mismatch_is_decisive(
        metrics, "right_elbow"
    )


def test_clear_unforeshortened_endpoint_mismatch_still_hard_kills():
    metrics = {
        "perJointMedianErrorBodyRatio": {
            "right_shoulder": 0.02,
            "right_elbow": 0.08,
            "right_wrist": 0.09,
        },
        "perAngleEndpointMetrics": {
            "right_elbow": {
                "mismatch": True,
                "maxEndpointMedianErrorDegrees": 40.0,
                "conditionedSampleCount": 24,
                "outputForeshortenedSampleCount": 0,
            }
        },
    }
    assert bake.materialized_source_endpoint_mismatch_is_decisive(metrics, "right_elbow")


def test_weak_spatial_endpoint_mismatch_is_not_a_hard_kill():
    metrics = {
        "perJointMedianErrorBodyRatio": {
            "right_shoulder": 0.014,
            "right_elbow": 0.038,
            "right_wrist": 0.048,
        },
        "perAngleEndpointMetrics": {
            "right_elbow": {
                "mismatch": True,
                "maxEndpointMedianErrorDegrees": 36.9,
                "conditionedSampleCount": 24,
                "outputForeshortenedSampleCount": 0,
            }
        },
    }
    assert not bake.materialized_source_endpoint_mismatch_is_decisive(
        metrics, "right_elbow"
    )


def test_unresolved_projection_cannot_silently_approve_required_fidelity(monkeypatch):
    monkeypatch.setattr(
        bake, "source_pose_comparison_payload_for_materialized_output", lambda _: ({}, {})
    )
    monkeypatch.setattr(
        fidelity,
        "registered_camera_pose_fidelity_metrics",
        lambda *args: {
            "available": True,
            "comparableFrameRatio": 1.0,
            "perAngleEndpointMetrics": {
                "left_elbow": {"mismatch": False, "comparisonUnresolved": True}
            },
        },
    )
    result = bake.materialized_source_pose_fidelity_metrics(
        source_pose_payload={}, output_motion_payload={}, required=True
    )
    assert not result["passed"]
    assert "materialized_source_pose_fidelity_unavailable" in result["rejectionReasons"]
