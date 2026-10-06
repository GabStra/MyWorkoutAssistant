import copy

import pytest

from exercise_motion_pkg import bake_and_rank as b
from exercise_motion_pkg import structural_refinement as s
from exercise_motion_pkg import foot_kinematics as f
from exercise_motion_pkg.contact_constraints import InfeasibleContactCorrection
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.target_motion import target_motion_profile_for_exercise


def sample_clip():
    joints = {"pelvis": [0, 1, 0], "neck": [0, 1.7, 0]}
    for side, x in (("left", -.2), ("right", .2)):
        joints.update({f"{side}_hip": [x, 1, 0], f"{side}_knee": [x, .5, .2],
                       f"{side}_ankle": [x, 0, 0], f"{side}_foot": [x, 0, .15]})
    return MotionClip(30, list(joints), [MotionFrame(i / 30, copy.deepcopy(joints)) for i in range(8)])


def test_infeasible_contact_proposal_retains_input(monkeypatch):
    clip = sample_clip()
    original = copy.deepcopy(clip)
    def fail(*args):
        raise InfeasibleContactCorrection("no feasible knee/ankle pose")
    monkeypatch.setattr(f, "solve_rigid_foot_contacts", fail)
    result, report = s.stabilize_forefoot_ground_contacts(clip, {})
    assert result == original
    assert report["applied"] is False
    assert report["reason"] == "infeasible_contact_correction"


def test_unexpected_solver_error_is_not_hidden(monkeypatch):
    def fail(*args):
        raise ValueError("invalid data")
    monkeypatch.setattr(f, "solve_rigid_foot_contacts", fail)
    with pytest.raises(ValueError, match="invalid data"):
        s.stabilize_forefoot_ground_contacts(sample_clip(), {})


@pytest.mark.parametrize("phase", ["Extend the hips and knees while pulling toward the chest",
                                  "Stabilize the front rack with the torso upright"])
def test_multiphase_pull_does_not_require_sustained_hinge(phase):
    contract = {"requiredPhases": ["Hinge at the hips and pull the barbell toward the torso", phase],
                "observableMotionSpec": {"primaryMovingRegions": ["hips", "elbows"],
                                         "motionPattern": "joint_flex_extend"}}
    assert target_motion_profile_for_exercise("Example", contract=contract) is None


def test_contact_correction_cannot_introduce_severe_foot_jumps(monkeypatch):
    clip = sample_clip()
    payload = {"fps": 30, "jointNames": clip.joint_names, "frames": [
        {"timeSec": frame.time_sec, "joints": copy.deepcopy(frame.joints),
         "sourceJoints": copy.deepcopy(frame.joints)} for frame in clip.frames]}
    def bad_proposal(before, evidence):
        after = copy.deepcopy(before)
        for i, frame in enumerate(after.frames):
            point = list(frame.joints["left_foot"])
            point[0] += .005 * i + (.5 if i == 4 else 0)
            frame.joints["left_foot"] = tuple(point)
        return after, {"applied": True}
    monkeypatch.setattr(b, "stabilize_forefoot_ground_contacts", bad_proposal)
    monkeypatch.setattr(b, "stabilize_distal_foot_heading", lambda c: (c, {}))
    result, _ = b.constrain_baked_payload_to_source_articulation(payload, use_controlled_motion_fit=False)
    assert result["postBakeForefootContactConstraint"]["reason"] == "foot_contact_correction_introduces_spikes"
    assert result["frames"][4]["joints"]["left_foot"] == clip.frames[4].joints["left_foot"]


def test_missing_evidence_is_distinct_from_observed_wrong_movement():
    assert b.missing_validation_evidence_reasons(["wrong_variant"]) == []
    assert b.missing_validation_evidence_reasons([
        "wrong_variant", "two_scale_source_specific_contract_missing",
    ]) == ["two_scale_source_specific_contract_missing"]


def test_final_status_summary_preserves_incomplete_review():
    result = {"status": "needs_source_review", "finalSelectionStatus": "old"}
    b.mark_parallel_candidate_final_selection_statuses(
        [result], review_items=[], selected=None, rejected_best=None)
    assert result["finalSelectionStatus"] == "review_incomplete"


def test_core_symmetry_preserves_shoulder_elevation():
    clip = sample_clip()
    for i, frame in enumerate(clip.frames):
        elevation = .08 * (i if i < 4 else 7 - i)
        frame.joints.update({"spine1": (0, 1.2, 0), "neck": (0, 1.7, 0),
                             "left_shoulder": (-.3, 1.5 + elevation, 0),
                             "right_shoulder": (.3, 1.5 + elevation, 0)})
    clip.joint_names[:] = list(clip.frames[0].joints)
    result, _ = s._align_core_for_same_phase_bilateral_travel(
        clip, bilateral_modes={"legs": {"mode": "same_phase_symmetric"}})
    for before, after in zip(clip.frames, result.frames):
        for side in ("left", "right"):
            assert after.joints[f"{side}_shoulder"][1] == pytest.approx(before.joints[f"{side}_shoulder"][1])
