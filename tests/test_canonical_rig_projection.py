"""Focused contract tests for exact canonical rig projection.

The rig dictionary is rebuilt directly from the production SMPL joint tree so
that the tests exercise the shipped ``FixedRig`` forward kinematics instead of
re-implementing it.
"""

from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.canonical_rig_projection import (
    exact_canonical_coordinate_jacobian,
    exact_canonical_coordinates,
)
from exercise_motion_pkg.controlled_motion import FixedRig, canonical_bilateral_reference
from exercise_motion_pkg.smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS

CANONICAL_EXECUTION = {"torso": "sagittal", "arms": "mirrored", "legs": "mirrored"}
UNCONSTRAINED_EXECUTION = {
    "torso": "unconstrained",
    "arms": "unconstrained",
    "legs": "unconstrained",
}
SOCKET_NAMES = ("left_hip", "right_hip", "left_collar", "right_collar")

# Length of every non-socket local +Y bone, in metres (SMPL-like proportions).
BONE_LENGTHS = {
    "spine1": 0.12,
    "spine2": 0.12,
    "spine3": 0.10,
    "neck": 0.08,
    "head": 0.10,
    "left_knee": 0.42,
    "right_knee": 0.42,
    "left_ankle": 0.42,
    "right_ankle": 0.42,
    "left_foot": 0.12,
    "right_foot": 0.12,
    "left_shoulder": 0.12,
    "right_shoulder": 0.12,
    "left_elbow": 0.28,
    "right_elbow": 0.28,
    "left_wrist": 0.26,
    "right_wrist": 0.26,
    "left_hand": 0.08,
    "right_hand": 0.08,
}


def _root_rotation(frame: int) -> np.ndarray:
    """Apply nonzero roll, pitch and yaw to exercise actual pelvis leveling."""
    rolls = (0.22, -0.16, 0.11)
    pitches = (0.25, -0.18, 0.12)
    yaws = (0.35, 0.50, -0.30)
    return (Rotation.from_rotvec([0.0, yaws[frame], 0.0]).as_matrix()
            @ Rotation.from_rotvec([0.0, 0.0, rolls[frame]]).as_matrix()
            @ Rotation.from_rotvec([pitches[frame], 0.0, 0.0]).as_matrix())


def _rotvec_series(frames: tuple[tuple[float, float, float], ...]) -> np.ndarray:
    return np.asarray(frames, dtype=float)


def _frame_local_rotations() -> dict[str, np.ndarray]:
    """Deliberately asymmetric, frame-varying local rotations."""
    return {
        "spine1": _rotvec_series(((0.06, 0.0, 0.14), (0.20, 0.03, -0.10), (-0.03, 0.02, 0.06))),
        "spine2": _rotvec_series(((0.02, 0.0, 0.08), (-0.08, 0.02, 0.05), (0.15, 0.0, -0.10))),
        "spine3": _rotvec_series(((0.0, 0.02, -0.05), (0.09, 0.0, 0.10), (0.13, 0.01, 0.04))),
        "neck": _rotvec_series(((0.0, 0.0, 0.02), (0.03, 0.0, -0.02), (0.01, 0.0, 0.03))),
        "left_knee": _rotvec_series(((0.15, 0.0, 0.02), (-0.20, 0.03, -0.02), (0.12, -0.02, 0.04))),
        "right_knee": _rotvec_series(((-0.06, 0.01, -0.03), (0.14, 0.0, 0.02), (-0.09, 0.02, -0.01))),
        "left_ankle": _rotvec_series(((0.12, 0.0, 0.0), (-0.08, 0.02, 0.02), (0.05, -0.01, 0.01))),
        "right_ankle": _rotvec_series(((-0.05, 0.01, 0.0), (0.10, 0.0, -0.02), (-0.02, 0.0, 0.01))),
        "left_foot": _rotvec_series(((0.0, 0.10, 0.0), (0.02, 0.05, 0.01), (-0.01, -0.08, 0.02))),
        "right_foot": _rotvec_series(((0.01, -0.04, 0.0), (-0.02, 0.08, 0.01), (0.0, -0.06, 0.01))),
        "left_shoulder": _rotvec_series(((0.05, 0.0, 0.0), (-0.02, 0.02, 0.0), (0.0, 0.0, 0.02))),
        "right_shoulder": _rotvec_series(((-0.03, 0.0, 0.01), (0.04, 0.0, -0.02), (0.01, 0.0, 0.0))),
        "left_elbow": _rotvec_series(((0.35, 0.0, 0.05), (-0.10, 0.05, 0.0), (0.20, 0.0, 0.10))),
        "right_elbow": _rotvec_series(((-0.12, 0.02, 0.0), (0.18, 0.0, 0.03), (0.05, 0.01, -0.02))),
        "left_wrist": _rotvec_series(((0.08, 0.0, 0.0), (0.0, 0.02, 0.05), (-0.04, 0.0, 0.0))),
        "right_wrist": _rotvec_series(((-0.05, 0.0, 0.02), (0.06, 0.0, 0.0), (0.02, 0.0, -0.03))),
        "left_hand": _rotvec_series(((0.02, 0.0, 0.0), (-0.03, 0.0, 0.01), (0.0, 0.0, 0.0))),
        "right_hand": _rotvec_series(((0.0, 0.0, -0.01), (0.02, 0.0, 0.0), (-0.01, 0.0, 0.02))),
    }


def _build_rig() -> tuple[FixedRig, dict]:
    names = list(SMPL_JOINT_NAMES)
    parents = [int(parent) for parent in SMPL_JOINT_PARENTS]
    order = list(range(len(names)))
    rotation_names = [name for name in names if name not in SOCKET_NAMES]

    offsets = np.zeros((len(names), 3), dtype=float)
    for joint, name in enumerate(names):
        if name in SOCKET_NAMES or joint == names.index("pelvis"):
            continue
        offsets[joint] = [0.0, BONE_LENGTHS[name], 0.0]
    # Fixed hip and collar sockets share Y/Z and mirror only in X.
    offsets[names.index("left_hip")] = [-0.10, 0.05, 0.02]
    offsets[names.index("right_hip")] = [0.10, 0.05, 0.02]
    offsets[names.index("left_collar")] = [-0.17, 0.02, 0.01]
    offsets[names.index("right_collar")] = [0.17, 0.02, 0.01]

    width = 3 + 3 * len(rotation_names)
    coordinates = np.zeros((3, width), dtype=float)
    coordinates[:, :3] = [[0.0, 1.0, 0.0], [0.05, 1.02, 0.02], [-0.03, 0.98, 0.01]]
    slots = {name: 3 + 3 * index for index, name in enumerate(rotation_names)}
    for frame in range(3):
        root = _root_rotation(frame)
        coordinates[frame, slots["pelvis"]:slots["pelvis"] + 3] = Rotation.from_matrix(root).as_rotvec()
        for name, series in _frame_local_rotations().items():
            coordinates[frame, slots[name]:slots[name] + 3] = series[frame]

    rig = FixedRig.__new__(FixedRig)
    rig.names = names
    rig.parents = parents
    rig.order = order
    rig.offsets = offsets
    rig.root = names.index("pelvis")
    rig.active = [names.index(name) for name in rotation_names]
    rig.slots = {joint: 3 + 3 * index for index, joint in enumerate(rig.active)}
    rig.initial = coordinates
    rig.width = width
    rig.material_reference_coordinates = coordinates.copy()

    spec = {
        "jointNames": names,
        "parents": parents,
        "order": order,
        "offsets": offsets.tolist(),
        "rotationJointNames": rotation_names,
        "coordinates": coordinates.tolist(),
    }
    return rig, spec


def _with_coordinates(spec: dict, coordinates: np.ndarray) -> dict:
    return {**spec, "coordinates": np.asarray(coordinates, dtype=float).tolist()}


def test_projection_satisfies_canonical_policy_and_authority():
    rig, spec = _build_rig()
    coordinates = np.asarray(spec["coordinates"], dtype=float)
    original = rig.decode(coordinates)

    projected = exact_canonical_coordinates(spec, CANONICAL_EXECUTION)
    assert projected.shape == coordinates.shape
    decoded = rig.decode(projected)

    target = canonical_bilateral_reference(decoded, rig.names, CANONICAL_EXECUTION)
    assert np.allclose(target, decoded, atol=1e-7), (
        "projected decode is not a fixed point of canonical_bilateral_reference: "
        f"max error {np.max(np.abs(target - decoded))}"
    )

    again = exact_canonical_coordinates(_with_coordinates(spec, projected), CANONICAL_EXECUTION)
    assert np.allclose(again, projected, atol=1e-9), "projector is not idempotent"

    for joint in rig.order:
        parent = rig.parents[joint]
        if parent < 0:
            continue
        original_length = np.linalg.norm(original[:, joint] - original[:, parent], axis=1)
        decoded_length = np.linalg.norm(decoded[:, joint] - decoded[:, parent], axis=1)
        assert np.allclose(decoded_length, original_length, atol=1e-9), (
            f"bone length changed for {rig.names[joint]}"
        )

    leg_parts = ("hip", "knee", "ankle", "foot")
    for side in ("left", "right"):
        authority = {"legs": side}
        authoritative = exact_canonical_coordinates(spec, CANONICAL_EXECUTION, authority)
        decoded_authoritative = rig.decode(authoritative)
        authoritative_target = canonical_bilateral_reference(
            decoded_authoritative, rig.names, CANONICAL_EXECUTION, authority
        )
        assert np.allclose(authoritative_target, decoded_authoritative, atol=1e-7), (
            f"{side} authority result is not a canonical fixed point"
        )
        supporting = [rig.names.index(f"{side}_{part}") for part in leg_parts]
        assert np.allclose(decoded_authoritative[:, supporting], original[:, supporting], atol=1e-7), (
            f"{side} authority moved the supporting leg world points"
        )


def test_terminal_foot_twist_is_independent_of_point_symmetry():
    rig, spec = _build_rig()
    canonical = exact_canonical_coordinates(spec, CANONICAL_EXECUTION)
    decoded_canonical = rig.decode(canonical)

    angle = 0.37
    foot = rig.names.index("left_foot")
    slot = slice(rig.slots[foot], rig.slots[foot] + 3)
    local = Rotation.from_rotvec(canonical[:, slot]).as_matrix()
    axial_twist = Rotation.from_rotvec([0.0, angle, 0.0]).as_matrix()
    twisted = canonical.copy()
    twisted[:, slot] = Rotation.from_matrix(local @ axial_twist).as_rotvec()

    projected = exact_canonical_coordinates(_with_coordinates(spec, twisted), CANONICAL_EXECUTION)
    decoded_twisted = rig.decode(projected)

    assert np.allclose(decoded_twisted, decoded_canonical, atol=1e-8), (
        "terminal foot axial twist changed joint positions"
    )

    world_before = rig.global_rotations(canonical)[foot]
    world_after = rig.global_rotations(projected)[foot]
    relative = world_after @ np.swapaxes(world_before, 1, 2)
    relative_rotation = Rotation.from_matrix(relative)
    assert np.allclose(relative_rotation.magnitude(), angle, atol=1e-6), (
        "world foot orientation lost the applied axial twist"
    )
    axis = relative_rotation.as_rotvec()
    axis /= np.linalg.norm(axis, axis=1, keepdims=True)
    bone_axis = world_before[:, :, 1]
    bone_axis /= np.linalg.norm(bone_axis, axis=1, keepdims=True)
    assert np.all(np.abs(np.sum(axis * bone_axis, axis=1)) > 1.0 - 1e-7), (
        "retained twist is not about the ankle-foot bone axis"
    )

    gauge_before = world_before[:, :, 0]
    gauge_after = world_after[:, :, 0]
    gauge_angle = np.arccos(np.clip(np.sum(gauge_before * gauge_after, axis=1), -1.0, 1.0))
    assert np.allclose(gauge_angle, angle, atol=1e-6), "material foot gauge did not retain the twist"


def test_sagittal_projection_is_invariant_to_equivalent_spine_local_gauge():
    rig, spec = _build_rig()
    coordinates = np.asarray(spec["coordinates"], dtype=float)
    changed = coordinates.copy()
    q = Rotation.from_rotvec([0.0, 0.7, 0.0]).as_matrix()
    for name, matrix in (
        ("spine1", Rotation.from_rotvec(coordinates[:, rig.slots[rig.names.index("spine1")]:
                                         rig.slots[rig.names.index("spine1")] + 3]).as_matrix() @ q),
        ("spine2", np.swapaxes(q, 0, 1) @ Rotation.from_rotvec(
            coordinates[:, rig.slots[rig.names.index("spine2")]:
                        rig.slots[rig.names.index("spine2")] + 3]).as_matrix()),
    ):
        start = rig.slots[rig.names.index(name)]
        changed[:, start:start + 3] = Rotation.from_matrix(matrix).as_rotvec()

    source_points = rig.decode(coordinates)
    equivalent_points = rig.decode(changed)
    assert np.allclose(source_points, equivalent_points, atol=1e-12), (
        "the local gauge rewrite changed source joint points"
    )

    authority = {"legs": "right"}
    projected = exact_canonical_coordinates(_with_coordinates(spec, coordinates), CANONICAL_EXECUTION, authority)
    projected_equivalent = exact_canonical_coordinates(_with_coordinates(spec, changed), CANONICAL_EXECUTION, authority)
    projected_points = rig.decode(projected)
    projected_equivalent_points = rig.decode(projected_equivalent)
    assert np.allclose(projected_points, projected_equivalent_points, atol=1e-8), (
        "equivalent source spine gauges produced different canonical joint points"
    )


def test_unconstrained_execution_is_identity_and_projection_jacobian_couples_to_decoder():
    rig, spec = _build_rig()
    coordinates = np.asarray(spec["coordinates"], dtype=float)
    frame_count, width = coordinates.shape
    size = frame_count * width

    unconstrained = exact_canonical_coordinates(spec, UNCONSTRAINED_EXECUTION)
    assert np.allclose(unconstrained, coordinates, atol=0.0, rtol=0.0), (
        "unconstrained execution changed coordinates"
    )
    identity = exact_canonical_coordinate_jacobian(spec, UNCONSTRAINED_EXECUTION)
    assert sp.issparse(identity)
    assert identity.shape == (size, size)
    assert np.allclose(identity.toarray(), np.eye(size), atol=1e-12)

    jacobian = exact_canonical_coordinate_jacobian(spec, CANONICAL_EXECUTION)
    assert sp.issparse(jacobian)
    assert jacobian.shape == (size, size)

    direction = np.random.default_rng(20261115).standard_normal(size)
    direction = direction.reshape(frame_count, width)
    jacobian_direction = np.asarray(jacobian @ direction.reshape(-1)).reshape(frame_count, width)

    step = 1e-6
    plus = exact_canonical_coordinates(
        _with_coordinates(spec, coordinates + step * direction), CANONICAL_EXECUTION
    )
    minus = exact_canonical_coordinates(
        _with_coordinates(spec, coordinates - step * direction), CANONICAL_EXECUTION
    )
    finite_difference = (rig.decode(plus) - rig.decode(minus)) / (2.0 * step)

    base = exact_canonical_coordinates(spec, CANONICAL_EXECUTION)
    jvp_plus = rig.decode(base + step * jacobian_direction)
    jvp_minus = rig.decode(base - step * jacobian_direction)
    jvp = (jvp_plus - jvp_minus) / (2.0 * step)

    difference = np.abs(finite_difference.reshape(-1) - jvp.reshape(-1))
    assert np.allclose(finite_difference, jvp, atol=5e-4, rtol=5e-3), (
        f"projection Jacobian/decoder directional JVP mismatch (max {np.max(difference)})"
    )
