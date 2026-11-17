import numpy as np
import pytest

from exercise_motion_pkg.support_joint_tracks import (
    build_support_joint_tracks,
    sample_support_joint_mask,
    validate_support_joint_tracks,
)


def test_support_joint_tracks_preserve_episode_identity_and_releases():
    evidence = {
        'status': 'confirmed',
        'stationaryJoints': ['right_knee'],
    }
    built = build_support_joint_tracks(evidence, ['pelvis', 'right_knee'], 4)
    assert built['source'] == 'validated_stationary_body_support'
    ids = built['joints']['right_knee']['episodeIds']
    assert ids == ['derived:stationary:right_knee:1'] * 4
    normalized = validate_support_joint_tracks(built, ['pelvis', 'right_knee'], 4)
    assert sample_support_joint_mask(normalized, 'right_knee', [0., 1., 1.5], 4).tolist() == [
        True, True, True]

    released = {
        'version': 1,
        'source': 'validated_stationary_body_support',
        'joints': {'right_knee': {'episodeIds': ['episode-a', 'episode-a', None, 'episode-b']}},
    }
    released = validate_support_joint_tracks(released, ['right_knee'], 4)
    assert sample_support_joint_mask(
        released, 'right_knee', [0., .5, 1., 1.5, 2., 2.5, 3.], 4).tolist() == [
            True, True, True, False, False, False, True]


def test_support_joint_tracks_fail_closed_when_present_but_malformed():
    malformed = {
        'version': 1,
        'source': 'validated_stationary_body_support',
        'joints': {'right_knee': {'episodeIds': ['episode-a']}},
    }
    with pytest.raises(ValueError, match='episode mapping'):
        validate_support_joint_tracks(malformed, ['right_knee'], 2)

    assert build_support_joint_tracks({'status': 'unknown'}, ['right_knee'], 2) is None


def test_native_material_owner_does_not_become_a_protected_joint_pin():
    episode = {
        'startFrame': 0, 'endFrame': 2, 'anchorId': 'material-anchor',
        'regionRole': 'forefoot', 'mode': 'stationary',
        'primitiveId': 'wearShoe:right_ankle->right_foot',
        'triangleIndex': 0, 'barycentric': [1., 0., 0.],
        'materialOffsetLocalMeters': [0., 0., 0.], 'referenceLengthMeters': .1,
        'targetWorld': [0., 0., 0.], 'surfaceNormal': [0., 1., 0.],
        'planeOffsetMeters': 0.,
    }
    evidence = {
        'status': 'confirmed',
        'stationaryJoints': ['right_knee', 'right_ankle', 'right_foot'],
        '_nativeFootMaterialTracks': {'version': 2, 'right': {
            'active': [True] * 3, 'directions': [[0., 0., 1.]] * 3,
            'sideAxes': [[-1., 0., 0.]] * 3, 'anchorIds': ['material-anchor'] * 3,
            'episodes': [episode],
        }},
    }
    built = build_support_joint_tracks(
        evidence, ['right_knee', 'right_ankle', 'right_foot'], 3)
    assert 'right_knee' in built['joints']
    assert 'right_ankle' in built['joints']  # explicit ankle ownership survives
    assert 'right_foot' not in built['joints']  # shoe material owns this constraint
