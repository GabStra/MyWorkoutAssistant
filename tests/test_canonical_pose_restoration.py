import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg.contact_interpolation import build_contact_foot_tracks
from exercise_motion_pkg.controlled_motion import FixedRig, canonical_bilateral_reference
from exercise_motion_pkg.rig_playback import sample_rig
from exercise_motion_pkg.trajectory_restoration import canonical_pose_metrics_and_jacobian


def _canonical_restore_case():
    fixture = json.loads(
        (Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json')
        .read_text(encoding='utf-8')
    )
    names = list(fixture['joints'])
    frame = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    points = np.repeat(frame[None, :, :], 6, axis=0)
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    pinned = np.zeros((len(points), len(names)), dtype=bool)
    anchor_ids = np.full(pinned.shape, None, dtype=object)
    for side in ('left', 'right'):
        foot = names.index(f'{side}_foot')
        pinned[:, foot] = True
        anchor_ids[:, foot] = f'{side}-source-anchor'
    tracks = build_contact_foot_tracks(rig, points, pinned, anchor_ids=anchor_ids)
    fixed_rig = {
        'version': 1,
        'jointNames': list(names),
        'parents': rig.parents,
        'order': rig.order,
        'offsets': rig.offsets.tolist(),
        'rotationJointNames': [names[index] for index in rig.active],
        'coordinates': coordinates.tolist(),
        'contactFootTracks': tracks,
    }
    policy = {
        'rig_payload': fixed_rig,
        'execution': {'legs': 'mirrored'},
        'joint_names': names,
        'cyclic': False,
        'subdivisions': 4,
        'safety_margin': 100.,
    }
    return names, rig, coordinates, tracks, policy


def test_canonical_pose_measures_refresh_track_geometry_and_keep_source_identity():
    from exercise_motion_pkg.contact_interpolation import refresh_contact_foot_tracks

    names, rig, coordinates, tracks, policy = _canonical_restore_case()
    ankle = names.index('right_ankle')
    rotation_slot = 3 + 3 * list(rig.active).index(ankle)
    candidate = coordinates.copy()
    candidate[2, rotation_slot + 2] += .12
    # Translation moves the candidate FK-derived toe targets. A stale track
    # still pins these feet to the old world-space locations.
    candidate[:, 0] += .03
    keypoints = rig.decode(candidate)
    refreshed = refresh_contact_foot_tracks(rig, keypoints, tracks)

    cursors = np.arange((len(candidate) - 1) * 4 + 1, dtype=float) / 4.
    target = canonical_bilateral_reference(
        sample_rig({**policy['rig_payload'], 'coordinates': candidate.tolist(),
                    'contactFootTracks': refreshed}, cursors),
        names, policy['execution'],
    )
    refreshed_points = sample_rig(
        {**policy['rig_payload'], 'coordinates': candidate.tolist(),
         'contactFootTracks': refreshed}, cursors,
    )
    stale_points = sample_rig(
        {**policy['rig_payload'], 'coordinates': candidate.tolist(),
         'contactFootTracks': tracks}, cursors,
    )
    expected = np.linalg.norm(refreshed_points - target, axis=-1) / .0005 - 1.

    labels, values, jacobian, full = canonical_pose_metrics_and_jacobian(
        candidate, rig, policy, projected_coordinates=candidate,
        compute_jacobian=False,
    )

    np.testing.assert_allclose(full, expected, atol=1e-10, rtol=1e-10)
    assert len(labels) == values.size == full.size
    assert jacobian.shape == (full.size, candidate.size)
    assert np.max(np.abs(refreshed_points - stale_points)) > 1e-6
    for side in ('left', 'right'):
        assert refreshed[side]['active'] == tracks[side]['active']
        assert refreshed[side]['anchorIds'] == tracks[side]['anchorIds']
    assert policy['rig_payload']['contactFootTracks'] == tracks


def test_canonical_pose_colored_jacobian_includes_root_translation_columns():
    names, rig, coordinates, _, policy = _canonical_restore_case()
    candidate = coordinates.copy()
    candidate[2, 0] += .01
    labels, values, jacobian, full = canonical_pose_metrics_and_jacobian(
        candidate, rig, policy, projected_coordinates=candidate,
        compute_jacobian=True,
    )
    assert len(labels) == values.size == full.size
    assert jacobian.shape == (len(labels), candidate.size)
    assert len(policy['last_jacobian_diagnostics']['selectedRows']) == len(labels)

    epsilon = 2e-6
    plus, minus = candidate.copy(), candidate.copy()
    plus[2, 0] += epsilon
    minus[2, 0] -= epsilon
    plus_values = canonical_pose_metrics_and_jacobian(
        plus, rig, policy, projected_coordinates=plus, compute_jacobian=False,
    )[1]
    minus_values = canonical_pose_metrics_and_jacobian(
        minus, rig, policy, projected_coordinates=minus, compute_jacobian=False,
    )[1]
    finite_difference = (plus_values - minus_values) / (2. * epsilon)
    root_translation_column = jacobian[:, 2 * rig.width].toarray().ravel()
    np.testing.assert_allclose(
        root_translation_column, finite_difference, atol=2e-4, rtol=2e-3,
    )
