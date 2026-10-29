import copy

import numpy as np

from exercise_motion_pkg.equipment_constraints import calibrated_grip_constraint, validate_grip
from exercise_motion_pkg.bake_and_rank import exercise_motion_contract_requires_rigid_paired_hands
from exercise_motion_pkg.controlled_motion import fit_controlled_motion, can_reuse_controlled_motion
from exercise_motion_pkg.rig_playback import validate_rig_playback
from test_controlled_motion_pipeline import accepted_payload


def test_independent_and_single_implements_override_hand_support():
    for contract in [
        {'implementSupportMode': 'hands_only', 'requiredEquipment': ['dumbbells']},
        {'implementSupportMode': 'hands_only', 'handRelationship': 'single', 'requiredEquipment': ['barbell']},
        {'implementSupportMode': 'hands_only', 'handRelationship': 'independent'},
    ]:
        assert not exercise_motion_contract_requires_rigid_paired_hands(contract)
    assert exercise_motion_contract_requires_rigid_paired_hands({'handRelationship': 'rigid_pair'})
    assert exercise_motion_contract_requires_rigid_paired_hands({
        'implementSupportMode': 'hands_only', 'requiredEquipment': ['barbell']
    })


def test_grip_spacing_constraint_does_not_require_pose_symmetry_or_fixed_world_hands():
    names = ['left_wrist', 'right_wrist']
    points = np.array([[[0., 0., 0.], [1., 0., 0.]], [[0., 2., 0.], [0., 3., 0.]]])
    constraint = calibrated_grip_constraint({'equipmentConstraints': {'handRelationship': 'rigid_pair'}}, points, names)
    assert validate_grip(points, names, constraint)['passed']
    points[-1, 1, 1] += .2
    assert not validate_grip(points, names, constraint)['passed']
    assert validate_grip(points, names, {'handRelationship': 'independent'})['passed']


def test_rigid_pair_preserves_an_observed_front_behind_bar_axis():
    names = ['left_hand', 'right_hand']
    points = np.array([
        [[-.1, .7, .32], [.1, .7, -.32]],
        [[-.12, .8, .31], [.12, .8, -.31]],
    ])
    equipment = calibrated_grip_constraint(
        {'equipmentConstraints': {'handRelationship': 'rigid_pair'}}, points, names
    )
    result = validate_grip(points, names, equipment)
    assert result['passed']
    assert equipment['distanceSource'] == 'robust_reconstruction_estimate'
    assert np.all(points[:, 0, 2] > points[:, 1, 2])


def test_equipment_checked_in_fit_playback_and_reuse():
    payload = accepted_payload()
    payload.pop('fixedRig')
    payload.pop('controlledMotionFit')
    payload['equipmentConstraints'] = {'handRelationship': 'rigid_pair'}
    fitted, report = fit_controlled_motion(payload, timeout_seconds=10.)
    fitted['controlledMotionFit'] = report
    assert report['applied'], report
    assert report['checks']['equipment']
    assert validate_rig_playback(fitted)['equipment']['passed']
    assert can_reuse_controlled_motion(fitted)
    corrupted = copy.deepcopy(fitted)
    corrupted['equipmentConstraints']['distanceMeters'] += .2
    assert not can_reuse_controlled_motion(corrupted)
    assert not validate_rig_playback(corrupted)['passed']
