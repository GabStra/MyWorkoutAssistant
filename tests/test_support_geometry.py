from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.support_geometry import (
    declare_support_requirements, geometry_errors, validate_support_geometry,
)


def test_native_material_side_axis_uses_incoming_foot_bone_fk_rotation():
    from exercise_motion_pkg import controlled_motion as motion

    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    pose = np.asarray([fixture['joints'][name] for name in names], dtype=float)
    rig = motion.FixedRig(np.asarray([pose]), names)
    ankle = names.index('left_ankle')
    foot = names.index('left_foot')
    assert foot in rig.slots
    source_axis = rig.global_rotations(rig.initial)[foot][0] @ np.array([1., 0., 0.])
    baseline = rig.material_side_axes(rig.initial, source_axis[None, :], 'left')
    twist = Rotation.from_rotvec([0., .6, 0.])

    # Twist the incoming foot-bone owner about its rest offset: all joint
    # points stay fixed, while the material surface frame changes.
    rolled = rig.initial.copy()
    slot = rig.slots[foot]
    local = Rotation.from_rotvec(rolled[0, slot:slot + 3])
    rolled[0, slot:slot + 3] = (local * twist).as_rotvec()
    np.testing.assert_allclose(rig.decode(rolled), rig.decode(rig.initial), atol=1e-10)
    current = rig.material_side_axes(rolled, source_axis[None, :], 'left')
    assert np.linalg.norm(current - baseline) > .1
    from exercise_motion_pkg.foot_geometry import shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles
    native = json.loads((Path(__file__).parent/'fixtures/native_foot_geometry_v1.json').read_text())['reference']
    points = rig.decode(rig.initial)
    triangle = shoe_triangles()[12]
    barycentric = np.asarray([.2, .3, .5])
    def bound_material(axis):
        mesh = shoe_vertices(points[0, ankle], points[0, foot], axis[0], None, .5,
                             native_geometry=native['sides']['left'])
        return barycentric @ mesh[triangle]
    target = bound_material(baseline)
    assert np.linalg.norm(bound_material(current) - target) > .01

    # Counterrotate the ankle parent and foot child: FK foot matrix and all
    # points stay fixed, so material side must not follow the shin matrix.
    compensated = rig.initial.copy()
    ankle_slot = rig.slots[ankle]
    ankle_local = Rotation.from_rotvec(compensated[0, ankle_slot:ankle_slot + 3])
    compensated[0, ankle_slot:ankle_slot + 3] = (ankle_local * twist).as_rotvec()
    foot_slot = rig.slots[foot]
    foot_local = Rotation.from_rotvec(compensated[0, foot_slot:foot_slot + 3])
    compensated[0, foot_slot:foot_slot + 3] = (twist.inv() * foot_local).as_rotvec()
    np.testing.assert_allclose(rig.decode(compensated), rig.decode(rig.initial), atol=1e-10)
    actual_foot = rig.global_rotations(compensated)[foot]
    original_foot = rig.global_rotations(rig.initial)[foot]
    np.testing.assert_allclose(actual_foot, original_foot, atol=1e-10)
    unchanged = rig.material_side_axes(compensated, source_axis[None, :], 'left')
    np.testing.assert_allclose(unchanged, baseline, atol=1e-10)


def test_native_bilateral_side_axis_mirror_uses_axial_vector_parity():
    from exercise_motion_pkg.support_geometry import _native_foot_material_contact_residuals

    native = json.loads((Path(__file__).parent/'fixtures/native_foot_geometry_v1.json').read_text())['reference']
    names = ['left_hip', 'right_hip', 'left_ankle', 'left_foot',
             'right_ankle', 'right_foot']
    points = np.asarray([[[-.1, 1., 0.], [.1, 1., 0.], [-.1, 0., 0.],
                          [-.1, 0., 1.], [.1, 0., 0.], [.1, 0., 1.]]])
    tracks = {'version': 2}
    for side in ('left', 'right'):
        tracks[side] = {'active': [False], 'directions': [[0., 0., 1.]],
                        'sideAxes': [[-1., 0., 0.]], 'episodes': []}
    evidence = {'_nativeFootMaterialTracks': tracks,
                'nativeFootGeometry': native,
                '_nativeFootMirrorRequired': True}
    values, errors = _native_foot_material_contact_residuals(
        points, names, evidence)
    assert not errors
    assert values.shape == (1, 6)
    np.testing.assert_allclose(values, 0., atol=1e-12)


def test_supported_initializer_owns_native_free_shoe_floor_and_atomic_acceptance(monkeypatch):
    from time import monotonic
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as c
    from exercise_motion_pkg.shoe_floor import ShoeFloorConstraint
    from exercise_motion_pkg.support_geometry import initialize_supported_motion
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    rig = c.FixedRig(np.tile([fixture['joints'][n] for n in names], (3, 1, 1)), names)
    points = rig.decode(rig.initial)
    payload = {'jointNames': names, 'frames': [{'joints': dict(zip(names, row.tolist()))} for row in points],
               'renderFloorY': -10., 'footRestPitchRadians': {}}
    shoes = ShoeFloorConstraint(rig, payload)
    payload['renderFloorY'] = float(shoes.heights(rig.initial.ravel()).min()-10.-.01)
    entry = rig.initial.copy()
    evidence = {'stationaryJoints': ['left_knee', 'right_knee'], '_materialShoePayload': payload}
    # Unknown contacts and absent pitch still require actual shoe clearance.
    def solve_bad(residual, initial, pattern, max_evaluations, **options):
        candidate = initial.reshape(entry.shape).copy()
        candidate[:, 1] -= .2
        assert np.any(residual(candidate.ravel())[-6:] < -1.)
        return SimpleNamespace(x=candidate.ravel(), nfev=1)
    monkeypatch.setattr(c, 'solve_trajectory', solve_bad)
    calibration = {}
    initialize_supported_motion(rig, points, evidence, points[0], calibration, monotonic()+10.)
    np.testing.assert_array_equal(rig.initial, entry)
    assert calibration['shoeFloorNonRegressionGuard']
    def solve_timeout(*args, **kwargs):
        solve_bad(*args, **kwargs)
        raise TimeoutError
    monkeypatch.setattr(c, 'solve_trajectory', solve_timeout)
    import pytest
    with pytest.raises(TimeoutError):
        initialize_supported_motion(rig, points, evidence, points[0], {}, monotonic()+10.)
    np.testing.assert_array_equal(rig.initial, entry)
    def solve_clear(residual, initial, pattern, max_evaluations, **options):
        candidate = initial.reshape(entry.shape).copy()
        candidate[:, 1] += .02
        assert np.all(residual(candidate.ravel())[-6:] == 0.)
        return SimpleNamespace(x=candidate.ravel(), nfev=1)
    monkeypatch.setattr(c, 'solve_trajectory', solve_clear)
    initialize_supported_motion(rig, points, evidence, points[0], {}, monotonic()+10.)
    np.testing.assert_allclose(rig.initial[:, 1], entry[:, 1]+.02)
    assert not payload['footRestPitchRadians'] and 'supportContacts' not in payload
    # A local frame is evaluated in its original global stored-frame context.
    from copy import copy
    local = copy(rig)
    local.initial = entry[1:2].copy()
    constraint = ShoeFloorConstraint(local, payload, frame_positions=np.array([1]), context=points)
    jacobian = constraint.jacobian(local.initial.ravel()).toarray()
    step = 1e-6
    plus, minus = local.initial.copy(), local.initial.copy()
    plus[:, 1] -= .2-step
    minus[:, 1] -= .2+step
    buried = local.initial.copy(); buried[:, 1] -= .2
    derivative = (constraint.residual(plus.ravel())-constraint.residual(minus.ravel()))/(2*step)
    np.testing.assert_allclose(constraint.jacobian(buried.ravel()).toarray()[:, 1], derivative, atol=1e-6)
    assert jacobian.shape == (6, local.width)
    local.initial = entry[:1].copy()
    local.initial[:, 1] -= .2
    context = points.copy(); context[:, :, 1] -= .2
    constraint = ShoeFloorConstraint(local, payload, frame_positions=np.array([0]), context=context)
    actual = constraint.jacobian(local.initial.ravel()).toarray()
    expected = np.empty_like(actual)
    for column in range(local.width):
        plus, minus = local.initial.ravel().copy(), local.initial.ravel().copy()
        plus[column] += step; minus[column] -= step
        expected[:, column] = (constraint.residual(plus)-constraint.residual(minus))/(2*step)
    np.testing.assert_allclose(actual, expected, atol=2e-6)
    assert np.any(np.abs(expected[2:]) > 1e-7), 'A first-frame shoe side must affect later native shoes'
    from exercise_motion_pkg.foot_geometry import shoe_orientation_context
    anchored_payload = {**payload, 'groundContactMode': 'continuous'}
    with shoe_orientation_context({'states': {'left': ['full_sole', 'unknown', 'full_sole'],
                                             'right': ['unknown']*3},
                                   'ground': np.ones(points.shape[:2], dtype=bool), 'planeGroups': []}):
        anchored = ShoeFloorConstraint(local, anchored_payload, frame_positions=np.array([0]), context=context)
        actual = anchored.jacobian(local.initial.ravel()).toarray()
        for column in range(local.width):
            plus, minus = local.initial.ravel().copy(), local.initial.ravel().copy()
            plus[column] += step; minus[column] -= step
            expected[:, column] = (anchored.residual(plus)-anchored.residual(minus))/(2*step)
        np.testing.assert_allclose(actual, expected, atol=2e-6)


def test_support_head_preservation_uses_body_relative_source_articulation():
    from exercise_motion_pkg.support_geometry import _head_articulation_residual
    names = ['left_hip', 'right_hip', 'pelvis', 'neck', 'head']
    source = np.array([[[-.2, 0., 0.], [.2, 0., 0.], [0., 0., 0.],
                        [0., 1., 0.], [0., 1.2, 0.]]])
    candidate = source.copy()
    angle = np.deg2rad(45.)
    candidate[:, -1] = [0., 1.+.2*np.cos(angle), .2*np.sin(angle)]
    assert np.isclose(_head_articulation_residual(candidate, source, names)[0, 0],
                      np.deg2rad(31.))
    rotation = Rotation.from_euler('xyz', [30., 20., 10.], degrees=True)
    rotated = rotation.apply(source.reshape(-1, 3)).reshape(source.shape) + 3.
    np.testing.assert_allclose(_head_articulation_residual(rotated, source, names), 0., atol=1e-8)


def test_supported_chain_range_keeps_immutable_source_angles():
    from exercise_motion_pkg.support_geometry import moving_support_articulations
    names = [f'{side}_{part}' for side in ('left', 'right') for part in ('hip', 'shoulder', 'elbow', 'wrist')]
    original = np.zeros((12, len(names), 3))
    corrected = original.copy()
    for values, excursion in ((original, 90.), (corrected, 45.)):
        theta = np.deg2rad(np.linspace(-40., -40.+excursion, 12))
        for side in ('left', 'right'):
            values[:, names.index(f'{side}_hip'), 1] = -1.
            values[:, names.index(f'{side}_elbow')] = np.c_[np.cos(theta), np.sin(theta), np.zeros(12)]
            values[:, names.index(f'{side}_wrist')] = values[:, names.index(f'{side}_elbow')] + [0., -.2, 0.]
    tracks = {label: track for label, _, track in moving_support_articulations(
        original, names, {'stationaryJoints': ['right_wrist']}, support_corrected_points=corrected)}
    assert np.isclose(np.rad2deg(np.ptp(tracks['left_shoulder'])), 90.)
    assert np.isclose(np.rad2deg(np.ptp(tracks['right_shoulder'])), 90.)
    # Placement/support endpoints do not redefine the source's angular excursion.
    paired = {label: track for label, _, track in moving_support_articulations(
        original, names, {}, support_corrected_points=corrected,
        constraint_endpoints=['left_wrist', 'right_wrist'])}
    assert np.isclose(np.rad2deg(np.ptp(paired['left_shoulder'])), 90.)
    # Grip equipment is not planted support: feet-only evidence must keep free-arm
    # source ROM even when a bar/dumbbell endpoint pair exists.
    feet_only = {label: track for label, _, track in moving_support_articulations(
        original, names, {'stationaryJoints': ['left_hip', 'right_hip']},
        support_corrected_points=corrected)}
    assert np.isclose(np.rad2deg(np.ptp(feet_only['left_shoulder'])), 90.)
    assert np.isclose(np.rad2deg(np.ptp(feet_only['right_shoulder'])), 90.)


def test_supported_reference_includes_partial_contacts_and_rigid_grip():
    from time import monotonic
    from exercise_motion_pkg.controlled_motion import FixedRig
    from exercise_motion_pkg.rig_playback import rig_contact_targets
    from exercise_motion_pkg.equipment_constraints import calibrated_grip_constraint, validate_grip
    from exercise_motion_pkg.support_geometry import calibrate_support_pose, initialize_supported_motion
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile([fixture['joints'][n] for n in names], (8, 1, 1))
    rig = FixedRig(points, names)
    points = rig.decode(rig.initial)
    feet = ['left_foot', 'right_foot']
    floor = float(points[0, names.index('left_foot'), 1])-.02
    evidence = {'required': True, 'status': 'confirmed', 'stationaryJoints': feet,
                'coplanarGroups': [{'joints': feet, 'normal': [0., 1., 0.], 'planeOffsetMeters': floor}]}
    pose, calibration = calibrate_support_pose(rig, points, evidence)
    assert pose is not None
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, [names.index(n) for n in feet]] = True
    pinned[2:6, names.index('right_ankle')] = True
    targets, _ = rig_contact_targets(points, names, pinned, rig.offsets,
                                     stationary_positions={n: pose[names.index(n)] for n in feet})
    grip = calibrated_grip_constraint({'equipmentConstraints': {'handRelationship': 'rigid_pair'}}, points, names)
    grip['distanceMeters'] *= .95
    result = initialize_supported_motion(rig, points, evidence, pose, calibration, monotonic()+30,
                                         pinned=pinned, contact_targets=targets, equipment=grip)
    assert np.max(np.linalg.norm((result-targets)[pinned], axis=-1)) < .0005
    assert validate_grip(result, names, grip)['passed']


def supported_payload():
    names = ['pelvis', 'spine', 'neck', 'left_foot', 'right_foot']
    joints = dict(zip(names, [[0, 1, 0], [.5, 1.03, 0], [1, 1, 0], [0, 0, -.2], [0, 0, .2]]))
    evidence = {'required': True, 'status': 'confirmed', 'stationaryJoints': names,
                'coplanarGroups': [{'joints': ['left_foot', 'right_foot'], 'normal': [0, 1, 0]}],
                'nonPenetrationChains': [{'endpoints': ['pelvis', 'neck'],
                                         'joints': ['spine'], 'normal': [0, 1, 0]}]}
    return {'jointNames': names, 'frames': [{'joints': deepcopy(joints)} for _ in range(12)],
            'sourceFootSupportEvidence': {'bodySupport': evidence}}


def test_detects_bounce_sag_and_wrong_surface_without_flattening_valid_arch():
    base = supported_payload()
    assert validate_support_geometry(base)['passed']
    for name, axis, amount, reason in [
        ('pelvis', 1, .03, 'supported_body_moves'),
        ('spine', 1, -.08, 'support_surface_geometry_mismatch'),
        ('right_foot', 1, .1, 'support_surface_geometry_mismatch'),
    ]:
        current = deepcopy(base)
        current['frames'][5]['joints'][name][axis] += amount
        assert reason in validate_support_geometry(current)['rejectionReasons']


def test_geometry_is_invariant_under_camera_rotation_and_translation():
    current = supported_payload()
    current['frames'][0]['joints']['spine'][1] -= .08
    names = current['jointNames']
    points = np.array([[f['joints'][n] for n in names] for f in current['frames']])
    evidence = current['sourceFootSupportEvidence']['bodySupport']
    expected = geometry_errors(points, names, evidence)
    rotation = Rotation.from_euler('xyz', [41, -63, 19], degrees=True)
    rotated = deepcopy(evidence)
    for group in rotated['coplanarGroups'] + rotated['nonPenetrationChains']:
        group['normal'] = rotation.apply(group['normal']).tolist()
    actual = geometry_errors(rotation.apply(points.reshape(-1, 3)).reshape(points.shape)+[3, 2, 1], names, rotated)
    np.testing.assert_allclose(actual, expected, atol=1e-12)


def test_observed_support_prevents_lowered_endpoint_from_legitimizing_sag():
    current = supported_payload()
    current['jointNames'] += ['left_shoulder', 'right_shoulder']
    evidence = current['sourceFootSupportEvidence']['bodySupport']
    evidence['coplanarGroups'].append({'joints': ['pelvis', 'left_shoulder', 'right_shoulder'],
                                      'normal': [0, 1, 0]})
    for frame in current['frames']:
        frame['joints'].update(left_shoulder=[.9, 1., -.2], right_shoulder=[.9, 1., .2])
    assert validate_support_geometry(current)['passed']  # Natural positive arch remains allowed.
    for frame in current['frames']:
        frame['joints']['neck'][1] = .96
        frame['joints']['spine'][1] = .99  # Above the old chord, below the actual support.
    assert not validate_support_geometry(current)['passed']
    names = current['jointNames']
    points = np.array([[f['joints'][n] for n in names] for f in current['frames']])
    expected = geometry_errors(points, names, evidence)
    rotation = Rotation.from_euler('xyz', [41, -63, 19], degrees=True)
    transformed = deepcopy(evidence)
    for group in transformed['coplanarGroups'] + transformed['nonPenetrationChains']:
        group['normal'] = rotation.apply(group['normal']).tolist()
    actual = geometry_errors(rotation.apply(points.reshape(-1, 3)).reshape(points.shape)+[3, 2, 1],
                             names, transformed)
    np.testing.assert_allclose(actual, expected, atol=1e-12)


def test_unknown_support_blocks_instead_of_inventing_contacts():
    current = supported_payload()
    current['sourceFootSupportEvidence']['bodySupport']['status'] = 'unknown'
    assert validate_support_geometry(current)['rejectionReasons'] == ['supported_body_evidence_unresolved']


def test_unresolved_source_frame_indexes_keep_empty_anchor_tracks_sized():
    from exercise_motion_pkg.support_geometry import support_contact_masks

    evidence = {
        '_fitFrameStateIndices': [-1, -1, -1],
        'footPatchEvidence': {
            'available': True,
            'feet': {'left': {'states': []}},
        },
    }

    masks, anchor_ids = support_contact_masks(
        evidence, ['left_ankle'], 3, frame_positions=[0., 1., 2.],
    )

    assert masks.shape == (3, 1)
    assert not masks.any()
    assert anchor_ids.shape == (3, 1)
    assert all(value is None for value in anchor_ids.flat)


def test_incomplete_confirmed_support_cannot_silently_pass():
    for value in ([], ['missing_joint']):
        current = supported_payload()
        current['sourceFootSupportEvidence']['bodySupport']['stationaryJoints'] = value
        assert not validate_support_geometry(current)['passed']
    current = supported_payload()
    current['frames'][0]['joints']['spine'][1] = float('nan')
    assert not validate_support_geometry(current)['passed']


def test_support_requirements_do_not_freeze_active_torso_or_standing_exercises():
    for primary, mode in [(['torso'], 'lying'), (['hips'], 'lying'), (['elbows'], 'standing')]:
        current = {}
        declare_support_requirements(current, {'primaryMovingRegions': primary,
            'referenceRegions': ['torso'], 'startPoseConstraints': {'supportMode': mode}})
        assert validate_support_geometry(current)['passed']
    current = {}
    declare_support_requirements(current, {'primaryMovingRegions': ['elbows'],
        'referenceRegions': ['torso'], 'startPoseConstraints': {'supportMode': 'lying'}})
    assert validate_support_geometry(current)['passed']  # Contract posture alone does not establish contact.


def test_rebasing_support_does_not_rotate_free_arms_with_the_spine():
    from exercise_motion_pkg.controlled_motion import FixedRig, joint_dependencies
    from exercise_motion_pkg.support_geometry import preserve_free_limb_motion
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile([fixture['joints'][n] for n in names], (8, 1, 1))
    rig = FixedRig(points, names)
    original = rig.decode(rig.initial)
    stationary = ['pelvis', 'neck', 'left_shoulder', 'right_shoulder']
    frozen = joint_dependencies(rig, stationary).astype(bool)
    slot = rig.slots[rig.root]
    rig.initial[:, slot:slot+3] = (Rotation.from_euler('z', 15, degrees=True)*
        Rotation.from_rotvec(rig.initial[:, slot:slot+3])).as_rotvec()
    anchored_before = rig.decode(rig.initial)
    preserve_free_limb_motion(rig, original, stationary, frozen)
    result = rig.decode(rig.initial)
    for name in stationary:
        np.testing.assert_allclose(result[:, names.index(name)], anchored_before[:, names.index(name)], atol=1e-12)
    for side in ('left', 'right'):
        for a, b in [('shoulder', 'elbow'), ('elbow', 'wrist'), ('wrist', 'hand')]:
            ia, ib = names.index(side+'_'+a), names.index(side+'_'+b)
            np.testing.assert_allclose(result[:, ib]-result[:, ia], original[:, ib]-original[:, ia], atol=1e-10)


def test_equal_toe_heights_do_not_hide_pitch_or_constrain_knee_articulation():
    names = ['knee', 'ankle', 'foot']
    points = np.array([[[0., 1., 0.], [0., 0., 0.], [.2, 0., 0.]]])
    evidence = {'soleContacts': [{'joints': names, 'normal': [0, 1, 0]}],
                'materialFootRestPitchRadians': {'ankle': 0.}}
    np.testing.assert_allclose(geometry_errors(points, names, evidence), 0.)
    changed = points.copy()
    changed[0, 1, 1] += .1
    assert np.max(np.abs(geometry_errors(changed, names, evidence))) > .005
    moving_knee = points.copy()
    moving_knee[0, 0, 2] += .1
    np.testing.assert_allclose(geometry_errors(moving_knee, names, evidence), 0.)
    rotation = Rotation.from_euler('xyz', [42, 19, -31], degrees=True)
    transformed = deepcopy(evidence)
    transformed['soleContacts'][0]['normal'] = rotation.apply([0, 1, 0]).tolist()
    np.testing.assert_allclose(
        geometry_errors(rotation.apply(changed[0])[None]+[3, 2, 1], names, transformed),
        geometry_errors(changed, names, evidence), atol=1e-12)


def test_full_sole_geometry_uses_calibrated_material_pitch_not_horizontal_ankle_toe_bone():
    from exercise_motion_pkg.support_geometry import geometry_errors

    rest_pitch = np.deg2rad(-19.)
    length = .2
    ankle = np.array([0., -length*np.sin(rest_pitch), 0.])
    toe = ankle + np.array([length*np.cos(rest_pitch), length*np.sin(rest_pitch), 0.])
    points = np.array([[0., 1., 0.], ankle, toe])
    names = ['left_knee', 'left_ankle', 'left_foot']
    evidence = {
        'soleContacts': [{'joints': names, 'normal': [0., 1., 0.]}],
        'materialFootRestPitchRadians': {'left': rest_pitch},
    }

    np.testing.assert_allclose(geometry_errors(points[None], names, evidence), 0., atol=1e-12)
    flattened = points.copy()
    flattened[2, 1] = flattened[1, 1]
    assert np.max(np.abs(geometry_errors(flattened[None], names, evidence))) > .005


def test_contact_projection_preserves_unconstrained_head_articulation():
    from time import monotonic
    from exercise_motion_pkg.controlled_motion import FixedRig
    from exercise_motion_pkg.support_geometry import initialize_supported_motion
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile([fixture['joints'][n] for n in names], (8, 1, 1))
    rig = FixedRig(points, names)
    slot = rig.slots[names.index('head')]
    rig.initial[:, slot] += np.linspace(-.08, .08, len(points))
    original = rig.decode(rig.initial)
    pose = original[4]
    evidence = {'required': True, 'status': 'confirmed', 'stationaryJoints': ['pelvis']}
    result = initialize_supported_motion(rig, original, evidence, pose,
        {'coordinates': rig.initial[4].tolist()}, monotonic()+30)
    assert np.linalg.norm(np.ptp(result[:, names.index('head')], axis=0)) > .01
    assert validate_support_geometry({'sourceFootSupportEvidence': {'bodySupport': evidence}}, result, names)['passed']


def test_surface_dependencies_cover_every_changed_residual():
    from exercise_motion_pkg.controlled_motion import FixedRig
    from exercise_motion_pkg.support_geometry import geometry_dependencies
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.array([[fixture['joints'][n] for n in names]])
    rig = FixedRig(points, names)
    evidence = {'soleContacts': [{'joints': ['left_knee', 'left_ankle', 'left_foot'], 'normal': [0, 1, 0]}],
        'materialFootRestPitchRadians': {'left': 0.},
        'coplanarGroups': [{'joints': ['left_foot', 'right_foot'], 'normal': [0, 1, 0], 'planeOffsetMeters': 0.},
                          {'joints': ['pelvis', 'left_shoulder', 'right_shoulder'], 'normal': [0, 1, 0]}],
        'nonPenetrationChains': [{'endpoints': ['pelvis', 'neck'], 'joints': ['spine1'], 'normal': [0, 1, 0]}]}
    pattern = geometry_dependencies(rig, evidence)
    baseline = geometry_errors(rig.decode(rig.initial), names, evidence)[0]
    for column in range(rig.width):
        changed = rig.initial.copy()
        changed[0, column] += .01
        delta = geometry_errors(rig.decode(changed), names, evidence)[0]-baseline
        assert np.all(pattern[np.abs(delta) > 1e-10, column])


def test_planted_feet_projection_preserves_moving_knees():
    from time import monotonic
    from exercise_motion_pkg.controlled_motion import FixedRig
    from exercise_motion_pkg.physical_validation import angles
    from exercise_motion_pkg.support_geometry import calibrate_support_pose, initialize_supported_motion
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile([fixture['joints'][n] for n in names], (8, 1, 1))
    excursion = np.sin(np.linspace(0, np.pi, len(points)))
    feet = {side+'_'+part for side in ('left', 'right') for part in ('ankle', 'foot')}
    for j, name in enumerate(names):
        if name.endswith('knee'):
            points[:, j, 0] += .15*excursion
            points[:, j, 1] -= .04*excursion
        elif name not in feet:
            points[:, j, 1] -= .12*excursion
    rig = FixedRig(points, names)
    original = rig.decode(rig.initial)
    evidence = {'required': True, 'status': 'confirmed', 'stationaryJoints': sorted(feet)}
    pose, calibration = calibrate_support_pose(rig, original, evidence)
    assert pose is not None
    result = initialize_supported_motion(rig, original, evidence, pose, calibration, monotonic()+30)
    for side in ('left', 'right'):
        indices = [names.index(side+'_'+part) for part in ('hip', 'knee', 'ankle')]
        original_angles = angles(*(original[:, j] for j in indices))
        result_angles = angles(*(result[:, j] for j in indices))
        before = np.ptp(original_angles)
        after = np.ptp(result_angles)
        assert before > np.deg2rad(20.)
        assert after >= .95*before
        assert np.max(abs(result_angles-original_angles)) < np.deg2rad(5.)
    for a, b in [('pelvis', 'neck'), ('left_shoulder', 'left_elbow'), ('right_shoulder', 'right_elbow')]:
        source_direction = original[:, names.index(b)]-original[:, names.index(a)]
        fitted_direction = result[:, names.index(b)]-result[:, names.index(a)]
        cosine = np.sum(source_direction*fitted_direction, axis=1)/(
            np.linalg.norm(source_direction, axis=1)*np.linalg.norm(fitted_direction, axis=1))
        assert np.all(cosine > np.cos(np.deg2rad(5.)))
    assert validate_support_geometry({'sourceFootSupportEvidence': {'bodySupport': evidence}}, result, names)['passed']


def test_shoe_roll_uses_confirmed_surface_after_pose_correction():
    from exercise_motion_pkg.temporal_quality import transport_corrected_bone_sides
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation
    payload = {'jointNames': ['left_knee', 'left_ankle', 'left_foot'], 'frames': [{'joints': {
        'left_knee': [0., 1., .1], 'left_ankle': [0., 0., 0.],
        'left_foot': [.2, 0., 0.]},
        'boneSides': {'left_ankle->left_foot': [0., .5, .5]}}],
        'footRestPitchRadians': {'left': 0.},
        'sourceFootSupportEvidence': {'bodySupport': {'required': True, 'status': 'confirmed',
            'stationaryJoints': ['left_ankle', 'left_foot'],
            'soleContacts': [{'joints': ['left_knee', 'left_ankle', 'left_foot'],
                              'normal': [0, 1, 0]}]}}}
    transport_corrected_bone_sides(deepcopy(payload['frames']), payload)
    side = payload['frames'][0]['boneSides']['left_ankle->left_foot']
    np.testing.assert_allclose(np.cross(side, [1, 0, 0]), [0, 1, 0])
    assert validate_supported_shoe_orientation(payload)['passed']
    payload['frames'][0]['boneSides']['left_ankle->left_foot'] = [0., .5, .5]
    assert not validate_supported_shoe_orientation(payload)['passed']


def test_material_shoe_orientation_accepts_source_neutral_pitch():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    pitch = np.deg2rad(-19.)
    vector = .2*np.array([np.cos(pitch), np.sin(pitch), 0.])
    payload = {
        'jointNames': ['left_knee', 'left_ankle', 'left_foot'],
        'footRestPitchRadians': {'left': pitch},
        'frames': [{'joints': {'left_knee': [0., 1., 0.], 'left_ankle': [0., 0., 0.],
                               'left_foot': vector.tolist()},
                    'boneSides': {'left_ankle->left_foot': [0., 0., 1.]}}],
        'sourceFootSupportEvidence': {'bodySupport': {
            'required': True, 'status': 'confirmed',
            'stationaryJoints': ['left_ankle', 'left_foot'],
            'soleContacts': [{'joints': ['left_knee', 'left_ankle', 'left_foot'],
                              'normal': [0., 1., 0.]}],
            'materialFootRestPitchRadians': {'left': 0.},
        }},
    }

    assert validate_supported_shoe_orientation(payload)['passed']


def test_dense_shoe_orientation_checks_interpolated_full_sole_roll():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    names = ['left_knee', 'left_ankle', 'left_foot']
    frames = [{
        'joints': {'left_knee': [0., 1., 0.], 'left_ankle': [0., 0., 0.],
                   'left_foot': [.2, 0., 0.]},
        'boneSides': {'left_ankle->left_foot': [0., 0., 1.]},
    } for _ in range(2)]
    support = {'required': True, 'status': 'confirmed',
        'stationaryJoints': ['left_ankle', 'left_foot'],
        'soleContacts': [{'joints': names, 'normal': [0., 1., 0.]}]}
    payload = {'jointNames': names, 'frames': frames,
        'footRestPitchRadians': {'left': 0.},
        'sourceFootSupportEvidence': {
            'bodySupport': support,
            'contacts': [{'jointName': 'left_foot', 'contactState': 'full_sole',
                'contactMotion': 'stationary', 'verticalOnly': False,
                '_fitFrameBounds': [0, 1], '_fitFrameCount': 2}],
            'footPatchEvidence': {'available': True, 'feet': {
                'left': {'states': ['full_sole', 'full_sole']}}},
            '_fitFrameStateIndices': [0, 1], '_fitFrameCount': 2,
        }}
    stored = validate_supported_shoe_orientation(payload)
    assert stored['passed'], stored

    dense = np.asarray([[frame['joints'][name] for name in names]
                        for frame in frames])
    midpoint = dense[0].copy()
    midpoint[names.index('left_ankle'), 1] = .03
    dense = np.stack([dense[0], midpoint, dense[1]])
    report = validate_supported_shoe_orientation(
        payload, points=dense, cursors=[0., .5, 1.])

    assert not report['passed'], report
    assert report['maximumOrientationErrorMeters'] > .005


def test_full_sole_without_calibrated_material_pitch_remains_unresolved():
    from exercise_motion_pkg.support_geometry import (
        geometry_errors, validate_support_geometry, validate_supported_shoe_orientation,
    )

    names = ['left_knee', 'left_ankle', 'left_foot']
    evidence = {'required': True, 'status': 'confirmed',
                'stationaryJoints': ['left_ankle', 'left_foot'],
                'soleContacts': [{'joints': names, 'normal': [0., 1., 0.]}]}
    points = np.asarray([[[0., 1., 0.], [0., 0., 0.], [.2, 0., 0.]]])
    residual = geometry_errors(points, names, evidence)
    assert np.isfinite(residual).all()
    assert np.max(np.abs(residual)) > .005
    payload = {'jointNames': names,
               'frames': [{'joints': dict(zip(names, points[0].tolist())),
                           'boneSides': {'left_ankle->left_foot': [0., 0., 1.]}}],
               'sourceFootSupportEvidence': {'bodySupport': evidence}}
    support = validate_support_geometry(payload, points, names)
    assert not support['passed']
    assert support['rejectionReasons'] == ['supported_material_sole_pitch_unavailable']
    orientation = validate_supported_shoe_orientation(payload)
    assert not orientation['passed']
    assert orientation['reason'] == 'sole_orientation_unavailable'


def test_timed_toe_only_does_not_require_stale_full_sole_pitch():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    payload = _timed_sole_support_payload(frame_count=5)
    source = payload['sourceFootSupportEvidence']
    source['contacts'][0]['contactState'] = 'toe_only'
    source['footPatchEvidence']['feet']['left']['states'] = ['toe_only'] * 4 + ['unknown']
    # Toe-only contact does not establish ankle stationarity.
    source['bodySupport']['stationaryJoints'].remove('left_ankle')
    payload['footRestPitchRadians'].pop('left')
    for frame in payload['frames']:
        frame['boneSides'] = {
            'left_ankle->left_foot': [0., 0., 1.],
            'right_ankle->right_foot': [0., 0., 1.],
        }

    geometry = validate_support_geometry(payload)
    orientation = validate_supported_shoe_orientation(payload)

    assert geometry['passed'], geometry
    assert orientation['passed'], orientation


def test_timed_full_sole_orientation_ignores_state_less_materialized_ankle_anchor():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    payload = _timed_sole_support_payload(frame_count=5)
    for frame in payload['frames']:
        frame['boneSides'] = {
            'left_ankle->left_foot': [0., 0., 1.],
            'right_ankle->right_foot': [0., 0., 1.],
        }

    orientation = validate_supported_shoe_orientation(payload)

    assert orientation['passed'], orientation


def _timed_sole_support_payload(frame_count=83):
    names = ['left_knee', 'left_ankle', 'left_foot',
             'right_knee', 'right_ankle', 'right_foot']
    frames = []
    for _ in range(frame_count):
        frames.append({'joints': {
            'left_knee': [0., 1., 0.], 'left_ankle': [0., 0., -.2],
            'left_foot': [.2, 0., -.2],
            'right_knee': [0., 1., .4], 'right_ankle': [0., 0., .2],
            'right_foot': [.2, 0., .2],
        }})
    contacts = []
    for side in ('left', 'right'):
        contacts.append({
            'jointName': f'{side}_foot', 'contactState': 'full_sole',
            'contactMotion': 'stationary', 'verticalOnly': False,
            'anchorGroupId': f'{side}:foot:0',
            'ankleAnchorGroupId': f'{side}:ankle:0',
            '_fitFrameBounds': [0, frame_count - 2],
            '_fitFrameCount': frame_count,
        })
    support = {
        'required': True, 'status': 'confirmed',
        'stationaryJoints': ['left_ankle', 'left_foot', 'right_ankle', 'right_foot'],
        'coplanarGroups': [
            {'joints': [f'{side}_foot'], 'normal': [0., 1., 0.], 'planeOffsetMeters': 0.}
            for side in ('left', 'right')
        ],
        'soleContacts': [
            {'joints': [f'{side}_knee', f'{side}_ankle', f'{side}_foot'],
             'normal': [0., 1., 0.]}
            for side in ('left', 'right')
        ],
    }
    return {
        'jointNames': names, 'fps': 25., 'frames': frames,
        'footRestPitchRadians': {'left': 0., 'right': 0.},
        'sourceFootSupportEvidence': {
            'bodySupport': support, 'contacts': contacts,
            'footPatchEvidence': {'available': True, 'feet': {
                side: {'states': ['full_sole'] * (frame_count - 1) + ['unknown']}
                for side in ('left', 'right')
            }},
            '_fitFrameStateIndices': list(range(frame_count)),
            '_fitFrameCount': frame_count,
        },
    }


def test_support_geometry_does_not_plant_unknown_endpoint_frame():
    payload = _timed_sole_support_payload()
    names = payload['jointNames']
    # This is an unobserved endpoint, so reconstructed ankle drift and a
    # changed shoe pitch there cannot be promoted into a support failure.
    payload['frames'][-1]['joints']['left_ankle'][0] = .008
    payload['frames'][-1]['joints']['left_foot'][0] = .195

    report = validate_support_geometry(payload)

    assert report['passed'], report
    assert report['activeContactFrameCountByJoint']['left_ankle'] == 82
    assert report['maximumStationaryJointRangeMeters'] < 1e-9
    assert report['maximumSurfaceErrorMeters'] < 1e-9


def test_support_geometry_keeps_strict_drift_gate_during_active_contact():
    payload = _timed_sole_support_payload()
    names = payload['jointNames']
    for name in ('left_ankle', 'left_foot'):
        payload['frames'][40]['joints'][name][0] += .006

    report = validate_support_geometry(payload)

    assert not report['passed']
    assert 'supported_body_moves' in report['rejectionReasons']
    assert report['maximumStationaryJointRangeMeters'] > .005


def test_support_geometry_checks_stationarity_per_distinct_contact_anchor():
    payload = _timed_sole_support_payload()
    contacts = payload['sourceFootSupportEvidence']['contacts']
    for side in ('left', 'right'):
        name = f'{side}_foot'
        ankle_name = f'{side}_ankle'
        contacts[:] = [contact for contact in contacts if not contact['jointName'].startswith(side)]
        contacts.extend([
            {'jointName': name, 'contactState': 'full_sole', 'contactMotion': 'stationary',
             'verticalOnly': False, 'anchorGroupId': f'{side}:foot:0',
             'ankleAnchorGroupId': f'{side}:ankle:0', '_fitFrameBounds': [0, 40],
             '_fitFrameCount': 83},
            {'jointName': name, 'contactState': 'full_sole', 'contactMotion': 'stationary',
             'verticalOnly': False, 'anchorGroupId': f'{side}:foot:1',
             'ankleAnchorGroupId': f'{side}:ankle:1', '_fitFrameBounds': [41, 81],
             '_fitFrameCount': 83},
        ])
        for frame in payload['frames'][41:82]:
            frame['joints'][name][2] += .1
            frame['joints'][ankle_name][2] += .1
            frame['joints'][f'{side}_knee'][2] += .1

    report = validate_support_geometry(payload)

    assert report['passed'], report
    assert report['maximumStationaryJointRangeMeters'] < 1e-9


def test_toe_only_contact_does_not_impose_full_sole_geometry_or_orientation():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    payload = _timed_sole_support_payload(frame_count=2)
    source = payload['sourceFootSupportEvidence']
    for contact in source['contacts']:
        contact.update(contactState='toe_only', verticalOnly=False)
        contact['_fitFrameBounds'] = [0, 1]
    for side in ('left', 'right'):
        source['footPatchEvidence']['feet'][side]['states'] = ['toe_only', 'toe_only']
    # A planted toe can coexist with heel rise. Material whole-sole geometry
    # must not flatten this pose or judge its ankle-to-toe line as a full sole.
    payload['frames'][0]['joints']['left_ankle'][1] = .04
    names = payload['jointNames']
    evidence = {**source['bodySupport'], **source}
    errors = geometry_errors(
        np.asarray([[frame['joints'][name] for name in names]
                    for frame in payload['frames']]), names, evidence)
    np.testing.assert_allclose(errors[:, :2], 0.)

    report = validate_supported_shoe_orientation(payload)

    assert report == {'required': False, 'passed': True,
                      'reason': 'no_active_full_sole_contact'}


def test_timed_foot_patch_preserves_independent_untimed_torso_support():
    payload = _timed_sole_support_payload()
    support = payload['sourceFootSupportEvidence']['bodySupport']
    support['stationaryJoints'].append('pelvis')
    payload['jointNames'].append('pelvis')
    for frame in payload['frames']:
        frame['joints']['pelvis'] = [0., 1., 0.]
    report = validate_support_geometry(payload)
    assert report['passed'], report

    payload['frames'][40]['joints']['pelvis'][0] += .006
    report = validate_support_geometry(payload)
    assert not report['passed']
    assert 'supported_body_moves' in report['rejectionReasons']


def test_dense_playback_support_masks_follow_stored_contact_clock():
    from exercise_motion_pkg.support_geometry import support_contact_masks

    payload = _timed_sole_support_payload()
    source = payload['sourceFootSupportEvidence']
    evidence = {**source['bodySupport'], **source}
    positions = np.arange(83 * 4 - 3, dtype=float) / 4.
    masks, _ = support_contact_masks(
        evidence, payload['jointNames'], len(positions), frame_positions=positions)
    left_foot = payload['jointNames'].index('left_foot')
    assert masks[np.flatnonzero(positions == 81.)[0], left_foot]
    assert not masks[np.flatnonzero(positions == 81.25)[0], left_foot]
    assert not masks[np.flatnonzero(positions == 82.)[0], left_foot]


def test_support_timing_scope_is_per_joint_for_raw_contact_and_legacy_torso():
    from exercise_motion_pkg.support_geometry import support_contact_masks

    names = ['left_ankle', 'left_foot', 'pelvis']
    evidence = {
        'required': True,
        'status': 'confirmed',
        'stationaryJoints': names,
        'contacts': [{'jointName': 'left_foot', 'contactState': 'full_sole',
                      'contactMotion': 'stationary', 'verticalOnly': False,
                      'startRatio': .25, 'endRatio': .75}],
    }

    masks, _ = support_contact_masks(evidence, names, 5)
    timed_masks, _ = support_contact_masks(
        evidence, names, 5, frame_positions=np.arange(5, dtype=float))
    np.testing.assert_array_equal(timed_masks, masks)

    np.testing.assert_array_equal(masks[:, names.index('left_foot')],
                                  [False, True, True, True, False])
    np.testing.assert_array_equal(masks[:, names.index('left_ankle')],
                                  [False, True, True, True, False])
    np.testing.assert_array_equal(masks[:, names.index('pelvis')], np.ones(5, dtype=bool))


def test_timed_contact_without_sole_state_does_not_expand_legacy_sole_to_whole_clip():
    from exercise_motion_pkg.support_geometry import (
        full_sole_contact_masks, validate_supported_shoe_orientation,
    )

    names = ['left_knee', 'left_ankle', 'left_foot',
             'right_knee', 'right_ankle', 'right_foot']
    evidence = {
        'soleContacts': [
            {'joints': ['left_knee', 'left_ankle', 'left_foot'], 'normal': [0., 1., 0.]},
            {'joints': ['right_knee', 'right_ankle', 'right_foot'], 'normal': [0., 1., 0.]},
        ],
        'contacts': [{'jointName': 'left_foot', 'contactMotion': 'stationary',
                      '_fitFrameBounds': [0, 0], '_fitFrameCount': 2}],
    }

    masks = full_sole_contact_masks(evidence, names, 2)

    assert not masks[:, names.index('left_ankle')].any()
    assert not masks[:, names.index('left_foot')].any()
    assert masks[:, names.index('right_ankle')].all()
    assert masks[:, names.index('right_foot')].all()

    frames = []
    for _ in range(2):
        frames.append({'joints': dict(zip(names, [
            [0., 1., 0.], [0., 0., 0.], [.2, 0., 0.],
            [0., 1., .4], [0., 0., .4], [.2, 0., .4],
        ])), 'boneSides': {
            'left_ankle->left_foot': [0., 0., 1.],
            'right_ankle->right_foot': [0., 0., 1.],
        }})
    payload = {
        'jointNames': names, 'frames': frames,
        'footRestPitchRadians': {'left': 0., 'right': 0.},
        'sourceFootSupportEvidence': {
            'bodySupport': {
                'required': True, 'status': 'confirmed',
                'stationaryJoints': ['left_ankle', 'left_foot',
                                     'right_ankle', 'right_foot'],
                'soleContacts': evidence['soleContacts'],
            },
            'contacts': evidence['contacts'],
        },
    }
    orientation = validate_supported_shoe_orientation(payload)
    assert not orientation['passed']
    assert orientation['reason'] == 'sole_contact_timing_unresolved'
    assert orientation['unresolvedSides'] == ['left']


def test_dense_support_geometry_still_checks_untimed_torso_plane():
    payload = _timed_sole_support_payload()
    support = payload['sourceFootSupportEvidence']['bodySupport']
    support['stationaryJoints'].extend(['pelvis', 'spine'])
    support['coplanarGroups'].append({
        'joints': ['pelvis', 'spine'], 'normal': [0., 1., 0.],
    })
    names = payload['jointNames'] + ['pelvis', 'spine']
    payload['jointNames'] = names
    for frame in payload['frames']:
        frame['joints'].update(pelvis=[0., 1., 0.], spine=[.1, 1., 0.])
    stored = np.asarray([[frame['joints'][name] for name in names]
                         for frame in payload['frames']])
    positions = np.arange((len(stored) - 1) * 4 + 1, dtype=float) / 4.
    dense = stored[np.clip(np.rint(positions).astype(int), 0, len(stored) - 1)]
    dense[np.flatnonzero(positions == 40.5)[0], names.index('spine'), 1] += .01

    report = validate_support_geometry(
        payload, dense, names, frame_positions=positions)

    assert not report['passed']
    assert 'support_surface_geometry_mismatch' in report['rejectionReasons']


def test_support_projection_repairs_reference_before_final_fit():
    from time import monotonic
    from exercise_motion_pkg.controlled_motion import FixedRig
    from exercise_motion_pkg.support_geometry import calibrate_support_pose, initialize_supported_motion
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile([fixture['joints'][n] for n in names], (8, 1, 1))
    rig = FixedRig(points, names)
    foot = names.index('left_foot')
    rig.initial[:, rig.slots[foot]] += np.linspace(-.1, .1, 8)
    original = rig.decode(rig.initial)
    contact_names = ['left_ankle', 'left_foot', 'right_ankle', 'right_foot']
    evidence = {'required': True, 'status': 'confirmed', 'stationaryJoints': contact_names,
        'coplanarGroups': [{'joints': contact_names, 'normal': [0, 1, 0],
                           'planeOffsetMeters': float(original[:, names.index('left_ankle'), 1].mean())}]}
    pose, calibration = calibrate_support_pose(rig, original, evidence)
    assert pose is not None
    result = initialize_supported_motion(rig, original, evidence, pose, calibration, monotonic()+30)
    assert validate_support_geometry({'sourceFootSupportEvidence': {'bodySupport': evidence}}, result, names)['passed']
    from exercise_motion_pkg.anatomical_repair import repair_residuals
    assert np.max(repair_residuals(result, names)[0]) <= 1e-6


def test_plant_only_body_support_detects_feet_not_torso():
    from exercise_motion_pkg.support_geometry import plant_only_body_support
    feet = {'required': True, 'status': 'confirmed',
            'stationaryJoints': ['left_ankle', 'left_foot', 'right_ankle', 'right_foot']}
    assert plant_only_body_support(feet)
    torso = {**feet, 'stationaryJoints': ['pelvis', 'spine1', 'left_ankle']}
    assert not plant_only_body_support(torso)
    assert not plant_only_body_support({'required': True, 'status': 'unknown',
                                        'stationaryJoints': feet['stationaryJoints']})


def test_contact_plant_projection_clears_millimeter_scale_support_error():
    """Regression: support init often stopped ~2 mm off; plant polish must hit 0.5 mm."""
    from exercise_motion_pkg.controlled_motion import FixedRig, project_contact_plant_coordinates
    from exercise_motion_pkg.rig_playback import rig_contact_targets
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile([fixture['joints'][n] for n in names], (8, 1, 1))
    rig = FixedRig(points, names)
    points = rig.decode(rig.initial)
    feet = [names.index('left_foot'), names.index('right_foot')]
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, feet] = True
    targets, _ = rig_contact_targets(points, names, pinned, rig.offsets)
    # Leave a multi-millimeter plant error like incomplete support projection.
    shifted = rig.initial.copy()
    shifted[:, :3] += [0.003, 0.0, 0.002]
    before = float(np.max(np.linalg.norm((rig.decode(shifted) - targets)[pinned], axis=-1)))
    assert before > 0.0005
    planted = project_contact_plant_coordinates(shifted, rig, pinned, targets, max_nfev=40)
    after = float(np.max(np.linalg.norm((rig.decode(planted) - targets)[pinned], axis=-1)))
    assert after < 0.0005, (before, after)


def test_contact_plant_projection_holds_interpolated_playback_plants():
    """Keyframe plants can still skate between samples under rotation interpolation."""
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, project_contact_plant_coordinates,
        project_interval_playback_plants, _playback_contact_sample_error,
        _playback_failing_intervals)
    from exercise_motion_pkg.rig_playback import PLAYBACK_CONTACT_LIMIT_METERS, rig_contact_targets
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile([fixture['joints'][n] for n in names], (8, 1, 1))
    # Longer clip so a per-interval TRF would be expensive if not gated.
    points = np.concatenate([points, points, points, points], axis=0)
    rig = FixedRig(points, names)
    points = rig.decode(rig.initial)
    feet = [names.index('left_foot'), names.index('right_foot')]
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, feet] = True
    targets, _ = rig_contact_targets(points, names, pinned, rig.offsets)
    shifted = rig.initial.copy()
    ankle = rig.slots[names.index('left_ankle')]
    # Alternate the source ankle orientation so keyframe-only planting leaves
    # an actual interpolation gap for the interval projector to repair.
    for frame_index in range(1, len(shifted) - 1):
        shifted[frame_index, ankle:ankle + 3] += [(-1) ** frame_index * .3, 0.0, .05]
    keyed = project_contact_plant_coordinates(shifted, rig, pinned, targets, max_nfev=40)
    before = _playback_contact_sample_error(keyed, rig, pinned, targets, cyclic=False)
    assert before > PLAYBACK_CONTACT_LIMIT_METERS
    assert _playback_failing_intervals(keyed, rig, pinned, targets, cyclic=False)
    started = __import__('time').monotonic()
    planted = project_interval_playback_plants(
        keyed, rig, pinned, targets, cyclic=False)
    elapsed = __import__('time').monotonic() - started
    after_key = float(np.max(np.linalg.norm((rig.decode(planted) - targets)[pinned], axis=-1)))
    after_play = _playback_contact_sample_error(planted, rig, pinned, targets, cyclic=False)
    assert after_key < PLAYBACK_CONTACT_LIMIT_METERS, (after_key, after_play)
    assert after_play < PLAYBACK_CONTACT_LIMIT_METERS, (before, after_play)
    assert not _playback_failing_intervals(planted, rig, pinned, targets, cyclic=False)
    # Coupled mid-sample TRF is heavier than a root-only scan, but must stay
    # well under a dense clip-wide plant solve on this fixture.
    assert elapsed < 25.0, elapsed


def test_contiguous_failing_interval_runs_group_neighbors():
    from exercise_motion_pkg.controlled_motion import (
        _contiguous_interval_runs, _hermite_stencil_frames)
    assert _contiguous_interval_runs([]) == []
    assert _contiguous_interval_runs([3]) == [(3, 3)]
    assert _contiguous_interval_runs([1, 2, 3, 7, 8, 10]) == [(1, 3), (7, 8), (10, 10)]
    # Mid-samples on [0,1] depend on tangent neighbors including frame 2.
    assert _hermite_stencil_frames([0], 8, cyclic=False) == [0, 1, 2]
    assert _hermite_stencil_frames([0], 8, cyclic=True) == [0, 1, 2, 7]
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, apply_supported_floor_clearance, _playback_contact_sample_error)
    from exercise_motion_pkg.rig_playback import PLAYBACK_CONTACT_LIMIT_METERS, rig_contact_targets
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile([fixture['joints'][n] for n in names], (8, 1, 1))
    rig = FixedRig(points, names)
    points = rig.decode(rig.initial)
    feet = [names.index('left_foot'), names.index('right_foot')]
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, feet] = True
    targets, _ = rig_contact_targets(points, names, pinned, rig.offsets)
    floor = float(points[:, feet, 1].min())
    dipped = rig.initial.copy()
    dipped[:, 1] -= 0.003
    restored, lift = apply_supported_floor_clearance(
        dipped, rig, pinned, targets, floor, cyclic=False)
    assert lift > 0
    key = float(np.max(np.linalg.norm((rig.decode(restored) - targets)[pinned], axis=-1)))
    play = _playback_contact_sample_error(restored, rig, pinned, targets, cyclic=False)
    assert key < PLAYBACK_CONTACT_LIMIT_METERS
    assert play < PLAYBACK_CONTACT_LIMIT_METERS


def test_floor_correction_clears_rendered_shoe_when_joint_centres_are_clear():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, _sampling_payload, apply_supported_floor_clearance,
    )
    from exercise_motion_pkg.rig_playback import free_material_floor_clearance_lift

    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile([fixture['joints'][name] for name in names], (8, 1, 1))
    points[:, :, 1] += 1.2
    ankle, toe = names.index('left_ankle'), names.index('left_foot')
    points[:, ankle] = [points[0, ankle, 0], .12, points[0, ankle, 2]]
    points[:, toe] = [points[0, ankle, 0] + .021, .001, points[0, ankle, 2]]
    rig = FixedRig(points, names)
    points = rig.decode(rig.initial)
    floor = 0.
    pinned = np.zeros(points.shape[:2], dtype=bool)
    reference = {
        'jointNames': names, 'fps': 30., 'renderFloorY': floor,
        'footRestPitchRadians': {},
        'frames': [{'timeSec': index / 30., 'joints': dict(zip(names, row.tolist()))}
                   for index, row in enumerate(points)],
        'fixedRig': _sampling_payload(rig, rig.initial),
    }
    assert points[:, :, 1].min() > floor
    before = free_material_floor_clearance_lift(reference, pinned, cyclic=False)
    assert before > .001

    corrected, lift = apply_supported_floor_clearance(
        rig.initial, rig, pinned, points, floor, material_reference=reference)

    assert lift >= before - 1e-9
    expected = rig.initial.copy()
    expected[:, 1] += lift
    np.testing.assert_allclose(corrected, expected, atol=1e-12)
    reference['fixedRig'] = _sampling_payload(rig, corrected)
    assert free_material_floor_clearance_lift(reference, pinned, cyclic=False) < 1e-9

def test_observed_knee_material_floor_uses_region_and_retains_clearance():
    from exercise_motion_pkg.render_geometry import knee_support_region
    from exercise_motion_pkg.support_geometry import geometry_errors
    names = ['pelvis','neck','left_hip','right_hip','left_knee','left_ankle']
    points = np.array([[[0.,.6,0.],[0.,1.,0.],[-.1,.6,0.],[.1,.6,0.],
                        [-.1,.1,0.],[-.1,.1,.4]]])
    lengths = [.5,.4]
    sides = np.array([[1.,0.,0.]])
    region = knee_support_region(points,names,'left_knee',lengths=lengths,side_axes=sides)
    floor = float(region[:,:,1].min())
    evidence = {'stationaryJoints':['left_knee'], 'status':'confirmed','required':True,
                '_floorMaterialContacts':['left_knee'],'_renderFloorY':floor,
                '_materialLegSides':[{'left_knee->left_ankle':[1.,0.,0.]}],
                '_materialSegmentLengths':{'left':lengths}}
    assert np.max(abs(geometry_errors(points,names,evidence))) < 1e-12
    raised = points.copy(); raised[:,:,1] += .02
    assert np.max(geometry_errors(raised,names,evidence)) > .019
    lowered = points.copy(); lowered[:,:,1] -= .02
    assert np.min(geometry_errors(lowered,names,evidence)) < -.019
    # Source contact membership stays separate from material target/clearance.
    assert evidence['stationaryJoints'] == ['left_knee']
    # Native knee cap coefficient: .40 * max(.215*thigh,.225*shin).
    radius = max(.215*.5,.225*.4)*.40
    assert np.isclose(region[0,:18,1].min(), .1-radius)

def test_knee_material_region_matches_production_native_mesh_samples():
    from exercise_motion_pkg.render_geometry import knee_support_region
    fixture = json.loads((Path(__file__).parent/'fixtures/native_knee_material_regions.json').read_text())
    for sample in fixture['samples']:
        names = list(sample['joints'])
        points = np.array([[sample['joints'][name] for name in names]])
        for side in ('left','right'):
            region = knee_support_region(points,names,side+'_knee',
                lengths=sample['lengths'][side],
                side_axes=np.array([sample['sides'][side+'_knee->'+side+'_ankle']]),
                body_axes=np.array([sample['bodyAxes']]))
            np.testing.assert_allclose(region[:,:,1].min(),
                sample['nativeRegionMinimumY'][side],atol=1e-6,rtol=0.)


def test_coupled_support_anatomy_polish_keeps_ankle_gate_and_material_contacts():
    from time import monotonic
    from exercise_motion_pkg.controlled_motion import FixedRig, project_contact_plant_coordinates
    from exercise_motion_pkg.anatomical_repair import repair_residuals, repair_residual_dependencies
    from exercise_motion_pkg.support_geometry import (
        _floor_material_region, repair_supported_motion_anatomy)
    fixture = json.loads((Path(__file__).parent / 'fixtures/material_floor_anchor_conflict.json').read_text())
    points = np.array(fixture['points']); names = fixture['names']; evidence = fixture['evidence']
    evidence['_materialBodyAxes'] = np.array(evidence['_materialBodyAxes'])
    reference = np.array(fixture['anatomicalReference'])
    rig = FixedRig(points, names); rig.offsets[:] = fixture['offsets']; rig.initial[:] = fixture['coordinates']
    np.testing.assert_allclose(rig.decode(rig.initial), points, atol=1e-12)
    assert np.any(repair_residuals(points, names, reference=reference)[0] > 1e-6)
    dependencies = repair_residual_dependencies(rig, points, reference=reference)
    assert dependencies.shape[0] == repair_residuals(points, names, reference=reference)[0].shape[1]
    # Retained feasible targets for this anatomy-polish counterexample; target
    # calibration is tested independently rather than retargeted after solving.
    positions = {'left_knee': [0.15824319, -0.52126731, -0.07764391],
                 'right_knee': [0.16331782, -0.52192868, 0.10247262]}
    pinned = np.zeros(points.shape[:2], dtype=bool); targets = points.copy()
    for joint, target in positions.items():
        pinned[:, names.index(joint)] = True; targets[:, names.index(joint)] = target
    original_offsets = rig.offsets.copy()
    corrected, report = repair_supported_motion_anatomy(
        rig, points, evidence, np.array(fixture['supportPose']), {}, monotonic()+15,
        pinned=pinned, contact_targets=targets, articulation_reference=reference)
    projected = project_contact_plant_coordinates(
        rig.initial, rig, pinned, targets, max_nfev=40, deadline=monotonic()+10)
    corrected = rig.decode(projected)
    assert report['passed'], report
    assert not np.any(repair_residuals(corrected, names, reference=reference)[0] > 1e-6)
    assert np.linalg.norm((corrected-targets)[pinned], axis=-1).max() <= .001
    for joint in positions:
        region = _floor_material_region(corrected, names, evidence, joint, None)
        assert np.abs(region[:, :, 1].min(axis=1)-evidence['_renderFloorY']).max() <= .005
    np.testing.assert_array_equal(rig.offsets, original_offsets)


def test_coupled_anatomy_frame_timeout_is_atomic_and_success_commits(monkeypatch):
    from time import monotonic
    from exercise_motion_pkg import support_geometry
    from exercise_motion_pkg.controlled_motion import FixedRig

    fixture = json.loads((Path(__file__).parent / 'fixtures/material_floor_anchor_conflict.json').read_text())
    points = np.array(fixture['points']); names = fixture['names']
    reference = np.array(fixture['anatomicalReference'])
    for interrupted in (True, False):
        rig = FixedRig(points, names)
        rig.offsets[:] = fixture['offsets']; rig.initial[:] = fixture['coordinates']
        before = rig.initial.copy()

        def project(local, *args, **kwargs):
            local.initial[:, 0] += .1
            if interrupted:
                raise TimeoutError
            return local.decode(local.initial)

        monkeypatch.setattr(support_geometry, 'initialize_supported_motion', project)
        result, report = support_geometry.repair_supported_motion_anatomy(
            rig, points, fixture['evidence'], np.array(fixture['supportPose']), {},
            monotonic()+5, pinned=np.zeros(points.shape[:2], dtype=bool),
            contact_targets=points, articulation_reference=reference)
        assert report['attemptedFrameCount'] > 0
        assert report['timedOutFrameCount'] == (report['attemptedFrameCount'] if interrupted else 0)
        assert report['projectedFrameCount'] == (0 if interrupted else report['attemptedFrameCount'])
        if interrupted:
            np.testing.assert_array_equal(rig.initial, before)
            np.testing.assert_allclose(result, points, atol=1e-12)
        else:
            assert np.max(result[:, :, 0]-points[:, :, 0]) > .09


def test_explicit_policy_owns_shared_floor_height_and_not_source_angular_bounds():
    from exercise_motion_pkg.support_alignment import policy_alignment_errors, policy_alignment_dependencies
    from exercise_motion_pkg.controlled_motion import FixedRig, canonical_bilateral_reference
    from exercise_motion_pkg.physical_validation import source_articulation_reference_field
    from exercise_motion_pkg.bake_and_rank import baked_leg_articulation_preservation_metrics
    fixture = json.loads((Path(__file__).parent / 'fixtures/material_floor_anchor_conflict.json').read_text())
    points = np.array(fixture['points']); names = fixture['names']; evidence = fixture['evidence']
    evidence['_materialBodyAxes'] = np.array(evidence['_materialBodyAxes'])
    policy = {'arms': 'mirrored', 'legs': 'mirrored', 'torso': 'sagittal'}
    assert policy_alignment_errors(points, names, None).shape == (len(points), 0)
    assert policy_alignment_errors(points, names, {'legs': 'unconstrained'}).shape[1] == 0
    projected = canonical_bilateral_reference(points, names, policy)
    assert np.linalg.norm(policy_alignment_errors(points, names, policy)) > .01
    np.testing.assert_allclose(policy_alignment_errors(projected, names, policy), 0., atol=1e-12)
    rig = FixedRig(points, names)
    assert policy_alignment_dependencies(rig, policy).shape == (len(names)*3, rig.width)
    frames = [{'joints': dict(zip(names, row.tolist())),
               'sourceJoints': dict(zip(names, row.tolist())),
               'controlledArticulationReferenceJoints': dict(zip(names, source)),
               'supportCorrectedReferenceJoints': dict(zip(names, row.tolist()))}
              for row, source in zip(points, fixture['anatomicalReference'])]
    assert source_articulation_reference_field(frames) == 'controlledArticulationReferenceJoints'
    metric = baked_leg_articulation_preservation_metrics({'frames': frames, 'jointNames': names, 'fps': 30.})
    assert metric['referenceField'] == 'controlledArticulationReferenceJoints'
    del frames[1]['controlledArticulationReferenceJoints']
    assert source_articulation_reference_field(frames) == 'controlledArticulationReferenceJoints'
    invalid = baked_leg_articulation_preservation_metrics({'frames': frames, 'jointNames': names, 'fps': 30.})
    assert invalid['invalidSupportReference'] and not invalid['available']


def test_floor_material_fit_respects_contact_band_preserving_raw_and_other_rows():
    from exercise_motion_pkg.render_geometry import knee_support_region
    from exercise_motion_pkg.support_geometry import geometry_constraint_errors, TOLERANCE_METERS
    names = ['pelvis','neck','left_hip','right_hip','left_knee','left_ankle','right_knee']
    pose = np.array([[[0.,.6,0.],[0.,1.,0.],[-.1,.6,0.],[.1,.6,0.],
                      [-.1,.1,0.],[-.1,.1,.4],[.1,.101,0.]]])
    lengths = [.5,.4]
    region = knee_support_region(pose,names,'left_knee',lengths=lengths,side_axes=np.array([[1.,0.,0.]]))
    evidence = {'stationaryJoints':['left_knee','right_knee'],'status':'confirmed','required':True,
                'coplanarGroups':[{'joints':['left_knee','right_knee'],'normal':[0.,1.,0.]}],
                '_floorMaterialContacts':['left_knee'],'_renderFloorY':float(region[:,:,1].min()),
                '_materialLegSides':[{'left_knee->left_ankle':[1.,0.,0.]}],
                '_materialSegmentLengths':{'left':lengths}}
    gaps = np.array([0.,.003657,.006,-.002])
    points = np.repeat(pose,len(gaps),axis=0)
    points[:,:,1] += gaps[:,None]
    raw = geometry_errors(points,names,evidence)
    fitted = geometry_constraint_errors(points,names,evidence)
    np.testing.assert_allclose(raw[:,-1],gaps,atol=1e-12)
    np.testing.assert_allclose(fitted[:,-1],[0.,0.,.001,-.002],atol=1e-12)
    np.testing.assert_array_equal(fitted[:,:-1],raw[:,:-1])
    np.testing.assert_array_equal(geometry_errors(points,names,evidence),raw)
    assert abs(raw[2,-1]) > TOLERANCE_METERS  # Validator still rejects the outside gap.
    assert raw[1,-1] > .0025  # Static calibration still sees its stricter raw error.


def test_supported_range_baseline_transports_free_motion_from_corrected_anchor():
    from exercise_motion_pkg.controlled_motion import support_joint_range_preserved
    from exercise_motion_pkg.physical_validation import angles
    from exercise_motion_pkg.support_geometry import moving_support_articulations

    names = ['left_hip', 'left_shoulder', 'left_elbow', 'pelvis', 'right_shoulder']
    theta = np.deg2rad(np.linspace(30., 70., 12))
    drift = np.deg2rad(np.linspace(10., -10., 12))
    raw = np.zeros((12, len(names), 3))
    raw[:, 1, 0] = np.linspace(0., .03, 12)
    raw[:, 0] = raw[:, 1] + np.c_[np.sin(drift), -np.cos(drift), np.zeros(12)]
    raw[:, 2] = raw[:, 1] + np.c_[np.sin(theta), -np.cos(theta), np.zeros(12)]
    corrected = np.zeros_like(raw)
    corrected[:, 0] = [0., -1., 0.]
    corrected[:, 2] = raw[:, 2] - raw[:, 1]
    evidence = {'stationaryJoints': ['pelvis', 'left_shoulder', 'right_shoulder']}
    tracks = moving_support_articulations(
        raw, names, evidence, support_corrected_points=corrected,
        constraint_endpoints=['left_shoulder'])
    label, columns, baseline = tracks[0]
    actual = angles(*(corrected[:, j] for j in columns))
    assert label == 'left_shoulder'
    assert support_joint_range_preserved({label: np.ptp(actual) / np.ptp(baseline)})
    raw_track = moving_support_articulations(raw, names, evidence)[0][2]
    assert not support_joint_range_preserved({label: np.ptp(actual) / np.ptp(raw_track)})

    # Real distal ROM loss still fails; corrected body geometry is unchanged.
    reduced = corrected.copy()
    reduced_theta = np.deg2rad(np.linspace(40., 60., 12))
    reduced[:, 2] = np.c_[np.sin(reduced_theta), -np.cos(reduced_theta), np.zeros(12)]
    reduced_track = angles(*(reduced[:, j] for j in columns))
    assert not support_joint_range_preserved(
        {label: np.ptp(reduced_track) / np.ptp(baseline)})

    # A held knee does not make its moving proximal hip a body-frame axis,
    # even when a separate torso support frame is also present.
    leg_names = ['left_hip', 'left_knee', 'left_ankle',
                 'pelvis', 'left_shoulder', 'right_shoulder']
    hip_angle = np.deg2rad(np.linspace(30., 90., 12))
    leg_raw = np.zeros((12, len(leg_names), 3))
    leg_raw[:, 0] = np.c_[np.sin(hip_angle), np.cos(hip_angle), np.zeros(12)]
    leg_raw[:, 2] = [0., -1., 0.]
    leg_corrected = leg_raw.copy()
    shrunken = np.deg2rad(np.linspace(30., 40., 12))
    leg_corrected[:, 0] = np.c_[np.sin(shrunken), np.cos(shrunken), np.zeros(12)]
    leg_evidence = {'stationaryJoints': [
        'left_knee', 'pelvis', 'left_shoulder', 'right_shoulder']}
    raw_knee = moving_support_articulations(leg_raw, leg_names, leg_evidence)[0]
    knee = moving_support_articulations(
        leg_raw, leg_names, leg_evidence, support_corrected_points=leg_corrected,
        constraint_endpoints=leg_evidence['stationaryJoints'])[0]
    assert knee[0] == raw_knee[0] == 'left_knee'
    np.testing.assert_array_equal(knee[2], raw_knee[2])
    shortened = angles(*(leg_corrected[:, j] for j in knee[1]))
    assert not support_joint_range_preserved(
        {knee[0]: np.ptp(shortened) / np.ptp(knee[2])})
def test_coupled_support_schedules_source_hinge_errors_with_valid_anatomy(monkeypatch):
    import json
    from pathlib import Path
    from time import monotonic
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg import controlled_motion as motion, support_geometry
    from exercise_motion_pkg.anatomical_repair import repair_residuals

    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    pose = np.asarray([fixture['joints'][name] for name in names])
    for side in ('left', 'right'):
        knee = names.index(side + '_knee')
        distal = [names.index(side + '_' + part) for part in ('ankle', 'foot')]
        pose[distal] = Rotation.from_rotvec([.9, 0., 0.]).apply(pose[distal] - pose[knee]) + pose[knee]
    rig = motion.FixedRig(np.asarray([pose] * 7), names)
    reference = rig.decode(rig.initial)
    observed = reference.copy()
    knee, hip = [names.index('left_' + part) for part in ('knee', 'hip')]
    axis = reference[0, knee] - reference[0, hip]
    axis /= np.linalg.norm(axis)
    for part in ('ankle', 'foot'):
        joint = names.index('left_' + part)
        observed[:, joint] = Rotation.from_rotvec(axis * .24).apply(
            observed[:, joint] - observed[:, knee]) + observed[:, knee]
    assert repair_residuals(observed, names, reference=reference)[0].max() == 0.
    parent, bend, sine = motion.hinge_coordinates(reference, names)
    reliable = motion.source_hinge_reliability(parent, bend, sine, 30.)
    rows = motion.reliable_knee_hinge_residuals(observed, names, parent, bend, reliable)
    assert rows[:, 0].min() > 30. and not rows[:, 1].any()
    assert motion.reliable_knee_hinge_dependencies(rig).shape == (2, rig.width)
    rig.initial[:] = motion.FixedRig(observed, names).initial
    attempts = []

    def record_projection(local, original, *args, angular_reference=None, frame_positions=None, **kwargs):
        np.testing.assert_array_equal(angular_reference, reference)
        attempts.extend(frame_positions.tolist())
        return original

    monkeypatch.setattr(support_geometry, 'initialize_supported_motion', record_projection)
    _, report = support_geometry.repair_supported_motion_anatomy(
        rig, observed, {'stationaryJoints': ['left_knee', 'right_knee']}, pose, {}, monotonic() + 10.,
        pinned=np.zeros(observed.shape[:2], dtype=bool), contact_targets=observed,
        articulation_reference=reference, angular_reference=reference)
    assert attempts == list(range(7))
    assert not report['passed'] and len(report['remainingHingeEvents']) == 7
