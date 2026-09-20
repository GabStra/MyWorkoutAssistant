from types import SimpleNamespace

import numpy as np
import pytest

from exercise_motion_pkg import video_world_alignment as alignment
from exercise_motion_pkg.ground import PlaneEstimate
from exercise_motion_pkg.models import MotionClip, MotionFrame


@pytest.mark.parametrize('source_upright, pitch, applied', [
    (1., 75., False), (1., 0., True), (.3, 20., True),
])
def test_rejected_body_fit_cannot_bypass_source_check_via_floor(
        tmp_path, monkeypatch, source_upright, pitch, applied):
    joints = {'pelvis': (0., 0., 3.), 'left_shoulder': (-.2, -1., 3.),
              'right_shoulder': (.2, -1., 3.), 'left_ankle': (-.1, 1., 3.),
              'right_ankle': (.1, 1., 3.)}
    clip = MotionClip(30., list(joints), [MotionFrame(i / 30, joints.copy()) for i in range(5)])
    video = tmp_path / 'source.mp4'
    video.touch()
    angle = np.radians(pitch)
    plane = PlaneEstimate((0., -float(np.cos(angle)), float(np.sin(angle))), 0., .01)
    distances = {name: [1. if 'shoulder' in name else .5 if name == 'pelvis' else 0.]
                 for name in joints}
    monkeypatch.setattr(alignment, 'is_unidepth_runtime_available', lambda: True)
    monkeypatch.setattr(alignment, 'video_world_alignment_enabled', lambda: True)
    monkeypatch.setattr(alignment, 'infer_depth_samples_for_video', lambda **kw: [
        SimpleNamespace(time_seconds=0., model_name='retained')])
    monkeypatch.setattr(alignment, 'estimate_camera_floor_plane', lambda *a, **kw: plane)
    monkeypatch.setattr(alignment, '_collect_video_floor_distance_samples', lambda *a, **kw: distances)
    monkeypatch.setattr(alignment, '_collect_video_floor_distance_observations', lambda *a, **kw: {})
    monkeypatch.setattr(alignment, 'solve_floor_distance_rigid_transform',
                        lambda *a, **kw: (np.eye(3), np.zeros(3), .01))
    monkeypatch.setattr(alignment, 'body_fit_projection_metrics', lambda *a: {'regressed': True})
    monkeypatch.setattr(alignment, 'source_pose_uprightness_score', lambda _: source_upright)
    result = alignment.align_motion_clip_to_video(
        clip, video_path=video, source_pose_payload={'frames': []}, support_mode_hint='upright')
    assert result.applied is applied
    if not applied:
        assert result.clip is clip
        assert result.metadata['rejectedTransform']
        assert result.metadata['floorOnlyUprightnessRegressed']
    else:
        assert result.metadata['rejectedBodyFit']


def test_invalid_depth_retains_reconstruction_without_claiming_floor(tmp_path, monkeypatch):
    from exercise_motion_pkg.unidepth_runner import _depth_predictions_to_arrays
    clip = MotionClip(30., ['pelvis'], [MotionFrame(0., {'pelvis': (0., 0., 3.)})])
    video = tmp_path / 'source.mp4'
    video.touch()
    monkeypatch.setattr(alignment, 'is_unidepth_runtime_available', lambda: True)
    monkeypatch.setattr(alignment, 'video_world_alignment_enabled', lambda: True)
    monkeypatch.setattr(alignment, 'infer_depth_samples_for_video', lambda **kw:
        _depth_predictions_to_arrays({'depth': np.ones(360),
            'points': np.ones((3, 360, 640)), 'intrinsics': np.eye(3)}))
    result = alignment.align_motion_clip_to_video(
        clip, video_path=video, source_pose_payload={'frames': []})
    assert result.clip is clip
    assert not result.applied
    assert result.camera_ground_plane is None
    assert result.reason == 'unidepth_prediction_invalid'
    assert '(360,)' in result.metadata['error']
