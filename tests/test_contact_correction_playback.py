import copy

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg import bake_and_rank
from exercise_motion_pkg.rig_playback import sample_rig
from test_controlled_motion_pipeline import accepted_payload


@pytest.mark.parametrize('yaw_step,broken_rig', [(0., False), (.015, False), (0., True)])
def test_contact_correction_updates_the_played_rig(yaw_step, broken_rig):
    payload = accepted_payload()
    payload['loop']['enabled'] = True
    names = payload['jointNames']
    coordinates = np.asarray(payload['fixedRig']['coordinates'])
    root_slot = 3 + 3 * payload['fixedRig']['rotationJointNames'].index('pelvis')
    for index, frame in enumerate(payload['frames']):
        rotation = Rotation.from_rotvec([0., index * yaw_step, 0.])
        shift = np.array([index * .01, 0., 0.])
        points = rotation.apply(np.asarray([frame['joints'][name] for name in names])) + shift
        frame['joints'] = dict(zip(names, points.tolist()))
        coordinates[index, :3] = frame['joints']['pelvis']
        coordinates[index, root_slot:root_slot + 3] = (
            rotation * Rotation.from_rotvec(coordinates[index, root_slot:root_slot + 3])
        ).as_rotvec()
    payload['fixedRig']['coordinates'] = coordinates.tolist()
    if broken_rig:
        payload['fixedRig']['coordinates'] = []
    before = copy.deepcopy(payload)
    evidence = {'contacts': [
        {'jointName': side + '_foot', 'startFrame': 0, 'endFrame': len(payload['frames']) - 1,
         'contactState': 'full_sole', 'contactMotion': 'stationary',
         'supportKind': 'observed_foot_patch', 'surfaceKind': 'ground'}
        for side in ('left', 'right')
    ]}
    corrected, metrics = bake_and_rank.apply_source_contact_sequence_correction(payload, evidence)
    if broken_rig:
        assert not metrics['applied']
        assert metrics['reason'] == 'contact_correction_not_improved'
        assert corrected['frames'] == before['frames']
        assert corrected['fixedRig'] == before['fixedRig']
        assert payload == before
        return
    assert metrics['applied'], metrics
    expected = np.asarray([[frame['joints'][name] for name in names] for frame in corrected['frames']])
    np.testing.assert_allclose(sample_rig(corrected['fixedRig'], np.arange(len(expected))), expected,
                               atol=1e-9)
    assert corrected['loop'] == before['loop']
    assert 'controlledMotionFit' not in corrected
    assert payload == before
    for frame, original in zip(corrected['frames'], before['frames']):
        assert frame['sourceJoints'] == original['sourceJoints']
