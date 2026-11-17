from __future__ import annotations

import numpy as np

from exercise_motion_pkg.canonical_rig_initialization import (
    propose_canonical_contact_rig,
)
from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.smpl_joint_names import (
    SMPL_JOINT_NAMES,
    SMPL_JOINT_PARENTS,
)


def _asymmetric_smpl_sequence(frame_count: int = 5) -> np.ndarray:
    names = list(SMPL_JOINT_NAMES)
    index = {name: i for i, name in enumerate(names)}
    offsets = {name: np.array([0.0, 0.08, 0.0]) for name in names}
    offsets['pelvis'] = np.zeros(3)
    offsets.update({
        'left_hip': np.array([-0.10, -0.08, 0.0]),
        'right_hip': np.array([0.10, -0.08, 0.0]),
        'spine1': np.array([0.0, 0.10, 0.0]),
        'spine2': np.array([0.0, 0.10, 0.01]),
        'spine3': np.array([0.0, 0.10, 0.01]),
        'neck': np.array([0.0, 0.10, 0.0]),
        'head': np.array([0.0, 0.10, 0.0]),
        'left_collar': np.array([-0.12, 0.02, 0.0]),
        'right_collar': np.array([0.12, 0.02, 0.0]),
        'left_shoulder': np.array([-0.13, 0.0, 0.0]),
        'right_shoulder': np.array([0.13, 0.0, 0.0]),
        'left_elbow': np.array([-0.20, -0.02, 0.01]),
        'right_elbow': np.array([0.20, -0.02, -0.01]),
        'left_wrist': np.array([-0.16, -0.01, 0.0]),
        'right_wrist': np.array([0.16, -0.01, 0.0]),
        'left_hand': np.array([-0.07, 0.0, 0.0]),
        'right_hand': np.array([0.07, 0.0, 0.0]),
        'left_knee': np.array([0.0, -0.30, 0.0]),
        'right_knee': np.array([0.0, -0.30, 0.0]),
        'left_ankle': np.array([0.0, -0.28, 0.0]),
        'right_ankle': np.array([0.0, -0.28, 0.0]),
        'left_foot': np.array([0.0, -0.02, 0.08]),
        'right_foot': np.array([0.0, -0.02, 0.08]),
    })

    frames = np.zeros((frame_count, len(names), 3), dtype=float)
    for frame in range(frame_count):
        for joint, name in enumerate(names):
            parent = SMPL_JOINT_PARENTS[joint]
            if parent < 0:
                frames[frame, joint] = [0.002 * frame, 1.0, 0.0]
            else:
                frames[frame, joint] = (
                    frames[frame, parent] + offsets[name]
                )
        # Small measured asymmetries make the canonical target nontrivial.
        frames[frame, index['right_hand'], 2] += 0.012
        frames[frame, index['left_shoulder'], 1] += 0.004
        frames[frame, index['right_shoulder'], 1] -= 0.003
    return frames


def test_canonical_rig_initializer_preserves_lengths_and_pins_or_rejects_conflict() -> None:
    names = list(SMPL_JOINT_NAMES)
    points = _asymmetric_smpl_sequence()
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    decoded = rig.decode(coordinates)
    pin = names.index('right_foot')
    pinned = np.zeros(decoded.shape[:2], dtype=bool)
    pinned[:, pin] = True
    contact_targets = decoded.copy()

    proposed, offsets, evidence = propose_canonical_contact_rig(
        coordinates, rig, {'arms': 'mirrored', 'torso': 'sagittal'},
        pinned, contact_targets,
    )

    assert evidence['applied'] is True
    assert evidence['canonicalResidualAfterMeters'] < evidence['canonicalResidualBeforeMeters']
    assert evidence['maximumPinErrorMeters'] <= 1e-9
    assert np.allclose(np.linalg.norm(offsets, axis=1), np.linalg.norm(rig.offsets, axis=1),
                       rtol=0.0, atol=1e-9)
    assert proposed.shape == coordinates.shape

    conflicting = pinned.copy()
    conflicting[:, names.index('left_foot')] = True
    incompatible_targets = contact_targets.copy()
    incompatible_targets[:, names.index('left_foot'), 0] += 0.01
    rejected_coordinates, rejected_offsets, rejection = propose_canonical_contact_rig(
        coordinates, rig, {'arms': 'mirrored', 'torso': 'sagittal'},
        conflicting, incompatible_targets,
    )
    assert rejection['applied'] is False
    assert rejection['reason'] == 'canonical_rig_cannot_preserve_all_pins'
    assert np.array_equal(rejected_coordinates, coordinates)
    assert np.array_equal(rejected_offsets, rig.offsets)
