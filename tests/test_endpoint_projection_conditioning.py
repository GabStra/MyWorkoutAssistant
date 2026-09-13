from exercise_motion_pkg import pose_fidelity as fidelity
from exercise_motion_pkg import bake_and_rank as bake


def test_end_on_output_limb_is_unresolved_not_a_confident_angle_mismatch():
    joints = {"left_shoulder": (0., 0.), "right_shoulder": (1., 0.),
              "left_hip": (0., 1.), "right_hip": (1., 1.),
              "left_knee": (0., 2.), "right_knee": (1., 2.),
              "left_elbow": (-.5, 0.), "left_wrist": (-1., 0.)}
    source = [{"time": i / 9, "joints": joints} for i in range(10)]
    output_joints = {name: (x, -y, 0.) for name, (x, y) in joints.items()}
    output_joints["left_elbow"] = (-.01, -.01, .5)
    output = [{"time": i / 9, "joints": output_joints} for i in range(10)]
    metrics = fidelity._projection_metrics(source, output, horizontal_vector=(1., 0.), mirror=False, swap_bilateral=False)
    elbow = metrics["perAngleEndpointMetrics"]["left_elbow"]
    assert elbow["comparisonUnresolved"]
    assert not elbow["mismatch"]
    assert elbow["outputForeshortenedSampleCount"] == 10


def test_visible_persistent_angle_error_still_fails():
    assert fidelity._endpoint_angle_metrics([(90., 140.)] * 10)["mismatch"]


def test_unresolved_projection_cannot_silently_approve_required_fidelity(monkeypatch):
    monkeypatch.setattr(bake, "source_pose_comparison_payload_for_materialized_output", lambda _: ({}, {}))
    monkeypatch.setattr(fidelity, "registered_camera_pose_fidelity_metrics", lambda *args: {
        "available": True, "comparableFrameRatio": 1.,
        "perAngleEndpointMetrics": {"left_elbow": {"mismatch": False, "comparisonUnresolved": True}},
    })
    result = bake.materialized_source_pose_fidelity_metrics(source_pose_payload={}, output_motion_payload={}, required=True)
    assert not result["passed"]
    assert "materialized_source_pose_fidelity_unavailable" in result["rejectionReasons"]
