import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.joint_plant_initialization import _make_specs


def test_free_foot_geometry_follows_timed_direction_without_adding_contact_pins():
    fixture = json.loads(
        (Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    base = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    points = np.tile(base, (4, 1, 1))
    ankle_i, toe_i = names.index('left_ankle'), names.index('left_foot')
    raw_vector = points[:, toe_i] - points[:, ankle_i]
    fixed_length = float(np.linalg.norm(raw_vector[0]))
    desired_direction = Rotation.from_euler('x', 8., degrees=True).apply(
        raw_vector[0] / fixed_length)
    directions = np.zeros((len(points), 2, 3), dtype=float)
    directions[:, 0] = desired_direction
    directions[:, 1] = (points[:, names.index('right_foot')]
                        - points[:, names.index('right_ankle')])

    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[2, toe_i] = True
    targets = points.copy()
    trajectory = {
        'left': np.array([True, True, True, False]),
        'right': np.zeros(len(points), dtype=bool),
    }
    authority = {
        'left': np.array([False, False, True, False]),
        'right': np.zeros(len(points), dtype=bool),
    }

    specs, report = _make_specs(
        names, points, pinned, targets, points,
        desired_world_foot_directions=directions,
        pitch_authority_mask_by_side=authority,
        pitch_trajectory_mask_by_side=trajectory,
    )

    assert report['feasible'] is True, report
    spec = next(row for row in specs if row['side'] == 'left')
    assert spec['ankleFollowsRoot'][:2].all()
    assert spec['toeFollowsRoot'][:2].all()
    assert spec['ankleFollowsRoot'][3] and spec['toeFollowsRoot'][3]
    np.testing.assert_array_equal(pinned[:, toe_i], [False, False, True, False])

    raw_midpoint = .5 * (points[:, ankle_i] + points[:, toe_i])
    target_midpoint = .5 * (spec['targetAnkle'] + spec['targetToe'])
    np.testing.assert_allclose(target_midpoint[:2], raw_midpoint[:2], atol=1e-12)
    np.testing.assert_array_equal(spec['targetAnkle'][3], points[3, ankle_i])
    np.testing.assert_array_equal(spec['targetToe'][3], points[3, toe_i])
    for frame in (0, 1, 2):
        target_vector = spec['targetToe'][frame] - spec['targetAnkle'][frame]
        np.testing.assert_allclose(target_vector / np.linalg.norm(target_vector),
                                   desired_direction, atol=1e-12)
    np.testing.assert_allclose(spec['targetAnkle'][2],
                               targets[2, toe_i] - desired_direction * fixed_length,
                               atol=1e-12)
