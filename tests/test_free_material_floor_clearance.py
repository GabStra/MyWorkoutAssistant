"""Regression coverage for free-foot floor scoring versus owned contact IK."""

import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg.contact_interpolation import ContactFootIKUnreachable
from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.rig_playback import (
    _native_sampling_rig, decode_rig, free_material_floor_clearance_lift,
    native_active_contact_ownership, sample_rig, validate_rig_playback,
)

FIXTURES = Path(__file__).parent / 'fixtures'


def rig_payload(count=3):
    fixture = json.loads((FIXTURES / 'sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.asarray(list(fixture['joints'].values())), (count, 1, 1))
    rig = FixedRig(points, names)
    return {
        'jointNames': names, 'parents': rig.parents, 'order': rig.order,
        'offsets': rig.offsets.tolist(),
        'rotationJointNames': [names[j] for j in rig.active],
        'coordinates': rig.initial.tolist(),
    }


def native_geometry():
    return json.loads(
        (FIXTURES / 'native_foot_geometry_v1.json').read_text())['reference']


def native_side_track(points, names, native, side, active_frames, *, target_offset):
    """Build a mesh-consistent native track whose toe target is out of reach."""
    from exercise_motion_pkg.foot_geometry import shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles
    from exercise_motion_pkg.native_foot_geometry import native_foot_bone_frame

    ankle_i, foot_i = names.index(side + '_ankle'), names.index(side + '_foot')
    direction = points[:, foot_i] - points[:, ankle_i]
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    axes = np.cross(direction, np.asarray([0., 0., 1.]))
    axes /= np.linalg.norm(axes, axis=1)[:, None]
    foot_scale = .2
    triangle_index, bary = 22, np.asarray([0., 0., 1.])
    mesh = shoe_vertices(points[0, ankle_i], points[0, foot_i], axes[0], None,
                         foot_scale, native_geometry=native['sides'][side])
    material_point = bary @ mesh[shoe_triangles()[triangle_index]]
    forward, lateral, up, length = native_foot_bone_frame(
        points[0, ankle_i], points[0, foot_i], axes[0])
    delta = material_point - points[0, ankle_i]
    ref_length = native['sides'][side]['ankleToFootJointLengthMeters']
    local = np.asarray([delta @ forward, delta @ lateral, delta @ up])
    local *= ref_length / float(length[0])

    active = np.zeros(len(points), dtype=bool)
    active[list(active_frames)] = True
    anchor_ids = [f'{side}:anchor' if state else None for state in active]
    episodes = []
    for frame in active_frames:
        episodes.append({
            'startFrame': int(frame), 'endFrame': int(frame),
            'anchorId': f'{side}:anchor', 'regionRole': 'forefoot',
            'mode': 'stationary',
            'primitiveId': f'wearShoe:{side}_ankle->{side}_foot',
            'triangleIndex': triangle_index, 'barycentric': bary.tolist(),
            'materialOffsetLocalMeters': local.tolist(),
            'referenceLengthMeters': ref_length,
            'targetWorld': (material_point + np.asarray(target_offset)).tolist(),
            'surfaceNormal': [0., 1., 0.],
            'planeOffsetMeters': float(material_point[1]),
        })
    return {
        'active': active.tolist(), 'directions': direction.tolist(),
        'sideAxes': axes.tolist(), 'anchorIds': anchor_ids, 'episodes': episodes,
    }


def payload(rig, native, tracks):
    points = decode_rig(rig, rig['coordinates'])
    return {
        'fps': 30.,
        'jointNames': rig['jointNames'],
        'fixedRig': {**rig, 'contactFootTracks': tracks},
        'frames': [{'joints': dict(zip(rig['jointNames'], row.tolist()))}
                   for row in points],
        'renderFloorY': float(points[:, :, 1].min()) - .0001,
        'footRestPitchRadians': {},
        'nativeFootGeometry': native,
        'loop': {'enabled': False},
    }

@pytest.mark.parametrize('cyclic, active_frames, owned_count', [
    (False, (0, 1, 2), None),
    (True, (1,), 7),
])
def test_free_material_floor_clearance_skips_unreachable_owned_contact_ik(
        monkeypatch, cyclic, active_frames, owned_count):
    native = native_geometry()
    rig = rig_payload(3)
    coordinates = np.asarray(rig['coordinates'], dtype=float)
    coordinates[:, 1] += 2.
    rig['coordinates'] = coordinates.tolist()
    points = decode_rig(rig, rig['coordinates'])
    names = rig['jointNames']

    unreachable = native_side_track(
        points, names, native, 'left', active_frames, target_offset=[10., 0., 0.])
    tracks = {'version': 2, 'left': unreachable}
    owned = native_active_contact_ownership(
        tracks, count=len(points), cyclic=cyclic)
    assert owned['left'].any()
    if owned_count is not None:
        assert int(owned['left'].sum()) == owned_count
        assert not owned['left'][0]
        assert owned['left'][len(owned['left']) // 3]

    with pytest.raises(ContactFootIKUnreachable):
        sample_rig(_native_sampling_rig(payload(rig, native, tracks)),
                   np.asarray([.5]), wrap=cyclic, return_side_axes=True)
    playback = validate_rig_playback(payload(rig, native, tracks))
    assert playback['passed'] is False
    assert playback['reason'] == 'contact_foot_ik_unreachable'

    import exercise_motion_pkg.contact_interpolation as contact_interpolation
    solve_calls = []
    original_solve = contact_interpolation._solve_knee

    def counting_solve(*args, **kwargs):
        solve_calls.append(1)
        return original_solve(*args, **kwargs)

    monkeypatch.setattr(contact_interpolation, '_solve_knee', counting_solve)
    pinned = np.zeros(points.shape[:2], dtype=bool)
    lift = free_material_floor_clearance_lift(
        payload(rig, native, tracks), pinned, cyclic=cyclic)
    assert solve_calls == []
    assert np.isfinite(lift)

    # The same ownership with a reachable toe target exercises the ordinary
    # contact IK path yet excludes the identical owned cursors from scoring.
    reachable = native_side_track(
        points, names, native, 'left', active_frames, target_offset=[0., 0., 0.])
    baseline = free_material_floor_clearance_lift(
        payload(rig, native, {'version': 2, 'left': reachable}),
        pinned, cyclic=cyclic)
    assert lift == pytest.approx(baseline)
    assert lift > 0.
