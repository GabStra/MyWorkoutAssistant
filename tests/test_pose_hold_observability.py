import pytest

from exercise_motion_pkg.pose_prefilter import (
    PoseDetection, PosePrefilterSettings, PoseSample, score_pose_window,
)
from exercise_motion_pkg.video_utils import BasicVideoMetadata


@pytest.mark.parametrize('completion_mode', ['stable_hold', 'return_to_start'])
@pytest.mark.parametrize('cropped', [False, True])
def test_stationary_hold_skips_travel_but_preserves_framing(completion_mode, cropped):
    metadata = BasicVideoMetadata(fps=2., frame_count=8, width=640, height=480)
    keypoints = {
        f'{side}_{joint}': (x, y, .95)
        for side, x in [('left', 260.), ('right', 380.)]
        for joint, y in [('shoulder', 140.), ('elbow', 200.), ('wrist', 260.),
                         ('hip', 300.), ('knee', 370.), ('ankle', 450.)]
    }
    if cropped:
        keypoints['left_ankle'] = (260., 480., .95)
    detection = PoseDetection(keypoints, (230., 100., 410., 480. if cropped else 460.))
    samples = [PoseSample(index / 2., [detection]) for index in range(8)]
    contract = {
        'completionMode': completion_mode,
        'observableMotionSpec': {
            'schemaVersion': 1, 'primaryMovingRegions': ['lower_limb'],
            'referenceRegions': ['torso'], 'primaryAxis': 'vertical',
            'motionPattern': 'limb_away_from_body',
            'mustBeVisibleRegions': ['lower_limb', 'torso'],
        },
    }
    result = score_pose_window(
        samples, metadata=metadata,
        settings=PosePrefilterSettings(target_motion_contract=contract))
    issues = result['blockingIssues']
    if completion_mode == 'stable_hold':
        assert 'weak_body_joint_motion' not in issues
        assert 'low_target_motion_observability' not in issues
        if not cropped:
            assert issues == []
    else:
        assert 'weak_body_joint_motion' in issues
        assert 'low_target_motion_observability' in issues
    assert ('cropped_body' in issues) == cropped
