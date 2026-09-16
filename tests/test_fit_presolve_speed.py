"""Pre-solve anatomy/support stages must not consume the whole fit budget."""
from copy import deepcopy
from time import monotonic

import numpy as np

from exercise_motion_pkg import anatomical_repair
from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.anatomical_repair import (
    ANATOMY_REPAIR_MAX_TOTAL_EVALS,
    repair_rig_anatomy,
)
from exercise_motion_pkg.controlled_motion import FixedRig


def _stance_points():
    import json
    from pathlib import Path
    fixture = json.loads(
        (Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text()
    )
    names = list(fixture['joints'])
    points = np.tile(np.array(list(fixture['joints'].values())), (12, 1, 1))
    return names, points


def test_anatomical_repair_stops_at_total_evaluation_budget(monkeypatch):
    names, points = _stance_points()
    axis = points[0, names.index('neck')] - points[0, names.index('pelvis')]
    lateral = points[0, names.index('right_hip')] - points[0, names.index('left_hip')]
    forward = np.cross(axis, lateral)
    forward /= np.linalg.norm(forward)
    # Corrupt many frames so repair would otherwise burn unbounded evals.
    for index in range(len(points)):
        points[index, names.index('spine1')] += forward * (0.12 + 0.01 * (index % 3))
    rig = FixedRig(points, names)
    original = anatomical_repair.least_squares
    calls = []

    def counting_least_squares(*args, **kwargs):
        calls.append(kwargs.get('max_nfev'))
        return original(*args, **kwargs)

    monkeypatch.setattr(anatomical_repair, 'least_squares', counting_least_squares)
    _, report = repair_rig_anatomy(rig, points, deadline=monotonic() + 60.)
    assert report['evaluations'] <= ANATOMY_REPAIR_MAX_TOTAL_EVALS
    assert report.get('evaluationBudget') == ANATOMY_REPAIR_MAX_TOTAL_EVALS
    assert calls
    assert max(calls) <= anatomical_repair.ANATOMY_REPAIR_MAX_EVALS_PER_FRAME
    # Pathological unbounded runs were 700–1350; the ceiling must stay below that
    # while still allowing hard multi-frame repairs.
    assert ANATOMY_REPAIR_MAX_TOTAL_EVALS >= 400
    assert ANATOMY_REPAIR_MAX_TOTAL_EVALS < 700
    # Soft polishing must not consume the whole ceiling once frames are repairable.
    assert report['evaluations'] < ANATOMY_REPAIR_MAX_TOTAL_EVALS // 2


def test_anatomical_repair_exits_once_geometry_and_lean_are_feasible():
    names, points = _stance_points()
    axis = points[0, names.index('neck')] - points[0, names.index('pelvis')]
    lateral = points[0, names.index('right_hip')] - points[0, names.index('left_hip')]
    forward = np.cross(axis, lateral)
    forward /= np.linalg.norm(forward)
    for index in range(len(points)):
        points[index, names.index('spine1')] += forward * (0.12 + 0.005 * (index % 5))
    rig = FixedRig(points, names)
    _, report = repair_rig_anatomy(rig, points, deadline=monotonic() + 60.)
    assert report['passed'], report
    assert report['maximumTorsoDirectionChangeDegrees'] < 0.01
    # Soft polishing used to burn hundreds of evals after bounds were already met.
    assert report['evaluations'] < 200
    assert report['warmStartedFrameCount'] >= 1
    # Spine repairs should not FD every limb rotation.
    assert report['averageFreeColumnCount'] < rig.width - 3


def test_observed_cycles_reuse_support_init_across_attempts(monkeypatch):
    shared_seen = []

    def fake_fit(payload, **kwargs):
        shared = kwargs.get('shared_support')
        shared_seen.append(shared)
        assert isinstance(shared, dict)
        if 'supportKey' not in shared:
            shared['supportKey'] = ('left_foot',)
            shared['supportPose'] = np.zeros(3)
            shared['supportCalibration'] = {'passed': True}
            shared['supportInitializedCoordinates'] = np.zeros((10, 9))
            return payload, {
                'applied': False,
                'reason': 'fit_validation_failed',
                'checks': {'trajectoryFit': True, 'rootTravel': True, 'loopSeam': False},
                'elapsedSeconds': 1.,
                'supportCalibration': {'reusedAcrossCycles': False},
            }
        assert shared.get('supportKey') == ('left_foot',)
        return payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {
                'trajectoryFit': False,
                'rootTravel': False,
            },
            'elapsedSeconds': 1.,
            'supportCalibration': {'reusedAcrossCycles': True},
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fake_fit)
    import exercise_motion_pkg.loop_cycles as loop_cycles
    monkeypatch.setattr(loop_cycles, 'rank_loop_cycles', lambda payload, max_candidates=3: [
        {'start': 0, 'end': 10}, {'start': 5, 'end': 15}])
    monkeypatch.setattr(
        loop_cycles, 'slice_loop_cycle',
        lambda payload, choice: {**payload, 'loopCycleSelection': choice})
    monkeypatch.setattr(motion, 'monotonic', lambda: 0.)
    monkeypatch.setattr(motion, 'fit_time_budget', lambda payload, timeout=None: 100. if timeout is None else timeout)
    payload = {'frames': [None] * 60, 'loop': {'enabled': True}}
    _, report = motion._fit_observed_cycles(payload, timeout_seconds=100.)
    assert len(shared_seen) >= 2
    assert shared_seen[0] is shared_seen[1]
    assert report['reason'] == 'no_validated_loop_cycle'
