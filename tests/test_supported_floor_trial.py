import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg import rig_playback
from exercise_motion_pkg.contact_interpolation import ContactFootIKUnreachable


@pytest.mark.parametrize('failure', ['trial', 'baseline', None])
def test_optional_floor_trial_keeps_baseline_on_unreachable_material(monkeypatch, failure):
    fixture = json.loads((Path(__file__).parent / 'fixtures' /
                          'sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    rig = motion.FixedRig(np.tile([fixture['joints'][n] for n in names], (3, 1, 1)), names)
    baseline = rig.initial.copy()
    points = rig.decode(baseline)
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, names.index('right_foot')] = True
    reference = {'jointNames': names, 'frames': [
        {'joints': dict(zip(names, row.tolist()))} for row in points]}
    trial = baseline.copy()
    # A small projected adjustment stays within the existing plant tolerance.
    trial[:, 0] += .0001
    calls = []
    error = ContactFootIKUnreachable('right', [0], [[0., 0., 0.]],
                                    [[0., 2., 0.]], [0.], [1.], [2.])

    def material_lift(payload, mask, *, cyclic):
        is_baseline = np.array_equal(payload['fixedRig']['coordinates'], baseline)
        calls.append(is_baseline)
        if failure == 'baseline' or (failure == 'trial' and not is_baseline):
            raise error
        return .005 if is_baseline else 0.

    monkeypatch.setattr(rig_playback, 'free_material_floor_clearance_lift', material_lift)
    monkeypatch.setattr(rig_playback, 'free_joint_floor_clearance_lift', lambda *a, **k: 0.)
    monkeypatch.setattr(motion, 'project_contact_plant_coordinates', lambda *a, **k: trial.copy())

    if failure == 'baseline':
        with pytest.raises(ContactFootIKUnreachable) as raised:
            motion.apply_supported_floor_clearance(
                baseline, rig, pinned, points, 0., material_reference=reference)
        assert raised.value is error
        assert calls == [True]
    else:
        result, lift = motion.apply_supported_floor_clearance(
            baseline, rig, pinned, points, 0., material_reference=reference)
        np.testing.assert_array_equal(result, baseline if failure else trial)
        assert lift == (0. if failure else .005)
        assert calls == ([True, False, False] if failure else [True, False])
    np.testing.assert_array_equal(rig.initial, baseline)
