import json
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import numpy as np

from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.support_geometry import calibrate_support_pose


def test_static_calibration_continues_same_prior_and_honors_expired_deadline(monkeypatch):
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.asarray([[fixture['joints'][name] for name in names]])
    rig = FixedRig(points, names)
    points = rig.decode(rig.initial)
    initial = rig.initial[0].copy()
    evidence = {'required': True, 'status': 'confirmed', 'stationaryJoints': ['left_knee'],
                'coplanarGroups': [{'joints': ['left_knee'], 'normal': [0., 1., 0.],
                                    'planeOffsetMeters': float(points[0, names.index('left_knee'), 1] + .006)}]}
    starts = []

    def incomplete_solve(residual, start, **kwargs):
        starts.append(start.copy())
        proposal = start.copy()
        proposal[1] += .002
        errors = residual(proposal)
        np.testing.assert_allclose(errors[-rig.width:], .001 * (proposal - initial), atol=1e-12)
        return SimpleNamespace(x=proposal, nfev=40, status=0, cost=float(errors @ errors) / 2.)

    monkeypatch.setattr('scipy.optimize.least_squares', incomplete_solve)
    pose, report = calibrate_support_pose(rig, points, evidence, deadline=monotonic() + 30.)
    assert pose is not None and report['passed']
    assert len(starts) == 2 and report['continuations'] == 1
    assert report['surfaceErrorMeters'] < .0025
    assert starts[1][1] == starts[0][1] + .002
    np.testing.assert_array_equal(report['referenceCoordinates'], initial)

    pose, report = calibrate_support_pose(rig, points, evidence, deadline=monotonic() - 1.)
    assert pose is None and not report['passed']
    assert report['stopReason'] == 'deadline' and report['evaluations'] == 0
    assert len(starts) == 2  # No optimizer or objective work after the deadline.


def test_static_calibration_preserves_stationary_tangents_on_rotated_plane(monkeypatch):
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    rig = FixedRig(np.asarray([[fixture['joints'][name] for name in names]]), names)
    points = rig.decode(rig.initial)
    normal = np.array([1., 1., 0.]) / np.sqrt(2.)
    tangent = np.array([1., -1., 0.]) / np.sqrt(2.)
    index = names.index('left_knee')
    evidence = {'required': True, 'status': 'confirmed', 'stationaryJoints': ['left_knee'],
                'coplanarGroups': [{'joints': ['left_knee'], 'normal': normal.tolist(),
                                    'planeOffsetMeters': float(points[0, index] @ normal)}]}

    def displaced_solve(residual, start, **kwargs):
        proposal = start.copy()
        proposal[:3] += .02 * tangent
        errors = residual(proposal)
        return SimpleNamespace(x=proposal, nfev=1, status=1, cost=float(errors @ errors) / 2.)

    monkeypatch.setattr('scipy.optimize.least_squares', displaced_solve)
    pose, report = calibrate_support_pose(rig, points, evidence)
    assert pose is None and not report['passed']
    assert report['surfaceErrorMeters'] < 1e-12
    assert report['stationaryTangentErrorMeters'] == __import__('pytest').approx(.02)
