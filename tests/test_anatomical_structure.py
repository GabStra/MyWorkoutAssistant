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


def test_playback_uses_time_aligned_articulation_and_rejects_mid_sample_overrun(monkeypatch):
    from types import SimpleNamespace

    from exercise_motion_pkg import body_support_observation, equipment_constraints
    from exercise_motion_pkg import foot_geometry, heel_contacts, loop_seam
    from exercise_motion_pkg import rig_playback, support_alignment, support_geometry
    from exercise_motion_pkg.physical_validation import validate_physical_motion
    from test_controlled_motion_pipeline import accepted_payload

    payload = accepted_payload()
    names = payload['jointNames']
    index = {name: i for i, name in enumerate(names)}
    joints = np.asarray([payload['frames'][0]['joints'][name] for name in names])
    hip, knee = joints[index['left_hip']], joints[index['left_knee']]
    parent_axis = (hip-knee) / np.linalg.norm(hip-knee)
    perpendicular = np.array([0., 0., 1.])
    perpendicular -= parent_axis * np.dot(parent_axis, perpendicular)
    perpendicular /= np.linalg.norm(perpendicular)
    cross_axis = np.cross(parent_axis, perpendicular)
    cross_axis /= np.linalg.norm(cross_axis)
    ankle_length = np.linalg.norm(joints[index['left_ankle']]-knee)

    def pose(cursor, knee_angle_degrees=135.):
        result = joints.copy()
        bend_phase = np.deg2rad(90. * cursor / 6.)
        bend_plane = np.cos(bend_phase)*perpendicular + np.sin(bend_phase)*cross_axis
        angle = np.deg2rad(knee_angle_degrees)
        ankle = knee + ankle_length*(np.cos(angle)*parent_axis + np.sin(angle)*bend_plane)
        delta = ankle-result[index['left_ankle']]
        result[index['left_ankle']] = ankle
        result[index['left_foot']] += delta
        return result

    key_points = np.asarray([pose(float(i)) for i in range(7)])
    for i, point in enumerate(key_points):
        frame = payload['frames'][i]
        for field in ('joints', 'controlledSourceJoints'):
            frame[field] = dict(zip(names, point.tolist()))
        frame['controlledArticulationReferenceJoints'] = dict(zip(names, point.tolist()))

    add_overrun = {'enabled': False}

    def sample(rig, cursors, *, wrap=False):
        return np.asarray([
            pose(float(cursor), 110. if add_overrun['enabled']
                 and abs(float(cursor)-2.5) < 1e-8 else 135.)
            for cursor in cursors
        ])

    monkeypatch.setattr(rig_playback, 'sample_rig', sample)
    monkeypatch.setattr(rig_playback, 'contact_mask',
                        lambda *_args, **_kwargs: np.zeros((7, len(names)), dtype=bool))
    monkeypatch.setattr(body_support_observation, 'materialize_stationary_sole_support', lambda _: {})
    monkeypatch.setattr(heel_contacts, 'heel_contact_tracks', lambda *_args, **_kwargs:
                        SimpleNamespace(pairs=[], residual=lambda *_a: np.empty((0, 3))))
    monkeypatch.setattr(loop_seam, 'seam_quality_metrics',
                        lambda *_args, **_kwargs: {'seamContinuous': True})
    monkeypatch.setattr(equipment_constraints, 'validate_grip', lambda *_: {'passed': True})
    monkeypatch.setattr(support_geometry, 'validate_support_geometry', lambda *_: {'passed': True})
    monkeypatch.setattr(support_geometry, 'validate_supported_shoe_orientation', lambda *_: {'passed': True})
    monkeypatch.setattr(foot_geometry, 'validate_material_shoes', lambda *_args, **_kwargs: {'passed': True})
    monkeypatch.setattr(support_alignment, 'validate_payload_alignment', lambda *_args, **_kwargs: {'passed': True})

    cursors = np.arange(25, dtype=float)/4.
    output = sample(payload['fixedRig'], cursors)
    left_endpoint_reference = np.repeat(key_points[:1], len(cursors), axis=0)
    legacy = validate_physical_motion(output, names, reference=left_endpoint_reference, fps=120.)
    assert any(event['reason'] == 'repair_hinge_direction_distortion'
               and event['joint'] == 'left_knee' for event in legacy['events'])

    clean = rig_playback.validate_rig_playback(payload)
    assert clean['passed']
    assert 'repair_hinge_direction_distortion' not in clean['physicalReasons']
    assert 'repair_articulation_distortion' not in clean['physicalReasons']

    # A real 25-degree knee change at a subframe must survive playback filtering.
    add_overrun['enabled'] = True
    overrun = rig_playback.validate_rig_playback(payload)
    knee_events = [event for event in overrun['physicalEvents']
                   if event.get('reason') == 'repair_articulation_distortion'
                   and event.get('joint') == 'left_knee']
    assert knee_events
    assert max(abs(event['changeDegrees']) for event in knee_events) > 10.25


def test_sample_rig_applies_contact_foot_tracks_after_forward_kinematics():
    from exercise_motion_pkg.contact_interpolation import build_contact_foot_tracks
    from exercise_motion_pkg.rig_playback import sample_rig

    names, rig, _ = calibrated_stance(count=2)
    keypoints = rig.decode(rig.initial)
    payload = {
        'jointNames': names,
        'fixedRig': {
            'jointNames': names,
            'parents': rig.parents,
            'order': rig.order,
            'offsets': rig.offsets.tolist(),
            'rotationJointNames': [names[j] for j in rig.active],
            'coordinates': rig.initial.tolist(),
        },
    }
    pinned = np.zeros((len(keypoints), len(names)), dtype=bool)
    pinned[:, names.index('left_foot')] = True
    tracks = build_contact_foot_tracks(rig, keypoints, pinned)
    tracks['left']['toes'] = (
        np.asarray(tracks['left']['toes']) + np.array([.01, 0., 0.])
    ).tolist()
    payload['fixedRig']['contactFootTracks'] = tracks

    raw = sample_rig({**payload['fixedRig'], 'contactFootTracks': None}, [.5, 0., 1.])
    sampled = sample_rig(payload['fixedRig'], [.5, 0., 1.])
    toe = names.index('left_foot')
    ankle = names.index('left_ankle')
    assert np.isclose(sampled[0, toe, 0] - raw[0, toe, 0], .01, atol=1e-6)
    assert not np.allclose(sampled[0, ankle], raw[0, ankle])
    np.testing.assert_array_equal(sampled[1:], raw[1:])


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
