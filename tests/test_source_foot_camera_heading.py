import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg import controlled_motion as motion


def _pose():
    fixture = json.loads(
        (Path(__file__).parent / 'fixtures' / 'sequence_stabilization_stance.json')
        .read_text(encoding='utf-8'))
    names = list(fixture['joints'])
    points = np.asarray([fixture['joints'][name] for name in names], dtype=float)[None, ...]
    index = {name: names.index(name) for name in names}
    # A simple valid right shin/foot frame makes the camera-nullspace case
    # explicit: the world-yaw change leaves the ankle angle unchanged.
    points[0, index['right_knee']] = [0., 0., 0.]
    points[0, index['right_ankle']] = [0., 1., 0.]
    points[0, index['right_foot']] = [0., 1., .12]
    return names, points, index


def _ray_constraint(index, target=(1., 0.)):
    return {
        'available': True,
        'projection': np.array([[0., 0., 1.], [0., 1., 0.]]),
        'sourceFootRaySideMapping': {'right': 'right'},
        'sourceFootRayObservations': [{
            'sourceSide': 'right', 'leftFrame': 0, 'rightFrame': 0, 'alpha': 0.,
            'ankleJointIndex': index['right_ankle'],
            'footJointIndex': index['right_foot'],
            'targetRay': np.asarray(target, dtype=float),
            'headingOffsetRadians': 0.,
        }],
    }


def test_observed_camera_heading_allows_ambiguous_3d_depth_yaw():
    names, source, index = _pose()
    candidate = source.copy()
    theta = np.deg2rad(23.425789)
    vector = candidate[0, index['right_foot']] - candidate[0, index['right_ankle']]
    candidate[0, index['right_foot']] = (
        candidate[0, index['right_ankle']]
        + Rotation.from_euler('y', theta).apply(vector))
    source_vector = source[0, index['right_foot']] - source[0, index['right_ankle']]
    candidate_vector = candidate[0, index['right_foot']] - candidate[0, index['right_ankle']]
    spatial_change = np.degrees(np.arccos(np.clip(
        np.dot(source_vector, candidate_vector)
        / np.linalg.norm(source_vector) / np.linalg.norm(candidate_vector), -1., 1.)))
    assert spatial_change == pytest.approx(23.425789, abs=1e-5)

    constraint = _ray_constraint(index)
    evidence = motion._source_foot_ray_fit_evidence(candidate, constraint)
    assert evidence['available'] is True
    assert evidence['passed'] is True
    assert evidence['gateApplied'] is True
    assert evidence['bySide']['right']['observationCount'] == 1
    assert evidence['absoluteAngularResidualP95Degrees'] == pytest.approx(0., abs=1e-8)

    regressions = motion.support_initialization_articulation_regressions(
        source, candidate, names, source_projection_constraint=constraint)
    assert not any(row['feature'].endswith('_foot_heading') for row in regressions)


def test_observed_camera_heading_over_15_degrees_still_rejects():
    names, source, index = _pose()
    candidate = source.copy()
    theta = np.deg2rad(23.425789)
    vector = candidate[0, index['right_foot']] - candidate[0, index['right_ankle']]
    candidate[0, index['right_foot']] = (
        candidate[0, index['right_ankle']]
        + Rotation.from_euler('y', theta).apply(vector))
    target_angle = np.deg2rad(20.)
    constraint = _ray_constraint(index, (np.cos(target_angle), np.sin(target_angle)))

    evidence = motion._source_foot_ray_fit_evidence(candidate, constraint)
    assert evidence['passed'] is False
    assert evidence['absoluteAngularResidualP95Degrees'] == pytest.approx(20.)
    regressions = motion.support_initialization_articulation_regressions(
        source, candidate, names, source_projection_constraint=constraint)
    row = next(row for row in regressions
               if row['feature'] == 'right_observed_camera_foot_heading')
    assert row['p95ChangeDegrees'] == pytest.approx(20.)
    assert row['toleranceDegrees'] == pytest.approx(15.)


def test_absent_ray_is_unavailable_and_positive_pitch_mask_still_applies():
    names, source, index = _pose()
    missing = motion._source_foot_ray_fit_evidence(
        source, {'available': True, 'sourceFootRayObservations': []})
    assert missing['available'] is False
    assert missing['passed'] is None
    assert missing['reason'] == 'independent_source_foot_ray_unavailable'

    candidate = source.copy()
    vector = candidate[0, index['right_foot']] - candidate[0, index['right_ankle']]
    candidate[0, index['right_foot']] = (
        candidate[0, index['right_ankle']]
        + Rotation.from_euler('x', 25., degrees=True).apply(vector))
    no_pitch_authority = motion.support_initialization_articulation_regressions(
        source, candidate, names)
    assert not any(row['feature'] == 'right_heel_pitch' for row in no_pitch_authority)
    qualified_pitch = motion.support_initialization_articulation_regressions(
        source, candidate, names,
        foot_pitch_authority_mask_by_side={'right': np.array([True])})
    assert any(row['feature'] == 'right_heel_pitch' for row in qualified_pitch)


def test_zero_camera_ray_is_unresolved_not_a_zero_error():
    names, source, index = _pose()
    evidence = motion._source_foot_ray_fit_evidence(
        source, _ray_constraint(index, (0., 0.)))
    assert evidence['available'] is False
    assert evidence['passed'] is False
    assert evidence['gateApplied'] is True
    assert evidence['reason'] == 'invalid_source_foot_ray_target'
