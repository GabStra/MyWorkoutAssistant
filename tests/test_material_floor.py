import json
from copy import copy
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import numpy as np

from exercise_motion_pkg.controlled_motion import FixedRig, _sampling_payload
from exercise_motion_pkg.material_floor import MaterialFloorConstraint
from exercise_motion_pkg.render_geometry import material_body_axes, material_leg_sides
from exercise_motion_pkg.rig_playback import sample_rig
from exercise_motion_pkg.support_geometry import _floor_material_region


def test_exact_material_history_and_native_quarter_jacobian(monkeypatch):
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.asarray([[fixture['joints'][name] for name in names]] * 7)
    for side in ('left', 'right'):
        hip, knee, ankle, foot = [names.index(side + '_' + part) for part in ('hip', 'knee', 'ankle', 'foot')]
        points[:, knee] = points[:, hip] + [0., -.4, 0.]
        points[:, ankle] = points[:, knee] + [.4, 0., 0.]
        points[:, foot] = points[:, ankle] + [0., -.15, .03]
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    coordinates[:, rig.slots[names.index('left_knee')] + 2] += .03 * np.sin(np.arange(7))
    three = coordinates[:3].copy()
    three_jacobian = rig.fk_jacobian(three)
    assert three_jacobian.shape == (3 * len(names) * 3, 3 * rig.width)
    probe = rig.slots[names.index('pelvis')] + 1
    plus, minus = three.copy(), three.copy()
    plus[0, probe] += 1e-6
    minus[0, probe] -= 1e-6
    np.testing.assert_allclose(three_jacobian[:, probe].toarray().ravel(),
        ((rig.decode(plus) - rig.decode(minus)) / 2e-6).ravel(), atol=2e-7)
    points = rig.decode(coordinates)
    frames = [{'joints': dict(zip(names, row.tolist()))} for row in points]
    evidence = {'required': True, 'status': 'confirmed',
                'stationaryJoints': ['left_knee', 'right_knee'],
                '_floorMaterialContacts': ['left_knee', 'right_knee'],
                '_renderFloorY': float(points[0, names.index('left_knee'), 1] - .03),
                '_materialLoopable': True, '_materialReferencePoints': points,
                '_materialLegSides': material_leg_sides(frames, loopable=True),
                '_materialBodyAxes': material_body_axes(points, names),
                '_materialSegmentLengths': {side: [.4, .4] for side in ('left', 'right')}}
    cursors = np.arange(28) / 4.
    constraint = MaterialFloorConstraint(rig, evidence, cursors=cursors)
    sampled = sample_rig(_sampling_payload(rig, coordinates), cursors, wrap=True)
    expected = np.stack([
        _floor_material_region(sampled, names, {**evidence, '_materialFinalValidation': True},
                               side + '_knee', cursors)[:, :, 1].min(axis=1) - evidence['_renderFloorY']
        for side in ('left', 'right')], axis=1)
    np.testing.assert_allclose(constraint.residual(coordinates, bounded=False), expected.ravel(), atol=1e-12)
    jacobian = constraint.jacobian(coordinates, bounded=False)
    columns = [rig.slots[names.index('left_knee')] + 2, 1,
               3 * rig.width + rig.slots[names.index('pelvis')] + 1]
    step = 2e-7
    finite = []
    for column in columns:
        plus, minus = coordinates.copy(), coordinates.copy()
        plus.ravel()[column] += step
        minus.ravel()[column] -= step
        finite.append((constraint.residual(plus, bounded=False) - constraint.residual(minus, bounded=False)) / (2 * step))
    np.testing.assert_allclose(jacobian[:, columns].toarray(), np.asarray(finite).T, atol=2e-7, rtol=2e-5)
    # This sample's four-frame interpolation/body window excludes stored frame zero.
    assert abs(jacobian[2 * 17, columns[0]]) > 1e-8
    local = copy(rig)
    local.initial = coordinates[:1].copy()
    local_constraint = MaterialFloorConstraint(
        local, evidence, frame_positions=np.array([0]), cursors=np.arange(7))
    local_jacobian = local_constraint.jacobian(local.initial, bounded=False)
    plus, minus = local.initial.copy(), local.initial.copy()
    plus[0, columns[0]] += step
    minus[0, columns[0]] -= step
    finite_local = (local_constraint.residual(plus, bounded=False)
                    - local_constraint.residual(minus, bounded=False)) / (2 * step)
    np.testing.assert_allclose(local_jacobian[:, columns[0]].toarray().ravel(),
                               finite_local, atol=2e-7, rtol=2e-5)
    assert np.any(abs(local_jacobian[6:, columns[0]].toarray()) > 1e-8)
    np.testing.assert_array_equal(local_constraint.context, points)
    # Reach the real local-plus-global-tail assembly without a trajectory fit.
    from exercise_motion_pkg.support_geometry import initialize_supported_motion
    rig.initial[:] = coordinates
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, [names.index('left_knee'), names.index('right_knee')]] = True
    result = initialize_supported_motion(
        rig, points, evidence, points[0], {}, monotonic() + 10.,
        pinned=pinned, contact_targets=points, max_evaluations=1)
    assert result.shape == points.shape and np.isfinite(result).all()
    from exercise_motion_pkg.support_geometry import calibrate_support_pose
    def one_static_evaluation(residual, initial, **options):
        errors = residual(initial)
        derivative = options['jac'](initial)
        assert derivative.shape == (len(errors), len(initial))
        assert np.isfinite(derivative.data).all()
        return SimpleNamespace(x=initial, nfev=1, status=1, cost=float(errors @ errors) / 2.)
    monkeypatch.setattr('scipy.optimize.least_squares', one_static_evaluation)
    _, calibration = calibrate_support_pose(rig, points, evidence)
    assert calibration['evaluations'] == 1
