import json
from pathlib import Path

import numpy as np
import pytest
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
    assert not spec['ankleFollowsRoot'].any()
    assert not spec['toeFollowsRoot'].any()
    np.testing.assert_array_equal(pinned[:, toe_i], [False, False, True, False])

    raw_midpoint = .5 * (points[:, ankle_i] + points[:, toe_i])
    target_midpoint = .5 * (spec['targetAnkle'] + spec['targetToe'])
    placement = target_midpoint[2] - raw_midpoint[2]
    np.testing.assert_allclose(target_midpoint - raw_midpoint,
                               np.tile(placement, (len(points), 1)), atol=1e-12)
    np.testing.assert_allclose(spec['targetToe'][3] - spec['targetAnkle'][3],
                               points[3, toe_i] - points[3, ankle_i])
    for frame in (0, 1, 2):
        target_vector = spec['targetToe'][frame] - spec['targetAnkle'][frame]
        np.testing.assert_allclose(target_vector / np.linalg.norm(target_vector),
                                   desired_direction, atol=1e-12)
    np.testing.assert_allclose(spec['targetAnkle'][2],
                               targets[2, toe_i] - desired_direction * fixed_length,
                               atol=1e-12)


@pytest.mark.parametrize(('owned_frames', 'cyclic'), [
    ([0, 1, 7, 8], False), ([2, 3, 5, 6], True),
])
def test_contact_release_carries_placement_without_retiming_or_root_follow(
        owned_frames, cyclic):
    from exercise_motion_pkg.joint_plant_initialization import _make_specs
    from exercise_motion_pkg.controlled_motion import FixedRig

    fixture = json.loads(
        (Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    base = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    source = np.tile(base, (9, 1, 1))
    # Deliberately nonuniform speed; only placement may be interpolated.
    source[:, :, 0] += np.array([0., .001, .004, .012, .023, .029, .031, .032, .032])[:, None]
    rig = FixedRig(source, names)
    points = rig.decode(rig.initial)
    ankle, toe = names.index('left_ankle'), names.index('left_foot')
    pins = np.zeros(points.shape[:2], dtype=bool)
    pins[owned_frames, ankle] = True
    pins[owned_frames, toe] = True
    original_pins = pins.copy()
    targets = points.copy()
    offset = np.array([.0, .0, .06])
    targets[:, [ankle, toe]] += offset
    specs, report = _make_specs(names, points, pins, targets, points, cyclic=cyclic)
    assert report['feasible'], report
    spec = next(s for s in specs if s['side'] == 'left')
    for label, joint in [('targetAnkle', ankle), ('targetToe', toe)]:
        np.testing.assert_allclose(spec[label], points[:, joint] + offset, atol=1e-12)
        np.testing.assert_allclose(np.diff(spec[label], axis=0),
                                   np.diff(points[:, joint], axis=0), atol=1e-12)
    assert not spec['ankleFollowsRoot'].any()
    assert not spec['toeFollowsRoot'].any()
    np.testing.assert_array_equal(pins, original_pins)
