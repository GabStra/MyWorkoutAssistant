from dataclasses import replace

import numpy as np

from exercise_motion_pkg import structural_refinement as refinement
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.pose_fidelity import registered_camera_pose_fidelity_metrics


def test_reconstruction_camera_inverts_recorded_transforms_and_keeps_pose_errors():
    from scipy.spatial.transform import Rotation

    joints = {
        'left_shoulder': (-.2, -.8, .1), 'right_shoulder': (.2, -.8, .05),
        'left_hip': (-.15, -.4, 0.), 'right_hip': (.15, -.4, .03),
        'left_knee': (-.15, -.1, .1), 'right_knee': (.15, -.1, .1),
        'left_ankle': (-.15, .3, .1), 'right_ankle': (.15, .3, .1),
        'left_elbow': (-.3, -.6, .1), 'right_elbow': (.3, -.6, .1),
        'left_wrist': (-.4, -.4, .1), 'right_wrist': (.4, -.4, .1),
    }
    alignment = Rotation.from_euler('xy', [25., 40.], degrees=True).as_matrix()
    transform = np.diag([1., -1., -1.]) @ alignment @ Rotation.from_euler('z', 30., degrees=True).as_matrix()
    clip = MotionClip(10., list(joints), [MotionFrame(i / 10., {
        n: tuple(transform @ p + [2., 3., 4.]) for n, p in joints.items()
    }) for i in range(6)], source={'extractor': 'WHAM', 'outputRotationDegrees': 30.},
        metadata={'wham': {'coordinateSpace': 'camera'},
                  'videoWorldAlignment': {'applied': True, 'rotationMatrix': alignment.tolist()},
                  'coordinateNormalization': {'transform': 'rotate_x_180_degrees'}})
    source = {'frames': [{'sourceTimeSec': f.time_sec,
                         'joints': {n: list(p[:2]) for n, p in joints.items()}}
                        for f in clip.frames]}

    def evaluate(output):
        retained = refinement.retain_camera_through_cleanup(clip, output, source)
        assert retained.metadata['sourcePoseRegistration']['camera'][
            'cameraOrientationAuthority'] == 'reconstruction_camera_coordinates'
        return registered_camera_pose_fidelity_metrics(source, refinement._motion_clip_pose_payload(retained))

    assert evaluate(clip)['p90JointErrorBodyRatio'] < 1e-8
    damaged = replace(clip, frames=[MotionFrame(f.time_sec, {
        n: tuple(np.asarray(p) + transform @ [0., .5, 0.]) if n == 'left_wrist' else p
        for n, p in f.joints.items()
    }) for f in clip.frames])
    assert evaluate(damaged)['perJointMedianErrorBodyRatio']['left_wrist'] > .2
    drifting = replace(clip, frames=[MotionFrame(f.time_sec, {
        n: tuple(np.asarray(p) + transform @ [0., i * .1, 0.]) for n, p in f.joints.items()
    }) for i, f in enumerate(clip.frames)])
    assert evaluate(drifting)['p90JointErrorBodyRatio'] > .05
    assert refinement.reconstruction_camera_orientation(replace(clip, source={})) is None
    malformed = replace(clip, metadata={**clip.metadata, 'videoWorldAlignment': {
        'applied': True, 'rotationMatrix': (np.eye(3) * 2.).tolist()}})
    assert refinement.reconstruction_camera_orientation(malformed) is None


def test_cleanup_camera_tracks_rigid_placement_but_exposes_pose_and_root_errors(monkeypatch):
    joints = {
        'left_shoulder': (-.2, .8, .1), 'right_shoulder': (.2, .8, .05),
        'left_hip': (-.15, .4, 0.), 'right_hip': (.15, .4, .03),
        'left_knee': (-.15, .1, .1), 'right_knee': (.15, .1, .1),
        'left_ankle': (-.15, -.3, .1), 'right_ankle': (.15, -.3, .1),
        'left_elbow': (-.3, .6, .1), 'right_elbow': (.3, .6, .1),
        'left_wrist': (-.4, .4, .1), 'right_wrist': (.4, .4, .1),
    }
    before = MotionClip(10., list(joints), [MotionFrame(i / 10., dict(joints)) for i in range(6)])
    source = {'frames': [{'sourceTimeSec': f.time_sec,
                         'joints': {n: list(p[:2]) for n, p in f.joints.items()}}
                        for f in before.frames]}
    camera = {'available': True, 'cameraRotation': np.eye(3).tolist(),
              'cameraImageTransform': [1., 0., 0., 0., 0., 0.], 'bilateralAssignment': 'identity'}
    monkeypatch.setattr(refinement, 'registered_camera_pose_fidelity_metrics',
                        lambda *args, **kwargs: camera)
    rotation = np.array([[0., 0., 1.], [0., 1., 0.], [-1., 0., 0.]])
    after = replace(before, frames=[MotionFrame(f.time_sec, {
        n: tuple(np.asarray(p) @ rotation + [2., 3., 4.]) for n, p in f.joints.items()
    }) for f in before.frames])

    def evaluate(clip):
        mapped = refinement.retain_camera_through_cleanup(before, clip, source)
        assert 'sourcePoseRegistration' in mapped.metadata
        return registered_camera_pose_fidelity_metrics(source, refinement._motion_clip_pose_payload(mapped))

    assert evaluate(after)['p90JointErrorBodyRatio'] < 1e-8
    drifting = replace(after, frames=[MotionFrame(f.time_sec, {
        n: (p[0], p[1] + i * .1, p[2]) for n, p in f.joints.items()
    }) for i, f in enumerate(after.frames)])
    assert evaluate(drifting)['p90JointErrorBodyRatio'] > .05
    damaged = replace(after, frames=[MotionFrame(f.time_sec, {
        n: (p[0], p[1] + .5, p[2]) if n == 'left_wrist' else p
        for n, p in f.joints.items()
    }) for f in after.frames])
    assert evaluate(damaged)['perJointMedianErrorBodyRatio']['left_wrist'] > .2
    changed_core = replace(after, frames=[MotionFrame(f.time_sec, {
        n: (p[0], p[1] + .1, p[2]) if n == 'left_shoulder' else p
        for n, p in f.joints.items()
    }) for f in after.frames])
    assert refinement.retain_camera_through_cleanup(before, changed_core, source) is changed_core
