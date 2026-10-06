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


@pytest.mark.parametrize('remaining,completion_deadline,allowed', [
    (5, 100., True), (5, 21., False), (100, 100., False), (75, 100., False),
])
def test_repair_completion_protects_downstream_budget(remaining, completion_deadline, allowed):
    from exercise_motion_pkg.anatomical_repair import _repair_completion_deadline
    deadline = _repair_completion_deadline(
        started=0., now=20., deadline=20., completion_deadline=completion_deadline,
        projected_frames=100, remaining_frames=remaining,
    )
    assert (deadline is not None) is allowed
    if allowed:
        assert 20. < deadline <= min(30., completion_deadline)


def test_anatomy_completion_continues_partial_rig_without_restarting(monkeypatch):
    from exercise_motion_pkg import anatomical_repair as anatomy
    names, points = stance()
    axis = points[0, names.index('neck')] - points[0, names.index('pelvis')]
    lateral = points[0, names.index('right_hip')] - points[0, names.index('left_hip')]
    forward = np.cross(axis, lateral)
    forward /= np.linalg.norm(forward)
    points[:, names.index('spine1')] += np.linspace(.14, .15, len(points))[:, None] * forward
    generous_rig = FixedRig(points, names)
    monkeypatch.setattr(anatomy, 'monotonic', lambda: 0.)
    expected, full_report = repair_rig_anatomy(generous_rig, points, deadline=10.)
    assert full_report['passed']

    for expires_inside_frame in (False, True):
        resumed_rig = FixedRig(points, names)
        initial = resumed_rig.initial.copy()
        completion_clock_calls = [0]
        def clock():
            repaired = np.count_nonzero(np.any(resumed_rig.initial != initial, axis=1))
            if repaired < len(points) - 1:
                return 0.
            completion_clock_calls[0] += 1
            if expires_inside_frame and completion_clock_calls[0] == 1:
                return 0.  # Enter the last frame, then expire inside its solver.
            return 10.
        monkeypatch.setattr(anatomy, 'monotonic', clock)
        actual, report = repair_rig_anatomy(
            resumed_rig, points, deadline=10., completion_deadline=20.)
        assert report['passed']
        assert report['completionContinuation']['remainingFrameCount'] == 1
        assert report['evaluations'] == full_report['evaluations']
        np.testing.assert_array_equal(actual, expected)


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


def test_anatomical_repair_uses_the_source_relative_torso_bend_floor():
    from exercise_motion_pkg.anatomical_repair import repair_residuals

    names, points = stance()
    upper = ('spine1', 'spine2', 'spine3', 'neck', 'head', 'left_collar',
             'right_collar', 'left_shoulder', 'right_shoulder', 'left_elbow',
             'right_elbow', 'left_wrist', 'right_wrist', 'left_hand', 'right_hand')
    for name in upper:
        if name in names:
            points[:, names.index(name), 2] += .35
            points[:, names.index(name), 1] -= .2

    absolute, labels = repair_residuals(points, names)
    source_relative, _ = repair_residuals(points, names, reference=points)
    torso_bend = [i for i, label in enumerate(labels)
                  if label.startswith('anatomy_torso_bend:')]
    assert torso_bend
    assert absolute[:, torso_bend].max() > 1e-6
    assert source_relative[:, torso_bend].max() <= 1e-6

    rig = FixedRig(points, names)
    corrected, report = repair_rig_anatomy(
        rig, points, reference=points, deadline=monotonic()+10.)
    assert report['passed']
    from exercise_motion_pkg.physical_validation import anatomical_structure_residuals
    corrected_residuals, corrected_labels = anatomical_structure_residuals(
        corrected, names, reference=points)
    torso_bend = [i for i, label in enumerate(corrected_labels)
                  if label.startswith('anatomy_torso_bend:')]
    assert torso_bend
    assert corrected_residuals[:, torso_bend].max() <= 1e-6


def test_spine_alignment_preserves_each_parent_bone_length():
    from exercise_motion_pkg.anatomical_repair import enforce_spine_axis_alignment

    names = ['pelvis', 'spine1', 'spine2', 'spine3', 'neck']
    points = np.zeros((2, len(names), 3), dtype=float)
    points[0, :, 1] = [0., .2, .4, .6, 1.]
    points[1, 1] = [.20, .20, 0.]
    points[1, 2] = [.28, .45, 0.]
    points[1, 3] = [.25, .38, 0.]
    points[1, 4] = [0., 1., 0.]

    corrected, report = enforce_spine_axis_alignment(points, names)

    assert report['applied'] is True
    parents = {'spine1': 'pelvis', 'spine2': 'spine1', 'spine3': 'spine2'}
    for child, parent in parents.items():
        before = np.linalg.norm(
            points[:, names.index(child)] - points[:, names.index(parent)], axis=-1)
        after = np.linalg.norm(
            corrected[:, names.index(child)] - corrected[:, names.index(parent)], axis=-1)
        np.testing.assert_allclose(after, before, atol=1e-9)


def test_rigid_bone_length_repair_preserves_input_directions():
    from exercise_motion_pkg.anatomical_repair import enforce_rigid_bone_lengths

    names = ['pelvis', 'spine1', 'spine2', 'spine3', 'neck']
    points = np.zeros((2, len(names), 3), dtype=float)
    points[0, :, 1] = [0., .2, .4, .6, .8]
    points[1, 1] = [.12, .24, 0.]
    points[1, 2] = [.24, .51, .02]
    points[1, 3] = [.36, .58, .08]
    points[1, 4] = [.42, .81, .1]

    corrected = enforce_rigid_bone_lengths(points, names)

    parents = {'spine1': 'pelvis', 'spine2': 'spine1', 'spine3': 'spine2', 'neck': 'spine3'}
    for child, parent in parents.items():
        before = points[:, names.index(child)] - points[:, names.index(parent)]
        after = corrected[:, names.index(child)] - corrected[:, names.index(parent)]
        before_direction = before / np.linalg.norm(before, axis=-1, keepdims=True)
        after_direction = after / np.linalg.norm(after, axis=-1, keepdims=True)
        np.testing.assert_allclose(after_direction, before_direction, atol=1e-9)
        np.testing.assert_allclose(
            np.linalg.norm(after, axis=-1), np.median(np.linalg.norm(before, axis=-1)), atol=1e-9)


def test_spine_fold_repair_handles_framewise_world_axis_changes():
    from exercise_motion_pkg.anatomical_repair import (
        enforce_rigid_bone_lengths,
        enforce_spine_axis_alignment,
    )
    from exercise_motion_pkg.physical_validation import anatomical_structure_residuals

    names = ['pelvis', 'spine1', 'spine2', 'spine3', 'neck']
    axes = np.asarray([
        [1., 0., 0.],
        [-.9, .3, .3],
        [-.1, .6, .8],
    ])
    axes /= np.linalg.norm(axes, axis=1, keepdims=True)
    points = np.zeros((len(axes), len(names), 3), dtype=float)
    points[:, names.index('neck')] = axes
    points[:, names.index('spine1')] = .25 * axes
    points[:, names.index('spine2')] = .50 * axes
    points[:, names.index('spine3')] = .75 * axes
    # The first frame has an exactly collinear backward segment. Its axis is
    # parallel to the old sequence-average fallback helper.
    points[0, names.index('spine3')] = .41 * axes[0]

    aligned, report = enforce_spine_axis_alignment(points, names)
    corrected = enforce_rigid_bone_lengths(aligned, names)
    residuals, labels = anatomical_structure_residuals(corrected, names, pose_only=True)
    spine_fold_columns = [i for i, label in enumerate(labels) if label.startswith('anatomy_spine_fold:')]

    assert report['joints']['spine3']['foldClampedFrameCount'] == 1
    assert spine_fold_columns
    assert not np.any(residuals[:, spine_fold_columns] > 1e-9)


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


def test_bounded_repair_preserves_source_head_direction_and_structure():
    from exercise_motion_pkg.temporal_quality import body_local_head_direction

    names, source = stance()
    rig = FixedRig(source, names)
    source, baseline = repair_rig_anatomy(
        rig, rig.decode(rig.initial), deadline=monotonic() + 10.)
    assert baseline['passed']
    neck = rig.slots[names.index('neck')]
    rig.initial[:, neck] += .5
    observed = rig.decode(rig.initial)
    before = body_local_head_direction(observed, names)
    reference = body_local_head_direction(source, names)
    assert np.rad2deg(np.arccos(np.clip(np.sum(before * reference, axis=1), -1., 1.))).max() > 15.25
    corrected, report = repair_rig_anatomy(
        rig, observed, reference=source, deadline=monotonic() + 10.)
    assert 'repair_head_articulation_distortion:head' in report['sourceViolations']
    assert report['passed'], report
    after = body_local_head_direction(corrected, names)
    assert np.rad2deg(np.arccos(np.clip(np.sum(after * reference, axis=1), -1., 1.))).max() < 15.25
    from exercise_motion_pkg.anatomical_repair import free_rotation_columns
    assert free_rotation_columns(rig, ['repair_head_articulation_distortion:head']) == list(range(neck, neck + 3))
    np.testing.assert_allclose(corrected[:, names.index('pelvis')], observed[:, names.index('pelvis')], atol=1e-10)
