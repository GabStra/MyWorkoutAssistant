from exercise_motion_pkg.cleanup import cleanup_motion_clip
from exercise_motion_pkg.models import MotionClip, MotionFrame


def test_cleanup_preserves_planted_feet_when_smoothing_noisy_root_translation():
    root_x = [
        0.0,
        0.08,
        -0.08,
        0.08,
        -0.08,
        0.08,
        -0.08,
        0.08,
        -0.08,
        0.08,
        -0.08,
        0.08,
        -0.08,
        0.08,
        -0.08,
        0.08,
        -0.08,
        0.0,
    ]
    frames = []
    for index, pelvis_x in enumerate(root_x):
        pelvis_y = 0.95
        frames.append(
            MotionFrame(
                time_sec=index / 30.0,
                joints={
                    "pelvis": (pelvis_x, pelvis_y, 0.0),
                    "neck": (pelvis_x, pelvis_y + 0.62, 0.0),
                    "head": (pelvis_x, pelvis_y + 0.78, 0.0),
                    "left_hip": (pelvis_x - 0.12, pelvis_y - 0.12, 0.0),
                    "right_hip": (pelvis_x + 0.12, pelvis_y - 0.12, 0.0),
                    "left_ankle": (-0.16, 0.06, 0.0),
                    "right_ankle": (0.16, 0.06, 0.0),
                    "left_foot": (-0.16, 0.0, 0.0),
                    "right_foot": (0.16, 0.0, 0.0),
                    "left_hand": (pelvis_x - 0.28, pelvis_y + 0.05, 0.0),
                    "right_hand": (pelvis_x + 0.28, pelvis_y + 0.05, 0.0),
                },
            )
        )
    clip = MotionClip(
        fps=30.0,
        joint_names=list(frames[0].joints),
        frames=frames,
    )

    cleaned, _ = cleanup_motion_clip(
        clip,
        ground_contact_mode="continuous",
        support_mode_hint="upright",
        preserve_temporal_extent=True,
        one_euro_min_cutoff=0.6,
        one_euro_beta=0.05,
        one_euro_derivative_cutoff=1.0,
    )

    support_profile = cleaned.metadata["cleanup"]["supportProfile"]
    assert support_profile["leftFootContactFrames"] == len(frames)
    assert support_profile["rightFootContactFrames"] == len(frames)
    for foot_name in ("left_foot", "right_foot"):
        anchor = cleaned.frames[0].joints[foot_name]
        max_drift = max(
            sum((frame.joints[foot_name][axis] - anchor[axis]) ** 2 for axis in (0, 2)) ** 0.5
            for frame in cleaned.frames
        )
        assert max_drift < 1e-6
