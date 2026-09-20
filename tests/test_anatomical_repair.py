"""Malformed WHAM geometry is corrected, not merely diagnosed and discarded."""
from copy import deepcopy
import json
from pathlib import Path
from time import monotonic

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.anatomical_repair import repair_rig_anatomy, torso_directions
from exercise_motion_pkg.controlled_motion import FixedRig, fit_controlled_motion, can_reuse_controlled_motion
from exercise_motion_pkg.physical_validation import validate_physical_motion, physical_metrics_from_payload


def stance():
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.array(list(fixture['joints'].values())), (7, 1, 1))
    rig = FixedRig(points, names)
    return names, rig.decode(rig.initial)


def test_feasible_rig_is_not_reposed_by_anatomical_projection():
    names, points = stance()
    rig = FixedRig(points, names)
    initial = rig.initial.copy()
    corrected, report = repair_rig_anatomy(rig, points, deadline=monotonic()+10.)
    assert report['passed'] and report['evaluations'] == 0
    np.testing.assert_array_equal(initial, rig.initial)
    np.testing.assert_allclose(corrected, points, atol=1e-12)


def test_repair_detects_constant_span_mismatch_against_observed_clip():
    names, points = stance()
    rig = FixedRig(points, names)
    observed = points.copy()
    left, right = names.index('left_shoulder'), names.index('right_shoulder')
    axis = points[:, right] - points[:, left]
    axis /= np.linalg.norm(axis, axis=1)[:, None]
    observed[:, left] -= .05 * axis
    observed[:, right] += .05 * axis
    # Expired budget isolates detection: a constant rig width is internally
    # stable, but it does not meet this clip's observed span constraint.
    _, report = repair_rig_anatomy(rig, observed, deadline=monotonic() - 1.)
    assert report['projectedFrameCount'] == len(points)
    assert report['unrepairedFrameCount'] == len(points)
    assert 'anatomy_span_variation:shoulders' in report['remainingViolations']


def test_priority_yield_during_warm_start_preserves_completed_repair(monkeypatch):
    from exercise_motion_pkg import anatomical_repair as anatomy, fit_runtime
    names, points = stance()
    points = points[:3].copy()
    axis = points[0, names.index('neck')] - points[0, names.index('pelvis')]
    lateral = points[0, names.index('right_hip')] - points[0, names.index('left_hip')]
    forward = np.cross(axis, lateral)
    forward /= np.linalg.norm(forward)
    points[:, names.index('spine1')] += np.array([.14, .145, .15])[:, None] * forward
    rig = FixedRig(points, names)
    initial = rig.initial.copy()
    yield_requested = [False]
    solve = anatomy.least_squares
    def solve_first(*args, **kwargs):
        try:
            return solve(*args, **kwargs)
        finally:
            yield_requested[0] = True
    monkeypatch.setattr(anatomy, 'least_squares', solve_first)
    monkeypatch.setattr(fit_runtime, 'fit_should_yield_for_priority', lambda: yield_requested[0])
    corrected, report = repair_rig_anatomy(rig, points, deadline=monotonic()+10.)
    assert report['passed'] is False
    assert report['unrepairedFrameCount'] == 2
    assert report['evaluations'] > 0
    assert not np.array_equal(rig.initial[0], initial[0])
    np.testing.assert_array_equal(rig.initial[1:], initial[1:])
    assert np.isfinite(corrected).all()


def test_valid_forward_lean_and_world_tilt_are_preserved():
    names, points = stance()
    points = points @ Rotation.from_euler('xyz', [.7, -.3, .9]).as_matrix()+[2., -1., .5]
    rig = FixedRig(points, names)
    corrected, report = repair_rig_anatomy(rig, points, deadline=monotonic()+10.)
    assert report['passed'] and report['evaluations'] == 0
    np.testing.assert_allclose(corrected, points, atol=1e-12)


def test_back_curve_repair_preserves_overall_torso_lean():
    names, points = stance()
    points = points @ Rotation.from_euler('xyz', [.6, .2, .5]).as_matrix()
    axis = points[0, names.index('neck')]-points[0, names.index('pelvis')]
    lateral = points[0, names.index('right_hip')]-points[0, names.index('left_hip')]
    forward = np.cross(axis, lateral)
    points[:, names.index('spine1')] += forward/np.linalg.norm(forward)*.14
    rig = FixedRig(points, names)
    corrected, report = repair_rig_anatomy(rig, points, deadline=monotonic()+30.)
    assert report['passed'], report
    assert report['maximumCorrectionMeters'] > .01
    assert report['maximumTorsoDirectionChangeDegrees'] < .01
    np.testing.assert_allclose(torso_directions(corrected, names), torso_directions(points, names), atol=1e-5)
    np.testing.assert_array_equal(corrected[:, rig.root], points[:, rig.root])
    assert validate_physical_motion(corrected, names)['passed']


def test_impossible_bilateral_forearm_lengths_are_corrected():
    names, points = stance()
    for side in ('left', 'right'):
        elbow, wrist, hand = [names.index(side+'_'+n) for n in ('elbow','wrist','hand')]
        extension = points[:, wrist]-points[:, elbow]
        points[:, wrist] += extension
        points[:, hand] += extension
    rig = FixedRig(points, names)
    corrected, report = repair_rig_anatomy(rig, points, deadline=monotonic()+20.)
    assert report['applied'] and report['passed'], report
    assert validate_physical_motion(corrected, names)['passed']
    np.testing.assert_allclose(corrected[:, names.index('left_foot')], points[:, names.index('left_foot')], atol=1e-12)


@pytest.mark.parametrize('placement_shift,yaw', [(0., 0.), (.25, .7)])
def test_folded_source_is_corrected_and_accepted_without_erasing_original(monkeypatch, placement_shift, yaw):
    from exercise_motion_pkg import anatomical_repair, controlled_motion

    calls = []
    original_repair = anatomical_repair.repair_rig_anatomy

    def counted_repair(*args, **kwargs):
        calls.append(True)
        return original_repair(*args, **kwargs)

    monkeypatch.setattr(anatomical_repair, 'repair_rig_anatomy', counted_repair)
    monkeypatch.setattr(controlled_motion, 'register_contact_placement',
                        lambda points, *args, **kwargs: (points @ Rotation.from_euler('y', yaw).as_matrix()+[placement_shift, 0., 0.],
                                              {'applied': bool(placement_shift or yaw)}))
    names, points = stance()
    axis = points[0, names.index('neck')]-points[0, names.index('pelvis')]
    lateral = points[0, names.index('right_hip')]-points[0, names.index('left_hip')]
    forward = np.cross(axis, lateral)
    points[:, names.index('spine1')] += forward/np.linalg.norm(forward)*.14
    assert not validate_physical_motion(points, names)['passed']
    payload = {'fps': 30., 'jointNames': names, 'loop': {'enabled': False},
               'frames': [{'timeSec': i/30., 'joints': dict(zip(names, p.tolist())),
                           'sourceJoints': dict(zip(names, p.tolist()))} for i, p in enumerate(points)]}
    original = deepcopy(payload)
    result, report = fit_controlled_motion(payload, timeout_seconds=60.)
    assert payload == original
    assert report['applied'], report
    assert report['anatomicalSourceRepair']['passed']
    assert report['anatomicalSourceRepair']['reusedInitialization']
    assert len(calls) == 1
    assert report['anatomicalSourceRepair']['maximumCorrectionMeters'] > .01
    assert report['playback']['passed']
    assert physical_metrics_from_payload(result)['passed']
    # Scene placement may translate raw evidence, but must retain its shape.
    raw = np.array([[f['sourceJoints'][n] for n in names] for f in result['frames']])
    np.testing.assert_allclose(raw-raw[:, :1], points-points[:, :1], atol=1e-12)
    result['controlledMotionFit'] = report
    assert can_reuse_controlled_motion(result)
    from exercise_motion_pkg.bake_and_rank import compute_kinematic_plausibility_metrics_from_payload
    metrics = compute_kinematic_plausibility_metrics_from_payload(result)
    assert 'physical_pose_constraint_violation' not in metrics['artifactReasons']
    assert 'controlled_motion_fit_rejected' not in metrics['artifactReasons']
    result['frames'][0]['correctedAnatomicalReferenceJoints']['head'][0] += .4
    assert not can_reuse_controlled_motion(result)
    assert not physical_metrics_from_payload(result)['passed']


def test_anatomical_repair_reuse_rejects_changed_articulation_and_reflection():
    from exercise_motion_pkg.anatomical_repair import transport_equivalent_anatomical_repair

    names, points = stance()
    altered = points.copy()
    altered[:, names.index('left_wrist'), 0] += .01
    assert transport_equivalent_anatomical_repair(points, points, altered, names) is None
    assert transport_equivalent_anatomical_repair(points, points, points*[-1., 1., 1.], names) is None


def test_shoulder_girdle_span_swing_is_repaired_to_a_rigid_width():
    names, points = stance()
    left, right = names.index('left_shoulder'), names.index('right_shoulder')
    inward = points[:, right]-points[:, left]
    inward /= np.linalg.norm(inward, axis=1, keepdims=True)
    points[2:5, left] += inward[2:5]*.04
    points[2:5, right] -= inward[2:5]*.04
    span = lambda a: np.linalg.norm(a[:, left]-a[:, right], axis=1)
    assert np.max(np.abs(span(points)-np.median(span(points)))) > .06

    rig = FixedRig(points, names)
    corrected, report = repair_rig_anatomy(rig, points, deadline=monotonic()+30.)
    assert 'anatomy_span_variation:shoulders' in report['sourceViolations']
    assert 'anatomy_span_variation:shoulders' not in report['remainingViolations']
    assert report['passed']
    from exercise_motion_pkg.physical_validation import SPAN_TOLERANCE_METERS, SPAN_TOLERANCE_RATIO
    limit = max(SPAN_TOLERANCE_METERS, np.median(span(points))*SPAN_TOLERANCE_RATIO)
    assert np.max(np.abs(span(corrected)-np.median(span(points)))) <= limit + 1e-6
