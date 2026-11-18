"""v781: the same stationary contact split by a loop seam must share one target.

A cyclic clip can represent one continuous stationary shoe contact as the run
ending at the last frame plus the run starting at frame 0. Each contiguous run
was bound independently, so the two halves could publish different world
anchors for the same material point. That target gap is what playback
interpolates across the loop seam, so a genuinely stationary pose registers a
false residual there. These tests reconcile only that same continuous contact
and prove released / repositioned / distinct contacts keep their own targets.
"""
import numpy as np

from exercise_motion_pkg.contact_interpolation import (
    native_material_contact_tracks,
    native_material_playback_residuals,
    reconcile_cyclic_seam_material_targets,
    _native_pose_material_point,
)

NAMES = ['left_ankle', 'left_foot']
OFFSETS = np.asarray([[0., 0., 0.], [0., 0., 1.]])
DIRECTION = [0., 0., 1.]
SIDE_AXIS = [1., 0., 0.]


def _episode(start, end, anchor, target, *, triangle=0, role='forefoot'):
    return {
        'startFrame': start, 'endFrame': end, 'anchorId': anchor,
        'regionRole': role, 'mode': 'stationary',
        'primitiveId': 'wearShoe:left_ankle->left_foot',
        'triangleIndex': triangle, 'barycentric': [1., 0., 0.],
        'materialOffsetLocalMeters': [0.2, 0.0, 0.0],
        'referenceLengthMeters': 1.0,
        'targetWorld': list(target),
        'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': 0.0,
    }


def _constant_points(count):
    return np.tile(np.asarray([[0., 0., 0.], [0., 0., 1.]]), (count, 1, 1))


def _material_point(episode):
    return _native_pose_material_point(
        np.zeros(3), np.asarray([0., 0., 1.]), np.asarray(SIDE_AXIS), episode, 1.0)


def _track(episodes, count, anchors):
    return {
        'version': 2,
        'left': {
            'active': [True] * count,
            'directions': [DIRECTION] * count,
            'sideAxes': [SIDE_AXIS] * count,
            'anchorIds': list(anchors),
            'episodes': episodes,
        },
    }


def _seam_episodes(material, gap_half=0.005):
    """Two loop-seam halves of one stationary forefoot plus a mid full sole."""
    first = _episode(0, 1, 'forefoot-anchor', material + np.asarray([gap_half, 0., 0.]))
    sole = _episode(2, 2, 'sole-anchor', material + np.asarray([0., 0.02, 0.]),
                    triangle=7, role='full_sole')
    last = _episode(3, 4, 'forefoot-anchor', material - np.asarray([gap_half, 0., 0.]))
    return [first, sole, last]


def _seam_residual(tracks):
    points = _constant_points(5)
    residuals, _ = native_material_playback_residuals(
        points, NAMES, OFFSETS, tracks, np.asarray([4.5]), wrap=True,
        return_metrics=True, fractional_side_axes={'left': np.asarray([SIDE_AXIS])})
    return float(np.linalg.norm(residuals[0]))


def test_independent_seam_targets_cause_residual_and_reconciliation_fixes_it():
    """Same continuous stationary pose: split targets fail, one target passes."""
    material = _material_point(_episode(0, 1, 'forefoot-anchor', [0., 0., 0.]))
    episodes = _seam_episodes(material)
    count = 5
    anchors = ['forefoot-anchor', 'forefoot-anchor', 'sole-anchor',
               'forefoot-anchor', 'forefoot-anchor']

    independent = _track([dict(e) for e in episodes], count, anchors)
    before = _seam_residual(independent)
    assert before > 0.003
    assert abs(before - 0.005) < 1e-9

    reconciled = reconcile_cyclic_seam_material_targets(
        _track([dict(e) for e in episodes], count, anchors))
    after = _seam_residual(reconciled)
    assert after < 0.003
    assert after < 1e-9

    fore = [e for e in reconciled['left']['episodes']
            if e['anchorId'] == 'forefoot-anchor']
    assert np.allclose(fore[0]['targetWorld'], material, atol=1e-12)
    assert np.allclose(fore[1]['targetWorld'], material, atol=1e-12)
    sole = next(e for e in reconciled['left']['episodes']
                if e['anchorId'] == 'sole-anchor')
    assert np.allclose(sole['targetWorld'],
                       material + np.asarray([0., 0.02, 0.]), atol=1e-12)


def _reconciled_targets(episodes, count, anchors):
    tracks = reconcile_cyclic_seam_material_targets(_track(episodes, count, anchors))
    return [(e['anchorId'], e['targetWorld']) for e in tracks['left']['episodes']]


def test_reconciliation_preserves_released_repositioned_and_distinct_contacts():
    material = _material_point(_episode(0, 1, 'forefoot-anchor', [0., 0., 0.]))

    # Genuine release: the same anchor's second span ends before the last frame.
    released_start = _episode(0, 1, 'forefoot-anchor', material + np.asarray([0.005, 0., 0.]))
    released_end = _episode(3, 3, 'forefoot-anchor', material - np.asarray([0.005, 0., 0.]))
    assert _reconciled_targets([released_start, released_end], 5,
                               ['forefoot-anchor'] * 5) == [
        ('forefoot-anchor', (material + np.asarray([0.005, 0., 0.])).tolist()),
        ('forefoot-anchor', (material - np.asarray([0.005, 0., 0.])).tolist()),
    ]

    # Repositioned contact: different physical material point at the seam.
    moved_start = _episode(0, 1, 'forefoot-anchor', material + np.asarray([0.005, 0., 0.]))
    moved_end = _episode(3, 4, 'forefoot-anchor', material - np.asarray([0.005, 0., 0.]),
                         triangle=9)
    assert _reconciled_targets([moved_start, moved_end], 5,
                               ['forefoot-anchor'] * 5) == [
        ('forefoot-anchor', (material + np.asarray([0.005, 0., 0.])).tolist()),
        ('forefoot-anchor', (material - np.asarray([0.005, 0., 0.])).tolist()),
    ]

    # Different anchor id at the seam is not the same contact.
    other_start = _episode(0, 1, 'forefoot-anchor', material + np.asarray([0.005, 0., 0.]))
    other_end = _episode(3, 4, 'other-anchor', material - np.asarray([0.005, 0., 0.]))
    assert _reconciled_targets([other_start, other_end], 5,
                               ['forefoot-anchor', 'forefoot-anchor', 'forefoot-anchor',
                                'other-anchor', 'other-anchor']) == [
        ('forefoot-anchor', (material + np.asarray([0.005, 0., 0.])).tolist()),
        ('other-anchor', (material - np.asarray([0.005, 0., 0.])).tolist()),
    ]


def test_builder_reconciles_only_when_clip_is_cyclic():
    material = _material_point(_episode(0, 1, 'forefoot-anchor', [0., 0., 0.]))
    episodes = _seam_episodes(material)
    points = _constant_points(5)
    pinned = np.tile(np.asarray([[False, True]]), (5, 1))
    side_axes = {'left': np.tile(np.asarray([SIDE_AXIS]), (5, 1))}
    anchor_ids = np.empty((5, 2), dtype=object)
    anchor_ids[:] = None
    anchor_ids[:, 1] = ['forefoot-anchor', 'forefoot-anchor', 'sole-anchor',
                        'forefoot-anchor', 'forefoot-anchor']

    def build(cyclic):
        return native_material_contact_tracks(
            {'jointNames': NAMES}, points, pinned, side_axes,
            {'left': [dict(e) for e in episodes]}, anchor_ids=anchor_ids,
            cyclic=cyclic)

    non_cyclic = build(False)
    split = [e['targetWorld'] for e in non_cyclic['left']['episodes']
             if e['anchorId'] == 'forefoot-anchor']
    assert not np.allclose(split[0], split[1], atol=1e-9)

    cyclic_tracks = build(True)
    shared = [e['targetWorld'] for e in cyclic_tracks['left']['episodes']
              if e['anchorId'] == 'forefoot-anchor']
    assert np.allclose(shared[0], shared[1], atol=1e-12)
    assert np.allclose(shared[0], material, atol=1e-12)


def test_reconciliation_requires_identical_material_offset_and_reference_length():
    """Same triangle/anchor is not enough: the cached local material point must match."""
    material = _material_point(_episode(0, 1, 'forefoot-anchor', [0., 0., 0.]))
    start = _episode(0, 1, 'forefoot-anchor', material + np.asarray([0.005, 0., 0.]))
    end = _episode(3, 4, 'forefoot-anchor', material - np.asarray([0.005, 0., 0.]))
    anchors = ['forefoot-anchor'] * 5

    offset_end = dict(end)
    offset_end['materialOffsetLocalMeters'] = [0.2, 0.004, 0.0]
    assert _reconciled_targets([start, offset_end], 5, anchors) == [
        ('forefoot-anchor', start['targetWorld']),
        ('forefoot-anchor', offset_end['targetWorld']),
    ]

    reference_end = dict(end)
    reference_end['referenceLengthMeters'] = 0.9
    assert _reconciled_targets([start, reference_end], 5, anchors) == [
        ('forefoot-anchor', start['targetWorld']),
        ('forefoot-anchor', reference_end['targetWorld']),
    ]
