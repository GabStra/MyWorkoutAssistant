import numpy as np
import pytest

from exercise_motion_pkg.controlled_motion import native_material_contact_domain, _sampling_payload
from exercise_motion_pkg.native_material_frames import freeze_material_frames, material_axes
from exercise_motion_pkg.rig_playback import sample_rig_coordinates
from test_native_contact_reach import _fixture


@pytest.mark.parametrize('mode', ['stationary', 'verticalOnly'])
def test_native_admission_uses_typed_material_domain(mode):
    rig, tracks = _fixture(mode, correction=0.)
    points = rig.decode(rig.initial)
    axes = {'left': np.tile([1., 0., 0.], (5, 1)),
            'right': np.tile([1., 0., 0.], (5, 1))}
    rig.material_frames = freeze_material_frames(rig, tracks, axes)
    payload = _sampling_payload(rig, rig.initial)
    cursors = np.arange(.25, 4., .25)
    cursors = cursors[cursors % 1 != 0]
    dense_q = sample_rig_coordinates(payload, cursors, wrap=False)
    key_axes = material_axes(payload, np.arange(5))
    dense_axes = material_axes(payload, cursors, coordinates=dense_q)
    def measure():
        return native_material_contact_domain(
            points, rig.decode(dense_q), rig.names, rig.offsets, tracks, cursors,
            cyclic=False, key_side_axes=key_axes, dense_side_axes=dense_axes,
            native_geometry=rig.native_foot_geometry_for_sampling,
            foot_scale=rig.native_foot_scale_for_sampling)
    active, metrics, required, verdict = measure()
    assert active and verdict['passed']
    assert metrics['keyframe' + ('Stationary' if mode == 'stationary' else 'Height') + 'SampleCount'] == 5
    # The joint pose, FK axes, reach and endpoint-target errors are unchanged;
    # changing the physical support target must nevertheless reject admission.
    episode = tracks['right']['episodes'][0]
    if mode == 'stationary':
        episode['targetWorld'][1] -= .004
    else:
        episode['planeOffsetMeters'] -= .004
    _, metrics, _, verdict = measure()
    assert not verdict['passed']
    assert metrics['maximumErrorMeters'] >= .003999
    assert any(c['applicable'] and not c['passed'] for c in verdict['components'])


def test_native_admission_absent_tracks_preserves_legacy():
    _, _, _, verdict = native_material_contact_domain(
        np.zeros((2, 1, 3)), np.zeros((1, 1, 3)), ['root'], np.zeros((1, 3)),
        None, [.5], cyclic=False, key_side_axes=None, dense_side_axes=None,
        native_geometry=None, foot_scale=None)
    assert verdict['passed'] and not verdict['available']
