"""Regression: immutable validation gates its own geometry, not the fit seed.

The pre-optimizer post-support-initialization cycle boundary must assess the
submitted immutable candidate. A generation fit instead assesses the seed
geometry it just rebuilt from ``initialized_points``.
"""
import copy

import numpy as np


NAMES = ['pelvis', 'left_hip', 'left_knee', 'left_ankle',
         'right_hip', 'right_knee', 'right_ankle']
BASE = {
    'pelvis': [0., 1.2, 0.],
    'left_hip': [0.1, 1., 0.],
    'left_knee': [0.1, .6, 0.],
    'left_ankle': [0.1, .2, 0.],
    'right_hip': [-0.1, 1., 0.],
    'right_knee': [-0.1, .6, 0.],
    'right_ankle': [-0.1, .2, 0.],
}


def _payload(frames):
    return {'jointNames': list(NAMES), 'frames': frames, 'fps': 30.,
            'loop': {'enabled': True}}


def _frames(positions):
    return [
        {'timeSec': index / 30., 'joints': {
            name: np.asarray(value, dtype=float).tolist()
            for name, value in zip(NAMES, position)}}
        for index, position in enumerate(positions)
    ]


def _positions(wrap_offset=0.):
    """Nine smoothly advancing poses; ``wrap_offset`` breaks the loop seam."""
    positions = []
    for index in range(9):
        offset = np.array([index * 1e-4, 0., 0.])
        if index == 0:
            offset = offset + np.array([wrap_offset, 0., 0.])
        positions.append([np.asarray(BASE[name]) + offset for name in NAMES])
    return np.asarray(positions)


def test_cycle_gate_uses_initialized_seed_for_generation():
    from exercise_motion_pkg.controlled_motion import (
        _post_support_initialization_cycle_payload)
    from exercise_motion_pkg.loop_cycles import cycle_boundary_motion_metrics

    payload = _payload(_frames(_positions()))
    rejected_seed = _positions(wrap_offset=.05)
    boundary_payload = _post_support_initialization_cycle_payload(
        payload, NAMES, rejected_seed, None)
    boundary = cycle_boundary_motion_metrics(boundary_payload)

    assert 'source_support_wrap_unrepairable' in boundary['rejectionReasons']
    assert boundary['passed'] is False
    assert boundary_payload['frames'] != payload['frames']


def test_cycle_gate_uses_submitted_candidate_during_immutable_validation():
    from exercise_motion_pkg.controlled_motion import (
        _post_support_initialization_cycle_payload)
    from exercise_motion_pkg.loop_cycles import cycle_boundary_motion_metrics

    seed = _payload(_frames(_positions(wrap_offset=.05)))
    candidate = _payload(_frames(_positions()))
    rejected_seed = _positions(wrap_offset=.05)
    boundary_payload = _post_support_initialization_cycle_payload(
        seed, NAMES, rejected_seed, copy.deepcopy(candidate))
    boundary = cycle_boundary_motion_metrics(boundary_payload)

    assert boundary_payload['frames'] == candidate['frames']
    assert boundary['passed'] is True, boundary
    # The generation seed that used to gate validation still fails.
    assert cycle_boundary_motion_metrics(
        _post_support_initialization_cycle_payload(
            seed, NAMES, rejected_seed, None))['passed'] is False
