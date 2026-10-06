from dataclasses import replace
import math
import json

import numpy as np
import pytest

from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.limb_bend_repair import repair_limb_bend_bursts
from exercise_motion_pkg import structural_refinement as s


def hinge_clip(angles, *, leg=False, turn=False):
    frames = []
    root, mid, end = ("left_hip", "left_knee", "left_ankle") if leg else ("left_shoulder", "left_elbow", "left_wrist")
    for i, angle in enumerate(angles):
        radians = math.radians(angle)
        joints = {"pelvis": (0., 1., 0.), "neck": (0., 2., 0.),
                  "left_shoulder": (-.25, 1.8, 0.), "right_shoulder": (.25, 1.8, 0.),
                  root: (0., 0., 0.), mid: (.5 * math.cos(radians), .5 * math.sin(radians), .5),
                  end: (0., 0., 1.)}
        if turn:
            # Whole-body yaw must not be interpreted as a hinge flip.
            theta = i * .04
            rotation = np.array([[math.cos(theta), 0, math.sin(theta)], [0, 1, 0], [-math.sin(theta), 0, math.cos(theta)]])
            joints = {name: tuple(rotation @ point) for name, point in joints.items()}
        frames.append(MotionFrame(i / 30., joints))
    return MotionClip(30., list(frames[0].joints), frames), (root, mid, end)


@pytest.mark.parametrize("leg", [False, True])
@pytest.mark.parametrize("length", [1, 3])
def test_short_hinge_flip_is_repaired_without_moving_endpoints(leg, length):
    angles = [0.] * 20
    angles[7:7 + length] = [150.] * length
    original, (root, mid, end) = hinge_clip(angles, leg=leg)
    repaired, report = repair_limb_bend_bursts(original)
    assert report["applied"]
    for i, (before, after) in enumerate(zip(original.frames, repaired.frames)):
        assert after.joints[root] == before.joints[root]
        assert after.joints[end] == before.joints[end]
        for a, b in ((root, mid), (mid, end)):
            assert math.dist(after.joints[a], after.joints[b]) == pytest.approx(math.dist(before.joints[a], before.joints[b]), abs=1e-9)
        if 7 <= i < 7 + length:
            assert after.joints[mid] == pytest.approx((.5, 0., .5), abs=1e-8)
        else:
            assert after.joints == before.joints


@pytest.mark.parametrize("angles", [[0.] * 6 + [150.] * 8 + [0.] * 6, [i * 8. for i in range(20)]])
def test_sustained_or_smooth_rotation_is_not_repaired(angles):
    clip, _ = hinge_clip(angles, turn=True)
    repaired, report = repair_limb_bend_bursts(clip)
    assert not report["applied"]
    assert repaired is clip


def test_burst_repair_is_equivariant_to_body_turn():
    angles = [0.] * 20
    angles[7:9] = [150.] * 2
    original, (_, mid, _) = hinge_clip(angles)
    turning, _ = hinge_clip(angles, turn=True)
    repaired, _ = repair_limb_bend_bursts(original)
    turned_repair, report = repair_limb_bend_bursts(turning)
    assert report["applied"]
    for i, (plain, turned) in enumerate(zip(repaired.frames, turned_repair.frames)):
        theta = i * .04
        rotation = np.array([[math.cos(theta), 0, math.sin(theta)], [0, 1, 0], [-math.sin(theta), 0, math.cos(theta)]])
        assert turned.joints[mid] == pytest.approx(rotation @ plain.joints[mid], abs=1e-8)


def test_near_straight_chain_does_not_supply_a_bend_direction():
    clip, (_, mid, _) = hinge_clip([0.] * 7 + [150.] + [0.] * 12)
    frames = [replace(frame, joints={**frame.joints, mid: (frame.joints[mid][0] * .0001,
                  frame.joints[mid][1] * .0001, .5)}) for frame in clip.frames]
    clip = replace(clip, frames=frames)
    assert repair_limb_bend_bursts(clip)[0] is clip


def test_burst_repair_does_not_bridge_missing_time():
    clip, _ = hinge_clip([0.] * 7 + [150.] + [0.] * 12)
    frames = [replace(frame, time_sec=frame.time_sec + (1. if i >= 7 else 0.))
              for i, frame in enumerate(clip.frames)]
    clip = replace(clip, frames=frames)
    assert repair_limb_bend_bursts(clip)[0] is clip


def skeleton_frame():
    joints = {"pelvis": (0., 1., 0.), "spine1": (0., 1.2, 0.), "spine2": (0., 1.4, 0.),
              "spine3": (0., 1.6, 0.), "neck": (0., 1.75, 0.), "head": (0., 1.95, 0.)}
    for side, sign in (("left", -1), ("right", 1)):
        joints.update({f"{side}_collar": (sign * .1, 1.68, 0.), f"{side}_shoulder": (sign * .25, 1.65, 0.),
                       f"{side}_elbow": (sign * .3, 1.35, .2), f"{side}_wrist": (sign * .25, 1.55, .45),
                       f"{side}_hand": (sign * .25, 1.55, .5), f"{side}_hip": (sign * .15, 1., 0.),
                       f"{side}_knee": (sign * .15, .6, .2), f"{side}_ankle": (sign * .15, .15, 0.),
                       f"{side}_foot": (sign * .15, .1, .15)})
    return MotionFrame(0., joints)


def test_core_repair_moves_core_and_preserves_every_bone_and_distal_endpoint():
    frame = skeleton_frame()
    targets = dict(frame.joints)
    targets["spine1"] = (.04, 1.19, 0.)
    targets["left_hip"] = (-.14, 1.03, 0.)
    targets["neck"] = (.03, 1.74, .01)
    repaired, scale = s._project_core_targets_with_fixed_endpoints(frame, targets)
    assert scale > 0
    assert math.dist(repaired["spine1"], frame.joints["spine1"]) > .001
    for parent, child in s.STRUCTURAL_BONES:
        assert math.dist(repaired[parent], repaired[child]) == pytest.approx(math.dist(frame.joints[parent], frame.joints[child]), abs=1e-8)
    for side in ("left", "right"):
        for suffix in ("wrist", "hand", "ankle", "foot"):
            assert repaired[f"{side}_{suffix}"] == frame.joints[f"{side}_{suffix}"]


def test_neck_edit_does_not_drag_shoulder_attachments():
    frame = skeleton_frame()
    targets = {"neck": (.035, 1.745, .01)}
    for preserve_shoulders in (False, True):
        repaired, scale = s._project_core_targets_with_fixed_endpoints(
            frame, targets, preserve_shoulders=preserve_shoulders)
        assert scale > 0
        assert math.dist(repaired['neck'], frame.joints['neck']) > .001
        for side in ('left', 'right'):
            for part in ('collar', 'shoulder'):
                name = f'{side}_{part}'
                assert repaired[name] == pytest.approx(frame.joints[name], abs=1e-8)


def test_unreachable_core_edit_does_not_drag_planted_feet():
    frame = skeleton_frame()
    targets = {name: (p[0], p[1] + 100, p[2]) for name, p in frame.joints.items()}
    repaired, scale = s._project_core_targets_with_fixed_endpoints(frame, targets)
    assert scale == 0
    assert repaired == frame.joints


def test_leg_driven_core_alignment_preserves_shoulders_and_arm_trajectories():
    frame = skeleton_frame()
    frame.joints["spine1"] = (.03, 1.2, 0.)
    frame.joints["spine2"] = (.03, 1.4, 0.)
    clip = MotionClip(30., list(frame.joints), [frame])
    repaired, report = s._align_core_for_same_phase_bilateral_travel(
        clip, bilateral_modes={"legs": {"mode": "same_phase_symmetric"}})
    assert report["applied"]
    for side in ("left", "right"):
        for part in ("shoulder", "elbow", "wrist", "hand"):
            assert repaired.frames[0].joints[f"{side}_{part}"] == pytest.approx(frame.joints[f"{side}_{part}"], abs=1e-9)


def test_paired_hand_repair_follows_body_turn_without_changing_rigid_hold():
    original = skeleton_frame()
    frames = []
    for i in range(20):
        theta = i * .07
        rotation = np.array([[math.cos(theta), 0., math.sin(theta)], [0., 1., 0.], [-math.sin(theta), 0., math.cos(theta)]])
        frames.append(MotionFrame(i / 30., {name: tuple(rotation @ p) for name, p in original.joints.items()}))
    clip = MotionClip(30., list(original.joints), frames)
    repaired, report = s._stabilize_rigid_paired_hand_spacing(clip)
    assert report["axisReference"] == "moving_body_frame"
    for before, after in zip(clip.frames, repaired.frames):
        for side in ("left", "right"):
            assert after.joints[f"{side}_hand"] == pytest.approx(before.joints[f"{side}_hand"], abs=1e-6)


def test_spike_only_repair_is_saved_from_current_artifact_and_invalidates_approval(tmp_path, monkeypatch):
    from scripts import repair_selected_articulation as repair
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir()
    (selected_dir / "raw").mkdir()
    skeleton = selected_dir / "x_wear_skeleton.json"
    document = {"fps": 30, "frames": [{"timeSec": 0., "joints": {"left_wrist": [1., 0., 0.]}}]}
    skeleton.write_text(json.dumps(document))
    backup = skeleton.with_suffix(skeleton.suffix + ".pre-articulation-fix")
    backup.write_text(json.dumps({"fps": 30, "frames": [{"timeSec": 0., "joints": {"left_wrist": [0., 0., 0.]}}]}))
    (selected_dir / "raw/motion.raw.json").write_text(json.dumps(document))
    selected = {"skeletonPath": str(skeleton), "candidateWorkspace": str(selected_dir),
                "reviewVideoPath": str(selected_dir / "video.webm"), "ranking": {"payload": {"finalOutputValidation": {"passed": True}}}}
    manifest = selected_dir / "selection_manifest.json"
    manifest.write_text(json.dumps({"selected": selected, "selectedResults": [selected]}))
    monkeypatch.setattr(repair, "constrain_to_source_articulation_envelope", lambda source, proposed: (proposed, {"applied": False}))
    monkeypatch.setattr(repair, "stabilize_distal_foot_heading", lambda clip: (clip, {"applied": False}))
    monkeypatch.setattr(repair, "stabilize_forefoot_ground_contacts", lambda clip, evidence: (clip, {"applied": False}))
    def fix_spike(clip):
        assert clip.frames[0].joints["left_wrist"][0] == 1.  # Not the stale backup's zero.
        frame = replace(clip.frames[0], joints={"left_wrist": (2., 0., 0.)})
        return replace(clip, frames=[frame]), {"applied": True}
    monkeypatch.setattr(repair, "suppress_post_ik_anatomical_spikes", fix_spike)
    assert repair.repair_manifest(manifest, render=False) is not None
    assert json.loads(skeleton.read_text())["frames"][0]["joints"]["left_wrist"][0] == 2.
    assert json.loads((selected_dir / "revalidation.json").read_text())["status"] == "needs_manual_review"
    assert json.loads(backup.read_text())["frames"][0]["joints"]["left_wrist"][0] == 0.
