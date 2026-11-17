import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg import reconstruction_convert
from exercise_motion_pkg.smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS
from exercise_motion_pkg.temporal_quality import transport_corrected_bone_sides, transport_side

ROOT = Path(__file__).resolve().parents[1]
LEFT_KEY = "left_ankle->left_foot"


def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    return vector / np.linalg.norm(vector)


def _prior(forward=(0.0, 0.0, 1.0), lateral=(1.0, 0.0, 0.0)):
    forward = _unit(forward)
    lateral = _unit(np.asarray(lateral) - forward * np.dot(lateral, forward))
    basis = np.stack([forward, lateral, np.cross(lateral, forward)], axis=1)
    side = {"modelFootFrame": basis.tolist()}
    return {"modelSha256": "a" * 64, "reconstructionSha256": "b" * 64,
            "sides": {"left": dict(side), "right": dict(side)}}


def _pose_with_rotations(rotations):
    pose = np.zeros((1, 72))
    for joint_name, rotvec in rotations.items():
        index = SMPL_JOINT_NAMES.index(joint_name)
        pose[0, 3 * index:3 * index + 3] = rotvec
    return pose


def _joints(left_ankle, left_foot, right_ankle=(0, 0, 0), right_foot=(0, 0, 1)):
    joints = np.zeros((1, len(SMPL_JOINT_NAMES), 3))
    joints[0, SMPL_JOINT_NAMES.index("left_ankle")] = left_ankle
    joints[0, SMPL_JOINT_NAMES.index("left_foot")] = left_foot
    joints[0, SMPL_JOINT_NAMES.index("right_ankle")] = right_ankle
    joints[0, SMPL_JOINT_NAMES.index("right_foot")] = right_foot
    return joints


def _sides(pose, joints, prior=None, *, degrees=0.0):
    return reconstruction_convert._native_foot_bone_sides(
        pose=pose, joints=joints, parents=SMPL_JOINT_PARENTS,
        foot_marker_prior=_prior() if prior is None else prior,
        output_rotation_degrees=degrees,
    )


def test_root_yaw_rotates_foot_side_with_joint_axis():
    root = Rotation.from_euler("y", 90, degrees=True)
    pose = _pose_with_rotations({"pelvis": root.as_rotvec()})
    joints = _joints((0, 0, 0), root.apply([0, 0, 1]),
                     (0, 0, 0), root.apply([0, 0, 1]))
    side = np.asarray(_sides(pose, joints)[0][LEFT_KEY])
    assert np.dot(side, [0, 0, -1]) == pytest.approx(1.0, abs=1e-9)


def test_ankle_twist_rotates_foot_side():
    twist = Rotation.from_euler("z", 90, degrees=True)
    pose = _pose_with_rotations({"left_ankle": twist.as_rotvec()})
    joints = _joints((0, 0, 0), (0, 0, 1))
    side = np.asarray(_sides(pose, joints)[0][LEFT_KEY])
    assert np.dot(side, [0, 1, 0]) == pytest.approx(1.0, abs=1e-9)


def test_child_foot_joint_rotation_does_not_own_bone_side():
    pose = _pose_with_rotations(
        {"left_foot": Rotation.from_euler("z", 35, degrees=True).as_rotvec()})
    joints = _joints((0, 0, 0), (0, 0, 1))
    side = np.asarray(_sides(pose, joints)[0][LEFT_KEY])
    assert np.dot(side, [1, 0, 0]) == pytest.approx(1.0, abs=1e-9)


def test_output_rotation_applies_to_both_joint_and_side_axes():
    pose = _pose_with_rotations({})
    emitted_forward = Rotation.from_euler("z", 90, degrees=True).apply([0, 1, 0])
    joints = _joints((0, 0, 0), emitted_forward)
    field = _sides(pose, joints, prior=_prior(forward=(0, 1, 0)), degrees=90.0)
    side = np.asarray(field[0][LEFT_KEY])
    expected_side = Rotation.from_euler("z", 90, degrees=True).apply([1, 0, 0])
    assert np.dot(side, expected_side) == pytest.approx(1.0, abs=1e-9)
    assert np.dot(side, emitted_forward) == pytest.approx(0.0, abs=1e-9)


def test_missing_prior_stays_legacy_without_inventing_axes():
    pose = _pose_with_rotations({})
    assert _sides(pose, _joints((0, 0, 0), (0, 0, 1)), prior={}) is None


def _find_prior(node):
    if isinstance(node, dict):
        sides = node.get("sides")
        if isinstance(sides, dict) and all(
                isinstance(sides.get(side), dict) and "modelFootFrame" in sides[side]
                for side in ("left", "right")):
            return node
        for value in node.values():
            found = _find_prior(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_prior(value)
            if found is not None:
                return found
    return None


def test_cached_reconstruction_pose_forward_agrees_with_emitted_bone():
    pkl = (ROOT / ".scratch/goal-contact-continuation/remaining-three-recovery-v11"
           / "workspace/cable-crunch/bake/reconstruction-cache"
           / "af12e2843115e468a9938961d2522cbfcf4d12dcc5715e01d740904ccb1f717a"
           / "reconstruction_output.pkl")
    raw_path = (ROOT / ".scratch/goal-contact-continuation/remaining-three-recovery-v11"
                / "workspace/cable-crunch/bake/cable-crunch-001-0p9zs2wnqhq/raw/motion.raw.json")
    prior_path = (ROOT / ".scratch/goal-contact-continuation/cable-restoration-positive-guard-v170"
                  / "solver-input-authoritative.json")
    if not all(path.is_file() for path in (pkl, raw_path, prior_path)):
        pytest.skip("retained cached pose artifacts are unavailable")
    joblib = pytest.importorskip("joblib")
    pose_world = np.asarray(joblib.load(pkl)[0]["pose_world"], dtype=float)
    raw_frames = json.loads(raw_path.read_text(encoding="utf-8"))["frames"]
    prior = _find_prior(json.loads(prior_path.read_text(encoding="utf-8")))
    rotations = Rotation.from_rotvec(pose_world.reshape(-1, 3)).as_matrix().reshape(
        len(pose_world), len(SMPL_JOINT_NAMES), 3, 3)
    for frame_index in (0, 60, 120, 180, 208):
        rot = rotations[frame_index]
        joints = np.zeros((1, len(SMPL_JOINT_NAMES), 3))
        for name, coords in raw_frames[frame_index]["joints"].items():
            joints[0, SMPL_JOINT_NAMES.index(name)] = coords
        for side, chain in (("left", (0, 1, 4, 7)), ("right", (0, 2, 5, 8))):
            ankle_rotation = np.eye(3)
            for joint_index in chain:
                ankle_rotation = ankle_rotation @ rot[joint_index]
            rest_forward = np.asarray(prior["sides"][side]["modelFootFrame"])[:, 0]
            predicted = ankle_rotation @ rest_forward
            actual = (joints[0, SMPL_JOINT_NAMES.index(f"{side}_foot")]
                      - joints[0, SMPL_JOINT_NAMES.index(f"{side}_ankle")])
            angle = np.degrees(np.arccos(np.clip(
                np.dot(_unit(predicted), _unit(actual)), -1.0, 1.0)))
            assert angle < 1e-3
        field = reconstruction_convert._native_foot_bone_sides(
            pose=pose_world[frame_index:frame_index + 1],
            joints=joints, parents=SMPL_JOINT_PARENTS, foot_marker_prior=prior,
            output_rotation_degrees=0.0,
        )
        for side in ("left", "right"):
            key = f"{side}_ankle->{side}_foot"
            side_axis = np.asarray(field[0][key])
            forward = _unit(joints[0, SMPL_JOINT_NAMES.index(f"{side}_foot")]
                            - joints[0, SMPL_JOINT_NAMES.index(f"{side}_ankle")])
            assert abs(float(np.dot(side_axis, forward))) < 1e-9


@pytest.fixture
def ground_repair(monkeypatch):
    from exercise_motion_pkg import contact_constraints, foot_geometry, support_geometry

    monkeypatch.setattr(contact_constraints, "motion_space_support_evidence", lambda payload: {})
    monkeypatch.setattr(contact_constraints, "observed_ground_contact_mask",
                        lambda evidence, names, count: np.ones((count, len(names)), dtype=bool))
    monkeypatch.setattr(foot_geometry, "calibrated_foot_rest_pitches",
                        lambda points, names, evidence, **kwargs: {})
    monkeypatch.setattr(support_geometry, "support_evidence",
                        lambda payload: {"status": "unavailable"})


def _payload(side, provenance):
    frame = {"joints": {"left_ankle": [0.0, 0.0, 0.0], "left_foot": [0.0, 0.0, 1.0]},
             "boneSides": {LEFT_KEY: side}}
    if provenance:
        frame["boneSideProvenance"] = {LEFT_KEY: provenance}
    return {"fps": 30.0, "jointNames": ["left_ankle", "left_foot"], "frames": [frame]}


def test_ground_repair_preserves_and_transports_qualified_model_axis(ground_repair):
    previous = {"joints": {"left_ankle": [0.0, 0.0, 0.0], "left_foot": [0.0, 0.0, 1.0]}}
    payload = _payload([1.0, 0.0, 0.0], reconstruction_convert.NATIVE_FOOT_SIDE_AXIS_PROVENANCE)
    rotated = Rotation.from_euler("y", 20, degrees=True).apply([0.0, 0.0, 1.0])
    payload["frames"][0]["joints"]["left_foot"] = rotated.tolist()
    transport_corrected_bone_sides([previous], payload)
    expected = transport_side(np.array([1.0, 0.0, 0.0]),
                              np.array([0.0, 0.0, 1.0]), _unit(rotated))
    actual = np.asarray(payload["frames"][0]["boneSides"][LEFT_KEY])
    assert np.dot(actual, expected) == pytest.approx(1.0, abs=1e-9)
    legacy = _unit(np.cross(_unit(rotated), [0.0, 1.0, 0.0]))
    assert np.dot(actual, legacy) < 0.0


def test_ground_repair_keeps_legacy_global_up_without_provenance(ground_repair):
    payload = _payload([1.0, 0.0, 0.0], None)
    transport_corrected_bone_sides([{"joints": {"left_ankle": [0.0, 0.0, 0.0],
                                                "left_foot": [0.0, 0.0, 1.0]}}], payload)
    assert np.allclose(payload["frames"][0]["boneSides"][LEFT_KEY], [-1.0, 0.0, 0.0])


def test_malformed_qualified_model_axis_fails_closed(ground_repair):
    payload = _payload([0.0, 0.0, 1.0],
                       reconstruction_convert.NATIVE_FOOT_SIDE_AXIS_PROVENANCE)
    with pytest.raises(ValueError, match="Malformed qualified bone side"):
        transport_corrected_bone_sides([], payload)


def test_confirmed_sole_contact_preserves_qualified_model_frame(ground_repair, monkeypatch):
    from exercise_motion_pkg import support_geometry

    monkeypatch.setattr(support_geometry, "support_evidence", lambda payload: {
        "status": "confirmed",
        "soleContacts": [{"joints": ["left_foot", "left_ankle", "left_foot"],
                           "normal": [1.0, 0.0, 0.0]}],
    })
    monkeypatch.setattr(support_geometry, "evidence_is_complete", lambda *args: True)
    provenance = reconstruction_convert.NATIVE_FOOT_SIDE_AXIS_PROVENANCE
    payload = _payload([1.0, 0.0, 0.0], provenance)
    transport_corrected_bone_sides([], payload)
    assert payload["frames"][0]["boneSides"][LEFT_KEY] == [1.0, 0.0, 0.0]
