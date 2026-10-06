import pytest

from exercise_motion_pkg import bake_and_rank as module


def test_off_floor_stationary_foot_is_not_reported_as_sliding():
    frames = [{"joints": {"head": [0., 1.8, 0.], "pelvis": [0., 1., 0.],
                          "left_ankle": [0., .2, 0.], "right_ankle": [.2, 0., 0.]}}
              for _ in range(20)]
    evidence = {"contacts": [{"jointName": "left_ankle", "supportKind": "foot",
                              "surfaceKind": "floor", "startRatio": 0., "endRatio": 1.,
                              "confidence": .9}]}
    metrics = module.source_confirmed_support_stationarity_metrics(
        {"frames": frames, "renderFloorY": 0.}, evidence)
    assert metrics["passed"] is False
    assert metrics["rejectionReasons"] == ["left_source_confirmed_support_off_floor"]
    assert metrics["sides"]["left"]["stationary"] is True


def test_final_review_does_not_inherit_invented_accessory_mechanics():
    prompt = module.build_final_output_source_contract_prompt_section({
        "advisoryText": "The rack must hold the rear foot.",
        "motionContext": {"requiredAccessories": ["Squat Rack"], "exerciseType": "BODY_WEIGHT"},
        "startPose": "Rear foot fixed to rack", "endPose": "Rear foot stays on rack",
    })
    assert "Squat Rack" in prompt
    assert "rear foot" not in prompt.lower()
    assert "Accessory presence does not specify" in prompt


def test_repair_comparison_can_keep_a_common_physical_scale():
    frames = [{"joints": {"pelvis": [0., 1., 0.], "head": [0., 2., 0.],
                          "left_ankle": [0., 0., 0.]}} for _ in range(4)]
    payload = {"jointNames": list(frames[0]["joints"]), "frames": frames}
    metrics = module.compute_kinematic_plausibility_metrics_from_payload(
        payload, comparison_body_height=1.5)
    assert metrics["bodyHeight"] == pytest.approx(1.5)
