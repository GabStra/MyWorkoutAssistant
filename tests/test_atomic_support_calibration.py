import copy
import json
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import numpy as np


def test_verified_static_frame_admits_seed_without_owning_anatomy_or_guard_scope():
    from exercise_motion_pkg import controlled_motion as c
    from exercise_motion_pkg.physical_validation import torso_bend_floor
    # The actual rejected Cable frame99 would lower its source spine floor
    # from145 to143.9997208 degrees if the seed became its own reference.
    def pose(angle):
        radians = np.deg2rad(angle)
        return np.array([[[0., 0., 0.], [0., 1., 0.],
                          [np.sin(radians), 1.-np.cos(radians), 0.]]])
    source, seed = pose(147.), pose(144.99972081385047)
    selected = c.fit_anatomy_constraint_reference(source)
    np.testing.assert_array_equal(selected, source)
    assert np.rad2deg(torso_bend_floor(*[selected[:, i] for i in range(3)]))[0] == 145.
    assert torso_bend_floor(*[seed[:, i] for i in range(3)])[0] < np.deg2rad(144.)
    report = {'sourceSupportAuthority': {'status': 'verified', 'passed': True},
              'supportCalibrationFrameValidation': {'passed': True},
              'supportReferenceAlignment': {'passed': True},
              'supportReferenceEquipment': {'passed': True},
              'supportReferenceAnatomy': {'passed': False},
              'supportReferenceGeometry': {'passed': False}}
    assert c.supported_seed_frame_is_valid(report)
    for key in ('sourceSupportAuthority', 'supportCalibrationFrameValidation',
                'supportReferenceAlignment', 'supportReferenceEquipment'):
        unknown = copy.deepcopy(report); unknown[key] = {}
        assert not c.supported_seed_frame_is_valid(unknown)
    assert c.support_articulation_guard_required(False, {'_floorMaterialContacts': ['left_knee']})
    assert c.support_articulation_guard_required(True, {})
    assert not c.support_articulation_guard_required(False, {'required': True})


def test_source_foot_guard_sees_body_yaw_with_exact_world_foot_vectors():
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg import controlled_motion as c
    from exercise_motion_pkg.support_geometry import _support_foot_p95_rows
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    rig = c.FixedRig(np.asarray([[fixture['joints'][name] for name in names]]*3), names)
    candidate = rig.decode(rig.initial)
    source = candidate.copy()
    for frame, angle in enumerate((-32., -35., -38.)):
        source[frame] = Rotation.from_euler('y', angle, degrees=True).apply(candidate[frame])
    for side in ('left', 'right'):
        ankle, toe = [names.index(side+'_'+part) for part in ('ankle', 'foot')]
        source[:, toe] = source[:, ankle]+candidate[:, toe]-candidate[:, ankle]
        np.testing.assert_allclose(candidate[:, toe]-candidate[:, ankle],
                                   source[:, toe]-source[:, ankle], atol=1e-15)
    authority = np.ones(source.shape[:2], dtype=bool)
    rows = _support_foot_p95_rows(rig, rig.initial, source, authority)
    assert np.all(rows[[0, 2]] > 0.)
    jacobian = _support_foot_p95_rows(rig, rig.initial, source, authority, jacobian=True)
    column = rig.slots[names.index('spine1')]+1
    flat_column = 2*rig.width+column
    assert jacobian[:, flat_column].nnz
    plus, minus = rig.initial.copy(), rig.initial.copy()
    plus[2, column] += 1e-6; minus[2, column] -= 1e-6
    difference = (_support_foot_p95_rows(rig, plus, source, authority)
                  - _support_foot_p95_rows(rig, minus, source, authority))/2e-6
    np.testing.assert_allclose(jacobian[:, flat_column].toarray().ravel(), difference,
                               atol=2e-5, rtol=2e-5)
    authority[:, names.index('left_foot')] = False
    assert np.all(_support_foot_p95_rows(rig, rig.initial, source, authority)[:2] == 0.)


def test_fixed_anchor_source_direction_restoration_is_strict_and_atomic():
    from exercise_motion_pkg import controlled_motion as c
    from exercise_motion_pkg.support_geometry import restore_supported_foot_directions
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    rig = c.FixedRig(np.asarray([[fixture['joints'][name] for name in names]]*3), names)
    original = rig.initial.copy()
    reference = rig.decode(original)
    candidate = original.copy()
    candidate[:, rig.slots[names.index('left_foot')]+1] += .7
    pinned = np.zeros(reference.shape[:2], dtype=bool)
    pinned[:, [names.index('left_knee'), names.index('left_ankle')]] = True
    targets = reference.copy()
    payload = {'jointNames': names, 'fps': 30., 'renderFloorY': -10.,
               'frames': [{'joints': dict(zip(names, row.tolist()))} for row in reference]}
    evidence = {'status': 'confirmed', 'stationaryJoints': ['left_knee', 'left_ankle'],
                '_materialShoePayload': payload}
    kwargs = dict(pinned=pinned, contact_targets=targets, alignment_reference=reference,
                  anatomical_reference=reference)
    assert c.support_initialization_articulation_regressions(reference, rig.decode(candidate), names)
    corrected, report = restore_supported_foot_directions(
        rig, candidate, reference, evidence, monotonic()+10., **kwargs)
    assert report['passed'], report
    assert not c.support_initialization_articulation_regressions(reference, rig.decode(corrected), names)
    np.testing.assert_array_equal(rig.initial, original)
    np.testing.assert_array_equal(targets, reference)
    bad = candidate.copy(); bad[:, 0] += .1
    rejected, report = restore_supported_foot_directions(
        rig, bad, reference, evidence, monotonic()+10., **kwargs)
    assert not report['passed'] and report['reason'] == 'physical_reference_requires_polish'
    np.testing.assert_array_equal(rejected, bad)
    np.testing.assert_array_equal(rig.initial, original)
    np.testing.assert_array_equal(targets, reference)


def test_static_calibration_cannot_pass_with_native_shoes_below_floor(monkeypatch):
    from exercise_motion_pkg.controlled_motion import FixedRig
    from exercise_motion_pkg.support_geometry import calibrate_support_pose, validate_static_support_pose
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    rig = FixedRig(np.asarray([[fixture['joints'][name] for name in names]]), names)
    points = rig.decode(rig.initial)
    original = rig.initial.copy()
    knee = names.index('left_knee')
    evidence = {'required': True, 'status': 'confirmed', 'stationaryJoints': ['left_knee'],
                'coplanarGroups': [{'joints': ['left_knee'], 'normal': [0., 1., 0.],
                                    'planeOffsetMeters': float(points[0, knee, 1])}]}
    evidence['_materialShoePayload'] = {
        'jointNames': names, 'fps': 30.,
        'renderFloorY': float(min(points[0, names.index(side+'_foot'), 1]
                                  for side in ('left', 'right'))+.05),
        'frames': [{'joints': dict(zip(names, points[0].tolist()))}]}

    def unchanged(residual, values, **kwargs):
        errors = residual(values)
        return SimpleNamespace(x=values.copy(), nfev=1, status=1, cost=float(errors@errors)/2.)

    monkeypatch.setattr('scipy.optimize.least_squares', unchanged)
    pose, report = calibrate_support_pose(rig, points, evidence, deadline=monotonic()+10.)
    assert pose is None and not report['passed']
    assert report['stationaryTangentErrorMeters'] < 1e-12
    assert report['shoeSurfacePenetrationMeters'] > .002
    np.testing.assert_array_equal(rig.initial, original)
    cached = validate_static_support_pose(rig, points, evidence, points[0],
        {'passed': True, 'coordinates': original[0].tolist()})
    assert not cached['passed'] and cached['shoeSurfacePenetrationMeters'] > .002


def test_fixed_calibration_keeps_connected_lengths_and_source_guard_jacobian():
    from exercise_motion_pkg import controlled_motion as c
    from exercise_motion_pkg.support_geometry import _support_foot_p95_rows
    fixture = json.loads((Path(__file__).parent/'fixtures/material_floor_anchor_conflict.json').read_text())
    names = fixture['names']
    points = np.asarray(fixture['points'])
    rig = c.FixedRig(points, names)
    rig.offsets[:] = fixture['offsets']
    rig.initial[:] = fixture['coordinates']
    original_q = rig.initial.copy()
    evidence = copy.deepcopy(fixture['evidence'])
    evidence['stationaryJoints'] = ['left_knee', 'right_knee', 'left_ankle']
    payload = {'jointNames': names, 'fps': 30., 'renderFloorY': evidence['_renderFloorY'],
               'frames': [{'joints': dict(zip(names, row.tolist()))} for row in points],
               'sourceFootSupportEvidence': {'bodySupport': copy.deepcopy(evidence)}}
    evidence['_materialShoePayload'] = payload
    pose = rig.decode(rig.initial[:1])[0]
    calibration = {'coordinates': original_q[0].tolist(), 'referenceCoordinates': original_q[0].tolist()}
    original_calibration = copy.deepcopy(calibration)
    pinned = np.zeros(points.shape[:2], bool)
    pinned[:, [names.index(name) for name in evidence['stationaryJoints']]] = True
    targets = rig.decode(original_q).copy()
    targets[pinned] = np.broadcast_to(pose, points.shape)[pinned]
    original_targets = targets.copy()
    reference = rig.decode(original_q)

    knee, ankle = [names.index('left_'+part) for part in ('knee', 'ankle')]
    np.testing.assert_allclose(np.linalg.norm(targets[:, knee]-targets[:, ankle], axis=-1),
                               np.linalg.norm(rig.offsets[ankle]), atol=1e-12)
    np.testing.assert_array_equal(rig.initial, original_q)
    np.testing.assert_array_equal(targets, original_targets)
    assert calibration == original_calibration

    changed = original_q.copy()
    column = rig.slots[names.index('left_foot')]
    changed[:, column] += [.45, .65, .85]
    analytic = _support_foot_p95_rows(rig, changed, reference, jacobian=True)
    index = 2*rig.width+column
    plus, minus = changed.ravel().copy(), changed.ravel().copy()
    plus[index] += 1e-6; minus[index] -= 1e-6
    difference = (_support_foot_p95_rows(rig, plus.reshape(changed.shape), reference)
                  - _support_foot_p95_rows(rig, minus.reshape(changed.shape), reference))/2e-6
    assert np.any(_support_foot_p95_rows(rig, changed, reference) > 0.)
    np.testing.assert_allclose(analytic[:, index].toarray().ravel(), difference, atol=2e-5, rtol=2e-5)
