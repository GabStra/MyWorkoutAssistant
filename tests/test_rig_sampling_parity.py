import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.rig_playback import decode_rig, sample_rig


def reference_sample(rig, cursors, wrap):
    values = np.asarray(rig['coordinates'])
    cursors = np.mod(cursors, len(values)) if wrap else np.clip(cursors, 0, len(values)-1)
    first = np.floor(cursors).astype(int)
    last = (first+1) % len(values) if wrap else np.minimum(first+1, len(values)-1)
    alpha = cursors-first
    a, b = values[first], values[last]
    left = Rotation.from_rotvec(a[:,3:].reshape(-1,3))
    right = Rotation.from_rotvec(b[:,3:].reshape(-1,3))
    amount = np.repeat(alpha, (values.shape[1]-3)//3)
    rotations = (left*Rotation.from_rotvec((left.inv()*right).as_rotvec()*amount[:,None])).as_rotvec()
    return decode_rig(rig, np.column_stack([
        a[:,:3]*(1-alpha[:,None])+b[:,:3]*alpha[:,None], rotations.reshape(len(cursors),-1)]))


@pytest.mark.parametrize('wrap', [False, True])
@pytest.mark.parametrize('variation', [0., 1e-9, .2, 4.])
def test_optimized_sampling_preserves_shortest_rotation_arcs(wrap, variation):
    joints = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())['joints']
    rig = FixedRig(np.tile(np.array(list(joints.values())), (9,1,1)), list(joints))
    rng = np.random.default_rng(120)
    values = rig.initial + variation*rng.normal(size=rig.initial.shape)
    data = {'jointNames':rig.names, 'parents':rig.parents, 'order':rig.order,
            'offsets':rig.offsets, 'rotationJointNames':[rig.names[j] for j in rig.active],
            'coordinates':values}
    cursors = np.arange(-1., 10., .125)
    np.testing.assert_allclose(sample_rig(data, cursors, wrap=wrap),
                               reference_sample(data, cursors, wrap), atol=2e-12, rtol=2e-12)
