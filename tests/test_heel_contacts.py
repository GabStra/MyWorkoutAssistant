import copy
import json
from types import SimpleNamespace

import numpy as np

from exercise_motion_pkg.foot_kinematics import HEEL_BEHIND_ANKLE_RATIO
from exercise_motion_pkg.heel_contacts import heel_contact_tracks


def test_fresh_support_receives_ground_plane_without_parent_depth_timing(tmp_path, monkeypatch):
    from exercise_motion_pkg import bake_and_rank as bake
    raw_dir = tmp_path / 'raw'
    raw_dir.mkdir()
    normal = [0., -0.95, -0.31]
    (raw_dir / 'motion.raw.json').write_text(json.dumps({'metadata': {'videoWorldAlignment': {
        'cameraGroundPlane': {'normal': normal},
        'videoFloorDistanceObservations': {'left_ankle': [99.]},
    }}}))
    child_video = tmp_path / 'child.mp4'
    child_video.touch()
    fresh = {'contacts': [{'jointName': 'left_hand'}]}
    pose = {'frames': []}
    observations = {'source': 'observed-child'}
    monkeypatch.setattr(bake, 'observe_foot_landmarks', lambda path: observations if path == child_video else None)
    def classify(evidence, observed, reference, camera_normal, depth_alignment=None):
        assert evidence is fresh and observed is observations and reference is pose
        assert camera_normal == normal and depth_alignment is None
        return {**evidence, 'groundReferenced': True}
    monkeypatch.setattr(bake, 'add_observed_foot_contacts', classify)
    result, source = bake.authoritative_source_foot_support_evidence(
        SimpleNamespace(candidate_workspace=tmp_path),
        {'sourceFootSupportEvidence': fresh, 'sourceVideoPath': str(child_video), '_sourcePoseReference': pose})
    assert result['groundReferenced'] and result['contacts'] == fresh['contacts']
    assert source == 'exact_selected_source_video'
    assert 'groundReferenced' not in fresh


def evidence(end=1.):
    return {'contacts': [{'jointName': 'left_foot', 'contactState': 'heel_only',
                         'contactMotion': 'stationary', 'surfaceKind': 'ground',
                         'startRatio': 0., 'endRatio': end}]}


def test_material_heel_anchor_allows_toe_rotation_and_releases_contact():
    angle = np.linspace(.2, .6, 8)
    foot = .2 * np.stack([np.cos(angle), np.sin(angle), np.zeros(8)], axis=1)
    ankles = HEEL_BEHIND_ANKLE_RATIO * foot
    points = np.stack([ankles, ankles + foot], axis=1)
    tracks = heel_contact_tracks(points, ['left_ankle', 'left_foot'], evidence(.5), floor=0.)
    np.testing.assert_allclose(tracks.residual(points), 0., atol=1e-15)
    shifted = points + [.01, 0., 0.]
    errors = tracks.residual(shifted)
    np.testing.assert_allclose(errors[:5, 0, 0], .01)
    np.testing.assert_array_equal(errors[5:], 0.)


def test_fitter_and_playback_enforce_heel_support():
    from test_controlled_motion_pipeline import accepted_payload
    from exercise_motion_pkg.controlled_motion import fit_controlled_motion
    from exercise_motion_pkg.rig_playback import validate_rig_playback, decode_rig

    original = accepted_payload()
    original.pop('controlledMotionFit')
    original.pop('fixedRig')
    original['sourceFootSupportEvidence'] = evidence()
    result, report = fit_controlled_motion(original, max_evaluations=2, timeout_seconds=10.)
    assert report['applied'], report
    valid = validate_rig_playback(result)
    assert valid['passed'], valid
    assert valid['maximumHeelContactErrorMeters'] < .0005
    moved = copy.deepcopy(result)
    coordinates = np.asarray(moved['fixedRig']['coordinates'])
    coordinates[:, 0] += .01
    moved['fixedRig']['coordinates'] = coordinates.tolist()
    poses = decode_rig(moved['fixedRig'], coordinates)
    for frame, pose in zip(moved['frames'], poses):
        frame['joints'] = dict(zip(moved['jointNames'], pose.tolist()))
    rejected = validate_rig_playback(moved)
    assert not rejected['passed']
    assert rejected['maximumHeelContactErrorMeters'] >= .0099
