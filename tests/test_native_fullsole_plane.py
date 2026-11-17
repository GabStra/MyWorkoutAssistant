import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg.foot_geometry import shoe_vertices
from exercise_motion_pkg.material_region_support import shoe_triangles
from exercise_motion_pkg import support_geometry
from exercise_motion_pkg.support_geometry import (
    _native_foot_material_contact_residuals, geometry_errors,
)


def _fullsole_case(angle_radians=0.0, *, region_role='full_sole'):
    fixture = json.loads((Path(__file__).parent / 'fixtures' /
                          'native_foot_geometry_v1.json').read_text())
    native = fixture['reference']
    length = native['sides']['left']['ankleToFootJointLengthMeters']
    scale = 0.17678885297530408
    forward = np.asarray([np.cos(angle_radians), np.sin(angle_radians), 0.])
    axis = np.asarray([0., 0., 1.])
    triangle_index = 10  # Actual heel/midfoot bottom strip in shoe_triangles().
    barycentric = np.asarray([.2, .4, .4])
    triangles = shoe_triangles()
    triangle = triangles[triangle_index]

    base_ankle = np.zeros(3)
    base_foot = forward * length
    mesh = shoe_vertices(base_ankle, base_foot, axis, None, scale,
                         native_geometry=native['sides']['left'])
    base_target = barycentric @ mesh[triangle]
    if angle_radians:
        # Translate the pitched shoe so its exact triangle+bary point remains
        # fixed on the same support plane; only whole-sole orientation changes.
        local_anchor = barycentric @ (mesh[triangle] - base_ankle)
        ankle = base_target - local_anchor
        foot = ankle + forward * length
    else:
        ankle, foot = base_ankle, base_foot
    points = np.zeros((2, 3, 3), dtype=float)
    points[:, 0] = [0., .2, 0.]
    points[:, 1] = ankle
    points[:, 2] = foot
    track = {
        'version': 2,
        'left': {
            'active': [True, True],
            'anchorIds': ['left:sole:0', 'left:sole:0'],
            'directions': [forward.tolist(), forward.tolist()],
            'sideAxes': [axis.tolist(), axis.tolist()],
            'episodes': [{
                'startFrame': 0, 'endFrame': 1, 'anchorId': 'left:sole:0',
                'regionRole': region_role, 'mode': 'stationary',
                'primitiveId': 'wearShoe:left_ankle->left_foot',
                'triangleIndex': triangle_index,
                'barycentric': barycentric.tolist(),
                'materialOffsetLocalMeters': [0., 0., 0.],
                'referenceLengthMeters': length,
                'targetWorld': base_target.tolist(),
                'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': 0.,
            }],
        },
    }
    evidence = {
        'required': True, 'status': 'confirmed',
        'soleContacts': [{
            'joints': ['left_knee', 'left_ankle', 'left_foot'],
            'normal': [0., 1., 0.],
        }],
        '_nativeFootMaterialTracks': track,
        'nativeFootGeometry': native,
        '_nativeFootScale': scale,
    }
    return points, evidence


def test_native_fullsole_plane_uses_mesh_heel_midfoot_and_forefoot_not_only_anchor():
    flat, evidence = _fullsole_case()
    flat_rows = geometry_errors(flat, ['left_knee', 'left_ankle', 'left_foot'], evidence)
    assert flat_rows.shape == (2, 11)  # legacy proxy + point/penetration + six sole samples
    np.testing.assert_allclose(flat_rows[:, 0], 0., atol=1e-10)
    np.testing.assert_allclose(flat_rows[:, -6:], 0., atol=1e-8)

    tilted, same_anchor_evidence = _fullsole_case(np.deg2rad(8.))
    tilted_rows = geometry_errors(
        tilted, ['left_knee', 'left_ankle', 'left_foot'], same_anchor_evidence)
    # The bound barycentric point remains fixed; the actual mesh plane catches
    # heel/toe lift that a point-only constraint would miss.
    np.testing.assert_allclose(tilted_rows[:, 1:4], 0., atol=1e-8)
    assert np.max(np.abs(tilted_rows[0, -6:])) > .005
    assert np.max(np.abs(tilted_rows[0, 1:])) > .005


def test_legacy_sole_pitch_remains_required_without_fullsole_native_coverage():
    points, evidence = _fullsole_case(region_role='forefoot')
    evidence.pop('_nativeFootMaterialTracks')
    evidence.pop('nativeFootGeometry')
    evidence.pop('_nativeFootScale')
    rows = geometry_errors(points, ['left_knee', 'left_ankle', 'left_foot'], evidence)
    assert np.any(np.abs(rows[:, 0]) > .005)


def test_support_validator_uses_normalized_native_evidence_override(monkeypatch):
    names = ['left_knee', 'left_ankle', 'left_foot']
    monkeypatch.setattr(support_geometry, 'support_contact_readiness',
                        lambda *args, **kwargs: {'passed': True})
    monkeypatch.setattr(support_geometry, 'evidence_is_complete', lambda *args: True)

    flat, evidence = _fullsole_case()
    payload = {'jointNames': names, 'frames': [
        {'joints': dict(zip(names, row.tolist()))} for row in flat]}
    passing = support_geometry.validate_support_geometry(
        payload, flat, names, evidence_override=evidence)
    assert passing['passed']

    tilted, tilted_evidence = _fullsole_case(np.deg2rad(8.))
    rejected = support_geometry.validate_support_geometry(
        payload, tilted, names, evidence_override=tilted_evidence)
    assert not rejected['passed']
    assert 'support_surface_geometry_mismatch' in rejected['rejectionReasons']


def test_bilateral_native_orientation_residual_uses_physical_shoe_extent():
    fixture = json.loads((Path(__file__).parent / 'fixtures' /
                          'native_foot_geometry_v1.json').read_text())
    native = fixture['reference']
    names = ['left_hip', 'right_hip', 'left_ankle', 'left_foot',
             'right_ankle', 'right_foot']
    length = native['sides']['left']['ankleToFootJointLengthMeters']
    scale = 0.17678885297530408
    points = np.asarray([[[-.1, 1., 0.], [.1, 1., 0.], [-.1, 0., 0.],
                          [-.1, 0., length], [.1, 0., 0.], [.1, 0., length]]])
    left_axis = np.asarray([-1., 0., 0.])
    angle = np.deg2rad(12.)
    right_axis = np.asarray([-np.cos(angle), -np.sin(angle), 0.])
    tracks = {'version': 2}
    for side, axis in (('left', left_axis), ('right', right_axis)):
        tracks[side] = {
            'active': [False], 'anchorIds': [None],
            'directions': [[0., 0., 1.]], 'sideAxes': [axis.tolist()],
            'episodes': [],
        }
    evidence = {'_nativeFootMaterialTracks': tracks,
                'nativeFootGeometry': native, '_nativeFootScale': scale,
                '_nativeFootMirrorRequired': True}

    residuals, errors = _native_foot_material_contact_residuals(points, names, evidence)
    assert not errors
    assert residuals.shape == (1, 6)
    np.testing.assert_allclose(residuals[0, :3], 0., atol=1e-12)

    # Express the mirror orientation error as displacement at the actual
    # generated mesh's lateral extent, in meters.
    reflection_axis = np.asarray([1., 0., 0.])
    reflected_right = right_axis - 2. * reflection_axis * np.dot(
        right_axis, reflection_axis)
    expected_direction_delta = left_axis + reflected_right
    left_mesh = shoe_vertices(points[0, 2], points[0, 3], left_axis, None, scale,
                              native_geometry=native['sides']['left'])
    right_mesh = shoe_vertices(points[0, 4], points[0, 5], right_axis, None, scale,
                               native_geometry=native['sides']['right'])
    left_reach = np.max(np.abs((left_mesh - points[0, 2]) @ left_axis))
    right_reach = np.max(np.abs((right_mesh - points[0, 4]) @ right_axis))
    lateral_reach = max(left_reach, right_reach)
    np.testing.assert_allclose(residuals[0, 3:],
                               expected_direction_delta * lateral_reach, atol=1e-12)
    assert np.max(np.abs(residuals[0, 3:])) > .005
