from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from exercise_motion_pkg import reconstruction_convert, reconstruction_retarget_source, reconstruction_smpl_preview
from exercise_motion_pkg.pipeline import crop_motion_clip_to_input_window
from exercise_motion_pkg.reconstruction_results import validate_reconstruction_frame_rate


@pytest.mark.parametrize('fps', [24.0, 25.0, 29.97, 30.0])
def test_conversion_and_context_crop_use_input_frame_clock(monkeypatch, fps):
    import torch
    smplx = pytest.importorskip("smplx")

    count = 100
    result = {'pose': np.zeros((count, 72)), 'trans': np.zeros((count, 3)),
              'betas': np.zeros(10), 'frame_ids': np.arange(count)}
    for module in (reconstruction_convert, reconstruction_retarget_source, reconstruction_smpl_preview):
        monkeypatch.setattr(module, 'load_reconstruction_results', lambda path: {0: result})
        monkeypatch.setattr(module, 'select_reconstruction_subject', lambda *args, **kwargs: (0, result))
        monkeypatch.setattr(module, 'resolve_reconstruction_coordinate_keys', lambda space: ('pose', 'trans'))
    joints = torch.zeros((count, 24, 3))
    joints[:, 0, 0] = torch.arange(count)

    class BodyModel:
        faces = np.array([[0, 1, 2]])

        def __call__(self, **kwargs):
            return SimpleNamespace(joints=joints, vertices=joints)

    monkeypatch.setattr(smplx, 'create', lambda **kwargs: BodyModel())
    options = {'reconstruction_results_pkl': Path('unused.pkl'), 'body_model_root': Path('unused'), 'fps': fps}
    clip = reconstruction_convert.convert_reconstruction_results_to_motion_clip(**options)
    assert clip.frames[24].time_sec == pytest.approx(24 / fps)
    assert clip.frames[24].source_time_sec is None
    assert clip.frames[24].source_frame_index is None
    assert clip.frames[24].inference_frame_index is None
    cropped = crop_motion_clip_to_input_window(clip, start_seconds=1, end_seconds=2)
    assert cropped.frames[0].joints['pelvis'][0] == np.ceil(fps)
    assert cropped.frames[-1].joints['pelvis'][0] == np.ceil(2 * fps) - 1
    assert cropped.frames[-1].time_sec < 2
    assert cropped.fps == fps
    retarget = reconstruction_retarget_source.build_reconstruction_retarget_source_payload(reconstruction_results_pkl=Path('unused.pkl'), fps=fps)
    assert retarget['fps'] == fps
    mesh = reconstruction_smpl_preview.load_reconstruction_smpl_mesh_sequence(**options)
    assert mesh.fps == fps


@pytest.mark.parametrize('fps', [0, -1, float('nan'), float('inf')])
def test_invalid_source_clock_is_rejected(fps):
    with pytest.raises(ValueError, match='frame rate'):
        validate_reconstruction_frame_rate(fps)
