from exercise_motion_pkg.pose_prefilter import PosePrefilterSettings, build_pose_sample_plan
from exercise_motion_pkg.video_utils import BasicVideoMetadata


def test_full_pose_scan_observes_last_frame_without_duplicate_samples():
    for count in (0, 1, 109, 110):
        metadata = BasicVideoMetadata(fps=24., frame_count=count, width=640, height=360)
        frames, _ = build_pose_sample_plan(
            metadata, settings=PosePrefilterSettings(sample_fps=8., scan_strategy='full'))
        assert frames == sorted(set(frames))
        assert all(0 <= frame < count for frame in frames)
        if count:
            assert frames[0] == 0
            assert frames[-1] == count - 1
