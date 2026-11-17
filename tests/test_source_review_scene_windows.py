from types import SimpleNamespace

from exercise_motion_pkg import youtube


def test_short_source_review_separates_demo_from_outro_and_pose_anchor(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"retained source")
    monkeypatch.setattr(youtube, "download_youtube_preview", lambda *args, **kwargs: video)
    monkeypatch.setattr("exercise_motion_pkg.video_utils.read_basic_video_metadata", lambda path:
                        SimpleNamespace(duration_seconds=9., fps=30., frame_count=270, width=640, height=360))
    monkeypatch.setattr("exercise_motion_pkg.segment_detection.detect_motion_candidate_intervals",
                        lambda **kwargs: [])
    monkeypatch.setattr("exercise_motion_pkg.bake_and_rank.detect_source_scene_boundaries",
                        lambda *args, **kwargs: {"status": "ok", "boundarySeconds": [5.]})
    candidate = youtube.YouTubeCandidate(
        url="https://www.youtube.com/watch?v=retained", video_id="retained", title="Movement demo",
        channel=None, duration_seconds=9, view_count=None, upload_date=None,
        description_snippet=None, thumbnail=None,
        vision_payload={"posePrefilter": {"validChunks": [{"startSeconds": 0., "endSeconds": 9.}]}},
    )
    prepared = youtube.prepare_vision_review(
        youtube.ExerciseEntry(exercise_id="exercise", name="Movement", slug="movement"),
        candidate, youtube.YouTubeRankingSettings(vision_chunk_seconds=12.),
    )
    try:
        assert prepared.chunk_windows == [(0., 5.), (5., 9.)]
        assert all(window.source == "source_scene" for window in prepared.review_windows)
    finally:
        prepared.close()
