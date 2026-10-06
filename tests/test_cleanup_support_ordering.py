import exercise_motion_pkg.cleanup as cleanup
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.render_geometry import support_surface_height


ROOT_X = [
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


def _noisy_root_stance_clip(*, global_y_offset: float = 0.0) -> MotionClip:
    frames = []
    for index, pelvis_x in enumerate(ROOT_X):
        pelvis_y = 0.95 + global_y_offset
        frames.append(
            MotionFrame(
                time_sec=index / 30.0,
                joints={
                    "pelvis": (pelvis_x, pelvis_y, 0.0),
                    "neck": (pelvis_x, pelvis_y + 0.62, 0.0),
                    "head": (pelvis_x, pelvis_y + 0.78, 0.0),
                    "left_hip": (pelvis_x - 0.12, pelvis_y - 0.12, 0.0),
                    "right_hip": (pelvis_x + 0.12, pelvis_y - 0.12, 0.0),
                    "left_ankle": (-0.16, global_y_offset + 0.06, 0.0),
                    "right_ankle": (0.16, global_y_offset + 0.06, 0.0),
                    "left_foot": (-0.16, global_y_offset, 0.0),
                    "right_foot": (0.16, global_y_offset, 0.0),
                    "left_hand": (pelvis_x - 0.28, pelvis_y + 0.05, 0.0),
                    "right_hand": (pelvis_x + 0.28, pelvis_y + 0.05, 0.0),
                },
            )
        )
    return MotionClip(
        fps=30.0,
        joint_names=list(frames[0].joints),
        frames=frames,
    )


def _assert_feet_stay_planted(clip: MotionClip) -> None:
    support_profile = clip.metadata["cleanup"]["supportProfile"]
    assert support_profile["leftFootContactFrames"] == clip.frame_count
    assert support_profile["rightFootContactFrames"] == clip.frame_count
    for foot_name in ("left_foot", "right_foot"):
        anchor = clip.frames[0].joints[foot_name]
        max_drift = max(
            sum((frame.joints[foot_name][axis] - anchor[axis]) ** 2 for axis in (0, 2)) ** 0.5
            for frame in clip.frames
        )
        assert max_drift < 1e-6


def _cleanup_continuous_stance(clip: MotionClip) -> MotionClip:
    cleaned, _ = cleanup.cleanup_motion_clip(
        clip,
        ground_contact_mode="continuous",
        support_mode_hint="upright",
        preserve_temporal_extent=True,
        one_euro_min_cutoff=0.6,
        one_euro_beta=0.05,
        one_euro_derivative_cutoff=1.0,
    )
    return cleaned


def test_cleanup_preserves_planted_feet_when_smoothing_noisy_root_translation():
    cleaned = _cleanup_continuous_stance(_noisy_root_stance_clip())

    _assert_feet_stay_planted(cleaned)


def test_cleanup_redetects_continuous_contacts_after_floor_normalization(monkeypatch):
    clip = _noisy_root_stance_clip(global_y_offset=0.2)
    contact_passes = []
    detect_contacts = cleanup.detect_support_contact_states

    def record_contact_pass(motion_clip, **kwargs):
        states = detect_contacts(motion_clip, **kwargs)
        contact_passes.append(
            {
                "minimumFootSurfaceY": min(
                    support_surface_height(frame.joints[foot_name][1])
                    for frame in motion_clip.frames
                    for foot_name in ("left_foot", "right_foot")
                ),
                "groundContactFrames": sum(
                    bool(state.get("leftInContact") or state.get("rightInContact"))
                    for state in states
                ),
            }
        )
        return states

    monkeypatch.setattr(cleanup, "detect_support_contact_states", record_contact_pass)

    cleaned = _cleanup_continuous_stance(clip)

    assert contact_passes[0]["minimumFootSurfaceY"] > 0.08
    assert contact_passes[0]["groundContactFrames"] == 0
    assert contact_passes[1]["minimumFootSurfaceY"] <= 0.08
    assert contact_passes[1]["groundContactFrames"] == clip.frame_count
    _assert_feet_stay_planted(cleaned)
