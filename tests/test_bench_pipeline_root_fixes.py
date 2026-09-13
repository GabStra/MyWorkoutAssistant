import copy
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.pose_fidelity import registered_camera_pose_fidelity_metrics
from exercise_motion_pkg.temporal_quality import track_discontinuity_metrics
from exercise_motion_pkg.loop_cycles import rank_loop_cycles
from exercise_motion_pkg.structural_refinement import preserve_terminal_bone_lengths
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg import structural_refinement as refinement


def motion_fixture():
    joints = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())['joints']
    frames = []
    for i in range(20):
        points = copy.deepcopy(joints)
        points['left_wrist'][0] += .15*np.sin(i/19*np.pi)
        frames.append({'timeSec': i/30, 'joints': points})
    return {'fps': 30., 'jointNames': list(joints), 'frames': frames}


def test_camera_registration_is_invariant_to_rigid_scene_rotation():
    motion = motion_fixture()
    camera = Rotation.from_euler('xyz', [23., 37., -18.], degrees=True)
    source = {'frames': [{'sourceTimeSec': f['timeSec'], 'joints':
              {n: (camera.apply(p)[:2]*.4+[.3, .6]).tolist() for n, p in f['joints'].items()}}
              for f in motion['frames']]}
    for angles in ([0, 0, 0], [45, 70, -12], [-32, 10, 90]):
        rotated = copy.deepcopy(motion)
        rotation = Rotation.from_euler('xyz', angles, degrees=True)
        for frame in rotated['frames']:
            frame['joints'] = {n: (rotation.apply(p)+[1, 2, 3]).tolist() for n, p in frame['joints'].items()}
        metrics = registered_camera_pose_fidelity_metrics(source, rotated)
        assert metrics['p90JointErrorBodyRatio'] < 1e-5
    damaged = copy.deepcopy(motion)
    for frame in damaged['frames']:
        frame['joints']['left_wrist'][0] += .5
    metrics = registered_camera_pose_fidelity_metrics(source, damaged)
    assert metrics['perJointMedianErrorBodyRatio']['left_wrist'] > .1


def test_source_correction_uses_elevated_camera_and_preserves_world_anchors():
    motion = motion_fixture()
    camera = Rotation.from_euler('xyz', [25., 35., -10.], degrees=True)
    target = copy.deepcopy(motion)
    rotation = Rotation.from_euler('z', 18., degrees=True)
    for frame in target['frames']:
        shoulder = np.asarray(frame['joints']['left_shoulder'])
        for name in ('left_elbow', 'left_wrist', 'left_hand'):
            frame['joints'][name] = (shoulder+rotation.apply(np.asarray(frame['joints'][name])-shoulder)).tolist()
    source = {'frames': [{'sourceTimeSec': f['timeSec'], 'joints':
              {n: (camera.apply(p)[:2]*.4+[.3, .6]).tolist() for n, p in f['joints'].items()}}
              for f in target['frames']]}
    clip = MotionClip(30., motion['jointNames'], [MotionFrame(f['timeSec'],
        {name: tuple(p) for name, p in f['joints'].items()}) for f in motion['frames']])
    result, report = refinement._align_hinge_articulation_to_source_pose(clip,
        source_pose_payload=source, chains=refinement.SOURCE_GUIDED_ARM_CHAINS)
    assert report['applied'] and report['cameraRegistration']['cameraModel'] == 'fixed_scaled_orthographic'
    before = registered_camera_pose_fidelity_metrics(source, motion)
    after = registered_camera_pose_fidelity_metrics(source, refinement._motion_clip_pose_payload(result), camera_reference=before)
    assert after['perJointMedianErrorBodyRatio']['left_wrist'] < before['perJointMedianErrorBodyRatio']['left_wrist']*.7
    for old, new in zip(clip.frames, result.frames):
        for name in ('pelvis', 'left_foot', 'right_foot'):
            np.testing.assert_allclose(old.joints[name], new.joints[name], atol=1e-10)


@pytest.mark.parametrize('fps', [15., 30., 60.])
@pytest.mark.parametrize('jump', [False, True])
def test_temporal_gate_separates_fast_smooth_motion_from_jump_at_each_rate(fps, jump):
    times = np.arange(int(fps*2)+1)/fps
    x = .4*np.tanh((times-1)*8)
    if jump:
        x += .35*(times >= 1)
    tracks = {'pelvis': np.zeros((len(x), 3)).tolist(),
              'left_hand': np.c_[x, np.ones(len(x)), np.zeros(len(x))].tolist()}
    result = track_discontinuity_metrics(tracks, root_joint='pelvis', fps=fps, body_height=1.8)
    assert result['severe'] is jump


def test_terminal_bones_use_current_edits_despite_initial_noop_metadata():
    payload = motion_fixture()
    frames = [MotionFrame(f['timeSec'], {n: tuple(p) for n, p in f['joints'].items()}) for f in payload['frames']]
    original = MotionClip(30., payload['jointNames'], frames)
    changed = copy.deepcopy(original)
    for frame in changed.frames:
        frame.joints['left_hand'] = tuple(np.array(frame.joints['left_wrist'])+[.3, 0, 0])
    result, report = preserve_terminal_bone_lengths(changed, original)
    assert report.get('reason') != 'source_preserving_refinement_changed_no_joints'
    assert report['applied']
    lengths = [np.linalg.norm(np.array(f.joints['left_hand'])-f.joints['left_wrist']) for f in result.frames]
    assert max(lengths)-min(lengths) < 1e-6


def test_cycle_diagnostics_remain_available_when_geometry_proposals_fail():
    payload = motion_fixture()
    for i, frame in enumerate(payload['frames']):
        for point in frame['joints'].values():
            point[0] += i*.1
    diagnostics = {}
    assert not rank_loop_cycles(payload, endpoint_correction_ratio=.06, diagnostics=diagnostics)
    assert diagnostics['counts']['intervalPairs'] > 0
    assert diagnostics['counts']['endpointFeasible'] == 0
