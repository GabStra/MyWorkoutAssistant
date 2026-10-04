from pathlib import Path

from exercise_motion_pkg import bake_and_rank as bake


def _ranked_candidate(candidate: dict) -> bake.RankedCandidate:
    return bake.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="squat",
        exercise_name="Squat",
        exercise_slug="squat",
        candidate=candidate,
    )


def test_source_cache_key_includes_download_profile_and_local_input_bytes(tmp_path: Path):
    video_path = tmp_path / "retained.mp4"
    video_path.write_bytes(b"first local video")
    base = _ranked_candidate({"url": "https://video.example/watch/abc", "videoPath": str(video_path)})
    high_resolution = _ranked_candidate({
        "url": "https://video.example/watch/abc",
        "videoPath": str(video_path),
        "visionPayload": {"posePrefilter": {"bodyScaleRatio": 0.2}},
    })

    default_key = bake.youtube_source_cache_stem(base)
    high_resolution_key = bake.youtube_source_cache_stem(high_resolution)
    assert default_key != high_resolution_key

    video_path.write_bytes(b"second local video")
    changed_input_key = bake.youtube_source_cache_stem(base)
    assert changed_input_key != default_key


def test_source_cache_manifest_verifies_bytes_and_download_lock_is_persistent(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"test-video-bytes")
    cache_dir = tmp_path / "cache"
    candidate = _ranked_candidate({"videoId": "local-source", "videoPath": str(source)})
    monkeypatch.setattr(bake, "cached_youtube_source_is_usable", lambda _path: True)

    cached, status = bake.download_ranked_candidate_to_source_cache(
        candidate,
        cache_dir=cache_dir,
    )

    assert status == "cached_local_source"
    assert bake.find_cached_youtube_source(cache_dir, bake.youtube_source_cache_stem(candidate)) == cached
    assert (cache_dir / f"{bake.youtube_source_cache_stem(candidate)}.download.oslock").exists()

    cached.write_bytes(b"tampered-video-bytes")
    assert bake.find_cached_youtube_source(cache_dir, bake.youtube_source_cache_stem(candidate)) is None
