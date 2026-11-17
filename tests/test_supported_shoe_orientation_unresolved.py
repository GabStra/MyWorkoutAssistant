"""Fail-closed shoe-orientation checks for unresolvable required sole geometry."""

import numpy as np


def _payload(names, contact_joints, *, pitch_key):
    joints = {
        'knee': [0., 1., 0.], 'ankle': [0., 0., 0.], 'foot': [.2, 0., 0.],
        'left_knee': [0., 1., 0.], 'left_ankle': [0., 0., 0.],
        'left_foot': [.2, 0., 0.], 'toe': [.2, 0., 0.],
        'right_foot': [.2, 0., 0.],
        'left_shoulder': [0., 1.5, 0.],
    }
    return {
        'jointNames': names,
        'frames': [{'joints': {name: joints[name] for name in names},
                    'boneSides': {}}],
        'footRestPitchRadians': {pitch_key: 0.},
        'sourceFootSupportEvidence': {'bodySupport': {
            'required': True, 'status': 'confirmed',
            'stationaryJoints': [name for name in names if 'ankle' in name or 'foot' in name],
            'soleContacts': [{'joints': contact_joints, 'normal': [0., 1., 0.]}],
        }},
    }


def test_side_less_required_sole_contact_fails_closed():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    names = ['knee', 'ankle', 'foot']
    report = validate_supported_shoe_orientation(
        _payload(names, names, pitch_key='ankle'))

    assert report['required'] is True
    assert report['passed'] is False, report
    assert report['reason'] == 'sole_orientation_unavailable'


def test_unsupported_foot_joint_does_not_skip_orientation_check():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    names = ['left_knee', 'left_ankle', 'toe']
    report = validate_supported_shoe_orientation(
        _payload(names, names, pitch_key='left'))

    assert report['required'] is True
    assert report['passed'] is False, report
    assert report['reason'] == 'sole_orientation_unavailable'


def test_mixed_side_sole_pair_does_not_skip_orientation_check():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    names = ['left_knee', 'left_ankle', 'right_foot']
    report = validate_supported_shoe_orientation(
        _payload(names, names, pitch_key='left'))

    assert report['required'] is True
    assert report['passed'] is False, report
    assert report['reason'] == 'sole_orientation_unavailable'


def test_proper_sideful_material_chain_still_passes():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    names = ['left_knee', 'left_ankle', 'left_foot']
    report = validate_supported_shoe_orientation(
        _payload(names, names, pitch_key='left'))

    assert report['passed'], report
    assert report['required'] is True


def test_sole_contact_cannot_substitute_another_joint_for_the_knee():
    from exercise_motion_pkg.support_geometry import validate_supported_shoe_orientation

    names = ['left_shoulder', 'left_ankle', 'left_foot']
    report = validate_supported_shoe_orientation(_payload(names, names, pitch_key='left'))
    assert report['required'] and report['passed'] is False
    assert report['reason'] == 'sole_orientation_unavailable'
