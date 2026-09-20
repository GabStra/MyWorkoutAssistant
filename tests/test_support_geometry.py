from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.support_geometry import (
    declare_support_requirements, geometry_errors, validate_support_geometry,
)


def test_supported_chain_range_uses_feasible_reference_but_free_arm_keeps_source():
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
    assert np.isclose(np.rad2deg(np.ptp(tracks['right_shoulder'])), 45.)
    # Explicit support-like endpoints may still opt into the corrected chain.
    paired = {label: track for label, _, track in moving_support_articulations(
        original, names, {}, support_corrected_points=corrected,
        constraint_endpoints=['left_wrist', 'right_wrist'])}
    assert np.isclose(np.rad2deg(np.ptp(paired['left_shoulder'])), 45.)
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
    assert not validate_support_geometry(current)['passed']


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
    evidence = {'soleContacts': [{'joints': names, 'normal': [0, 1, 0]}]}
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
    payload = {'jointNames': ['knee', 'ankle', 'foot'], 'frames': [{'joints': {
        'knee': [0., 1., .1], 'ankle': [0., 0., 0.], 'foot': [.2, 0., 0.]},
        'boneSides': {'ankle->foot': [0., .5, .5]}}],
        'sourceFootSupportEvidence': {'bodySupport': {'required': True, 'status': 'confirmed',
            'stationaryJoints': ['ankle', 'foot'],
            'soleContacts': [{'joints': ['knee', 'ankle', 'foot'], 'normal': [0, 1, 0]}]}}}
    transport_corrected_bone_sides(deepcopy(payload['frames']), payload)
    side = payload['frames'][0]['boneSides']['ankle->foot']
    np.testing.assert_allclose(np.cross(side, [1, 0, 0]), [0, 1, 0])
    assert validate_supported_shoe_orientation(payload)['passed']
    payload['frames'][0]['boneSides']['ankle->foot'] = [0., .5, .5]
    assert not validate_supported_shoe_orientation(payload)['passed']


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
    shifted[1:-1, ankle:ankle + 3] += [0.2, 0.0, 0.05]
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
