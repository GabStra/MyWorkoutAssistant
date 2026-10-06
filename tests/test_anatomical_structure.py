"""Anatomy is independent of source agreement and bilateral pose symmetry."""
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.physical_validation import anatomical_structure_residuals, validate_physical_motion, physical_metrics_from_payload
from exercise_motion_pkg.rig_playback import validate_rig_playback


def calibrated_stance(count=7):
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.array(list(fixture['joints'].values())), (count, 1, 1))
    rig = FixedRig(points, names)
    return names, rig, rig.decode(rig.initial)


def test_calibration_centers_sockets_and_matches_lengths_without_mirroring_pose():
    names, rig, points = calibrated_stance()
    assert not anatomical_structure_residuals(points, names)[0].any()
    for name in names:
        if name.startswith('left_'):
            other = name.replace('left_', 'right_', 1)
            np.testing.assert_allclose(np.linalg.norm(rig.offsets[names.index(name)]),
                                       np.linalg.norm(rig.offsets[names.index(other)]), atol=1e-12)
    # Independently rotate a left arm through safe poses; right arm stays put.
    values = rig.initial.copy()
    elbow = rig.slots[names.index('left_elbow')]
    values[:, elbow:elbow+3] = (Rotation.from_euler('y', np.linspace(0., .2, len(values))) *
                               Rotation.from_rotvec(values[:, elbow:elbow+3])).as_rotvec()
    moved = rig.decode(values)
    np.testing.assert_allclose(moved[:, names.index('right_wrist')], points[:, names.index('right_wrist')])
    assert np.linalg.norm(moved[-1, names.index('left_wrist')]-points[-1, names.index('left_wrist')]) > .01
    assert validate_physical_motion(moved, names)['passed']


def test_torso_bend_follows_flexed_reference_instead_of_upright_absolute():
    names, _, points = calibrated_stance()
    # Prone/supported torso: hip–spine–shoulder angle well below the upright floor.
    flexed = points.copy()
    upper = ('spine1', 'spine2', 'spine3', 'neck', 'head', 'left_collar', 'right_collar',
             'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
             'left_wrist', 'right_wrist', 'left_hand', 'right_hand')
    for name in upper:
        if name in names:
            flexed[:, names.index(name), 2] += .35
            flexed[:, names.index(name), 1] -= .2
    absolute, labels = anatomical_structure_residuals(flexed, names)
    relative, _ = anatomical_structure_residuals(flexed, names, reference=flexed)
    bend = [i for i, label in enumerate(labels) if label.startswith('anatomy_torso_bend')]
    assert bend and absolute[:, bend].max() > 1e-6
    assert relative[:, bend].max() <= 1e-6
    assert 'anatomy_torso_bend' not in validate_physical_motion(flexed, names, reference=flexed)['reasons']


def test_structure_is_invariant_to_world_rotation_translation_and_scale():
    names, _, points = calibrated_stance()
    turned = points @ Rotation.from_euler('xyz', [.8, -.6, 1.1]).as_matrix()*1.3+[3., -2., 5.]
    assert not anatomical_structure_residuals(turned, names)[0].any()


def test_banana_spine_is_rejected_even_when_identical_to_source():
    names, _, points = calibrated_stance()
    axis = points[0, names.index('neck')]-points[0, names.index('pelvis')]
    lateral = points[0, names.index('right_hip')]-points[0, names.index('left_hip')]
    forward = np.cross(axis, lateral)
    forward /= np.linalg.norm(forward)
    points[:, names.index('spine1')] += forward*.14
    report = validate_physical_motion(points, names, reference=points.copy())
    assert not report['passed']
    assert 'anatomy_spine_deviation' in report['reasons']


def test_displaced_neck_and_unequal_bones_are_not_authorized_by_source():
    names, _, points = calibrated_stance()
    lateral = points[0, names.index('right_collar')]-points[0, names.index('left_collar')]
    points[:, names.index('neck')] += lateral*.3
    points[:, names.index('left_hand')] += [0., .1, 0.]
    report = validate_physical_motion(points, names, reference=points.copy())
    assert 'anatomy_socket_alignment' in report['reasons']
    assert 'anatomy_bilateral_proportions' in report['reasons']


def test_neck_cannot_leave_the_chest_in_the_forward_backward_plane():
    names, _, points = calibrated_stance()
    neck, head, chest = [names.index(n) for n in ('neck', 'head', 'spine3')]
    displacement = -2.*(points[:, neck]-points[:, chest])
    points[:, neck] += displacement
    points[:, head] += displacement
    assert 'anatomy_chest_attachment' in validate_physical_motion(points, names)['reasons']


def test_stretching_source_cannot_authorize_stretching_output():
    names, _, points = calibrated_stance()
    points[-1, names.index('left_hand')] += [0., .04, 0.]
    assert 'anatomy_bone_length_variation' in validate_physical_motion(points, names, reference=points)['reasons']


def test_equally_elongated_limbs_are_rejected_without_a_source_reference():
    names, _, points = calibrated_stance()
    for side in ('left', 'right'):
        elbow, wrist, hand = [names.index(side+'_'+n) for n in ('elbow', 'wrist', 'hand')]
        extension = points[:, wrist]-points[:, elbow]
        points[:, wrist] += extension
        points[:, hand] += extension
    assert 'anatomy_segment_proportion' in validate_physical_motion(points, names)['reasons']


def test_millimetre_anatomical_span_leftover_does_not_void_legal_output(monkeypatch):
    from exercise_motion_pkg import anatomical_repair
    from exercise_motion_pkg.physical_validation import anatomical_reference_is_usable
    from test_controlled_motion_pipeline import accepted_payload

    points = np.zeros((2, 1, 3))
    names = ['pelvis']

    def span_leftover(pts, labels, span_targets=None):
        return np.array([[0.0012], [0.0]]), ['anatomy_span_variation:shoulders']

    monkeypatch.setattr(anatomical_repair, 'repair_residuals', span_leftover)
    assert anatomical_reference_is_usable(points, names)

    def corrupt(pts, labels, span_targets=None):
        return np.array([[0.0012, 0.05], [0.0, 0.0]]), [
            'anatomy_span_variation:shoulders', 'anatomy_torso_bend:spine1']

    monkeypatch.setattr(anatomical_repair, 'repair_residuals', corrupt)
    assert not anatomical_reference_is_usable(points, names)

    payload = accepted_payload()
    payload['anatomicalSourceRepair'] = {'passed': True}
    for frame in payload['frames']:
        frame['correctedAnatomicalReferenceJoints'] = dict(frame['joints'])
        frame['controlledArticulationReferenceJoints'] = dict(frame['joints'])
    monkeypatch.setattr(anatomical_repair, 'repair_residuals', span_leftover)
    from exercise_motion_pkg.physical_validation import physical_metrics_from_payload
    assert physical_metrics_from_payload(payload)['passed']


def test_export_and_interpolated_playback_reject_a_corrupt_constant_length_rig():
    names, rig, _ = calibrated_stance()
    values = rig.initial.copy()
    slot = rig.slots[names.index('spine2')]
    values[:, slot:slot+3] = (Rotation.from_euler('x', 100., degrees=True) *
                              Rotation.from_rotvec(values[:, slot:slot+3])).as_rotvec()
    points = rig.decode(values)
    payload = {'fps': 30., 'jointNames': names, 'loop': {'enabled': False},
               'fixedRig': {'jointNames': names, 'parents': rig.parents, 'order': rig.order,
                            'offsets': rig.offsets.tolist(), 'rotationJointNames': [names[j] for j in rig.active],
                            'coordinates': values.tolist()},
               'frames': [{'timeSec': i/30., 'joints': dict(zip(names, p.tolist())),
                           'controlledSourceJoints': dict(zip(names, p.tolist()))} for i, p in enumerate(points)]}
    report = validate_rig_playback(payload)
    assert report['maximumBoneLengthVariationMeters'] < 1e-12
    assert not report['passed']
    assert any(r.startswith('anatomy_spine_') for r in report['physicalReasons'])
    assert not physical_metrics_from_payload(payload)['passed']


def _stance_with_shoulder_span_swing(swing_meters):
    """Draw both shoulders symmetrically inward by swing_meters/2 each."""
    names, _, points = calibrated_stance()
    swung = points.copy()
    left, right = names.index('left_shoulder'), names.index('right_shoulder')
    inward = (swung[:, right] - swung[:, left])
    inward /= np.linalg.norm(inward, axis=1, keepdims=True)
    half = swing_meters*.5
    swung[2:5, left] += inward[2:5]*half
    swung[2:5, right] -= inward[2:5]*half
    return names, points, swung


def test_shoulder_girdle_span_swing_is_rejected():
    names, points, swung = _stance_with_shoulder_span_swing(.18)
    span = np.linalg.norm(swung[:, names.index('left_shoulder')]-swung[:, names.index('right_shoulder')], axis=1)
    deviation = np.max(np.abs(span-np.median(span)))/np.median(span)
    assert deviation > .12
    report = validate_physical_motion(swung, names)
    assert 'anatomy_span_variation' in report['reasons']


def test_small_shoulder_girdle_span_motion_is_accepted():
    names, points, swung = _stance_with_shoulder_span_swing(.01)
    assert validate_physical_motion(swung, names)['passed']


def test_raw_source_span_jitter_does_not_gate_non_fixed_rig_payload():
    names, points, swung = _stance_with_shoulder_span_swing(.18)
    payload = {'fps': 30., 'jointNames': names,
               'frames': [{'joints': dict(zip(names, p.tolist()))} for p in swung]}
    report = physical_metrics_from_payload(payload)
    assert 'anatomy_span_variation' not in report['reasons']
