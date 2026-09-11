import copy
import math

import numpy as np
import pytest

from exercise_motion_pkg import bake_and_rank as b
from exercise_motion_pkg.pose_fidelity import _endpoint_angle_metrics
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.structural_refinement import constrain_to_source_articulation_envelope
from exercise_motion_pkg.temporal_quality import (
    bone_roll_metrics, introduced_joint_spikes, refresh_motion_bounds, transport_corrected_bone_sides,
)


def roll_clip(angles, swing=False):
    frames = []
    for i, angle in enumerate(angles):
        theta = i * .04 if swing else 0
        axis = np.array([math.sin(theta), math.cos(theta), 0])
        side = np.array([math.cos(theta), -math.sin(theta), 0])
        radians = math.radians(angle)
        side = side * math.cos(radians) + np.cross(axis, side) * math.sin(radians)
        frames.append({"joints": {"left_elbow": [0, 0, 0], "left_wrist": axis.tolist()},
                       "boneSides": {"left_elbow->left_wrist": side.tolist()}})
    return {"fps": 30, "frames": frames}


def test_roll_distinguishes_swing_and_smooth_pronation_from_jump():
    assert not bone_roll_metrics(roll_clip([i * 8 for i in range(60)], swing=True))["severe"]
    angles = [i * 3 for i in range(30)]
    angles[15] += 45
    metrics = bone_roll_metrics(roll_clip(angles, swing=True))
    assert metrics["severe"]
    assert any(event["frameIndex"] == 15 for event in metrics["events"])


def test_missing_orientation_does_not_bridge_gap():
    clip = roll_clip([0] * 8 + [150] * 8)
    clip["frames"][8]["boneSides"] = {}
    assert not bone_roll_metrics(clip)["severe"]


def test_returning_foot_still_counts_as_sliding():
    frames = [{"joints": {"head": [0, 1.8, 0], "pelvis": [0, 1, 0],
                "left_ankle": [.24 * math.sin(math.pi * i / 20), 0, 0],
                "left_foot": [.24 * math.sin(math.pi * i / 20), 0, .1]}} for i in range(21)]
    evidence = {"feet": {"left": {"jointName": "left_ankle", "continuousSupport": True}}}
    assert not b.source_confirmed_support_stationarity_metrics({"frames": frames}, evidence)["passed"]
    for frame in frames:
        frame["joints"]["left_foot"] = [0, 0, .1]
    assert b.source_confirmed_support_stationarity_metrics({"frames": frames}, evidence)["passed"]


def test_bounds_refresh_does_not_move_authoritative_floor():
    payload = {"renderFloorY": -.5, "bounds": {"minY": -99}, "frames": [
        {"joints": {"a": [0, 1, 2], "b": [-1, 3, 4]}}]}
    refresh_motion_bounds(payload)
    assert payload["bounds"]["minY"] == 1
    assert payload["bounds"]["center"] == [-.5, 2, 3]
    assert payload["renderFloorY"] == -.5


def test_processing_spike_does_not_hide_in_clip_average():
    frames = []
    for i in range(9):
        joints = {"pelvis": [i / 10, 0, 0], "head": [i / 10, 2, 0],
                  "left_wrist": [i / 10 + .5, 1, 0]}
        frames.append({"joints": copy.deepcopy(joints), "sourceJoints": joints})
    payload = {"frames": frames}
    assert not introduced_joint_spikes(payload)["severe"]
    frames[4]["joints"]["left_wrist"][2] = .08
    assert introduced_joint_spikes(payload)["severe"]


def test_endpoint_check_exposes_one_bad_limb_phase():
    samples = [(90, 90)] * 40 + [(175, 130)] * 4
    assert _endpoint_angle_metrics(samples)["mismatch"]
    assert not _endpoint_angle_metrics([(x, x + 3) for x, _ in samples])["mismatch"]
    assert not _endpoint_angle_metrics([(175, 130)])["available"]


def test_semantic_rejection_is_not_overridden_by_generic_scores():
    parsed = {"approved": False, "reject": ["gross_pose_reconstruction_error"]}
    metrics = {key: {"passed": True} for key in (
        "sourceVideoFullRepetitionPhaseCompletenessMetrics", "sourceOutputPoseFidelityMetrics",
        "sourceOutputTargetMotionPreservationMetrics")}
    metrics["kinematicPlausibilityMetrics"] = {"severeArtifact": False}
    assert b.reconcile_source_confirmed_contract_contradiction(parsed, item=None,
        deterministic_metrics=metrics, has_source_context=True, exercise_motion_contract={}) == parsed


def test_phase_guard_cannot_borrow_flexion_from_another_part_of_rep():
    def clip(angles):
        frames = [MotionFrame(i / 30, {"left_shoulder": (0., 0., 0.),
                  "left_elbow": (1., 0., 0.), "left_wrist": (
                      1 - math.cos(math.radians(angle)), math.sin(math.radians(angle)), 0.)})
                  for i, angle in enumerate(angles)]
        return MotionClip(30, list(frames[0].joints), frames)
    source, proposal = clip([170, 90]), clip([120, 90])
    _, global_metrics = constrain_to_source_articulation_envelope(source, proposal)
    assert not global_metrics["applied"]
    result, metrics = constrain_to_source_articulation_envelope(source, proposal, phase_tolerance_degrees=10)
    assert metrics["applied"]
    exported = {name: list(point) for name, point in result.frames[0].joints.items()}
    assert b.joint_angle_from_payload(exported, "left_shoulder", "left_elbow", "left_wrist") == pytest.approx(160)


def test_uneven_frame_spacing_does_not_create_processing_jitter():
    frames = []
    for t in [0., .01, .09, .1, .11]:
        joints = {"pelvis": [0, 0, 0], "head": [0, 2, 0], "left_wrist": [t * 10, 1, 0]}
        frames.append({"timeSec": t, "sourceJoints": joints, "joints": copy.deepcopy(joints)})
    assert not introduced_joint_spikes({"frames": frames})["severe"]


def test_ik_rotation_keeps_orientation_attached_to_bone():
    payload = roll_clip([0])
    original = copy.deepcopy(payload["frames"])
    payload["frames"][0]["joints"]["left_wrist"] = [1, 0, 0]
    transport_corrected_bone_sides(original, payload)
    side = payload["frames"][0]["boneSides"]["left_elbow->left_wrist"]
    assert side == pytest.approx([0, -1, 0])


def test_stationary_ground_patch_must_be_on_authoritative_floor():
    frames = [{"joints": {"pelvis": [0, 1, 0], "head": [0, 2, 0],
               "left_ankle": [0, .4, 0], "left_foot": [0, .4, .1]}} for _ in range(10)]
    evidence = {"sharedSupportPlaneY": .8, "contacts": [{
        "jointName": "left_foot", "supportKind": "observed_foot_patch",
        "contactState": "full_sole", "contactMotion": "stationary", "startRatio": 0, "endRatio": 1}]}
    metrics = b.source_confirmed_support_stationarity_metrics({"frames": frames, "renderFloorY": 0}, evidence)
    assert "left_source_confirmed_support_off_floor" in metrics["rejectionReasons"]
