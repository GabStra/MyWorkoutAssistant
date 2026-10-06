import copy
import json
from pathlib import Path

import pytest

from exercise_motion_pkg import bake_and_rank as bake


@pytest.mark.parametrize("artifacts,consecutive,allowed", [
    (["root_translation_discontinuity"], 0, True),
    (["root_translation_discontinuity", "limb_velocity_spike_penalty"], 2, True),
    (["root_translation_discontinuity", "limb_velocity_spike_penalty"], 3, False),
    (["root_translation_discontinuity", "bone_length_instability_penalty"], 0, False),
    (["root_translation_discontinuity", "joint_angle_spike_penalty"], 0, False),
])
def test_only_cleanup_owned_raw_defects_reach_repair(artifacts, consecutive, allowed):
    gate = {"rejectionReasons": ["raw_wham_kinematic_artifact"],
            "kinematicPlausibilityMetrics": {
                "artifactReasons": artifacts,
                "distalStep": {"thresholdExceedanceCount": 4,
                               "maxConsecutiveThresholdExceedanceCount": consecutive}}}
    assert bake.raw_wham_motion_gate_allows_cleaned_recovery(gate) is allowed
    gate["rejectionReasons"].append("raw_wham_motion_unreadable")
    assert not bake.raw_wham_motion_gate_allows_cleaned_recovery(gate)


@pytest.mark.parametrize("repaired", [False, True])
def test_real_translation_gate_requires_successful_cleanup(tmp_path, repaired):
    joints = json.loads((Path(__file__).parent / "fixtures/sequence_stabilization_stance.json").read_text())["joints"]
    clean = {"fps": 30, "jointNames": list(joints), "frames": [
        {"timeSec": i / 30, "joints": copy.deepcopy(joints)} for i in range(12)]}
    raw = copy.deepcopy(clean)
    for i, frame in enumerate(raw["frames"]):
        for point in frame["joints"].values():
            point[2] += .15 if i % 2 else 0.
    raw_path, cleaned_path = tmp_path / "raw.json", tmp_path / "cleaned.json"
    raw_path.write_text(json.dumps(raw))
    cleaned_path.write_text(json.dumps(clean if repaired else raw))
    gate = bake.evaluate_generated_motion_recovery_gate(
        raw_motion_path=raw_path, cleaned_motion_path=cleaned_path,
        source_pose_reference_path=tmp_path / "absent.json",
        exercise_motion_contract=None, exercise_name="Squat")
    assert "root_translation_discontinuity" in gate["kinematicPlausibilityMetrics"]["artifactReasons"]
    assert gate["cleanedRecovery"]["attempted"]
    assert gate["passed"] is repaired
