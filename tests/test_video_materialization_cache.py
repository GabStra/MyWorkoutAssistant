import hashlib
import json
from pathlib import Path

import pytest

from exercise_motion_pkg.video_materialization_cache import (
    MaterializationNotProduced,
    default_video_materialization_cache_dir,
    materialize_cached,
)


def _producer(calls: list[str], settings: dict):
    def produce(output_path: Path) -> None:
        calls.append(json.dumps(settings, sort_keys=True))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(
            hashlib.sha256(
                (output_path.name.split(".")[0] + json.dumps(settings, sort_keys=True)).encode()
            ).digest()
        )

    return produce


def test_same_source_bytes_reuse_across_paths_and_workspaces(tmp_path: Path) -> None:
    source_a = tmp_path / "workspace-a" / "source.mp4"
    source_b = tmp_path / "workspace-b" / "nested" / "renamed.mov"
    source_a.parent.mkdir(parents=True)
    source_b.parent.mkdir(parents=True)
    source_a.write_bytes(b"same-source-bytes")
    source_b.write_bytes(b"same-source-bytes")
    cache_dir = tmp_path / "reconstruction-cache" / "video-materialization"
    calls: list[str] = []

    first = materialize_cached(
        source_path=source_a,
        output_path=tmp_path / "workspace-a" / "input" / "trim.mp4",
        settings={"fps": 30},
        cache_dir=cache_dir,
        producer=_producer(calls, {"fps": 30}),
    )
    second = materialize_cached(
        source_path=source_b,
        output_path=tmp_path / "workspace-b" / "input" / "trim.mp4",
        settings={"fps": 30},
        cache_dir=cache_dir,
        producer=_producer(calls, {"fps": 30}),
    )

    assert calls == ['{"fps": 30}']
    assert first.read_bytes() == second.read_bytes()
    assert second.parent != first.parent


def test_settings_source_and_corrupt_cached_output_force_regeneration(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    cache_dir = tmp_path / "cache"
    calls: list[str] = []

    def run(source_path: Path, settings: dict, name: str) -> bytes:
        return materialize_cached(
            source_path=source_path,
            output_path=tmp_path / name,
            settings=settings,
            cache_dir=cache_dir,
            producer=_producer(calls, settings),
        ).read_bytes()

    original = run(source, {"fps": 30}, "first.mp4")
    changed_settings = run(source, {"fps": 24}, "settings.mp4")
    other_source = tmp_path / "other.mp4"
    other_source.write_bytes(b"other")
    changed_input = run(other_source, {"fps": 30}, "input.mp4")
    assert len(calls) == 3
    assert len({original, changed_settings, changed_input}) == 3

    for cached_output in cache_dir.glob("*.mp4"):
        cached_output.write_bytes(b"corrupted")
    restored = run(source, {"fps": 30}, "restored.mp4")
    assert len(calls) == 4
    assert restored == original


def test_rejects_source_equal_output_zero_output_and_non_json_settings(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    with pytest.raises(ValueError, match="differ from its source"):
        materialize_cached(
            source_path=source,
            output_path=source,
            settings={"fps": 30},
            cache_dir=tmp_path / "cache",
            producer=lambda destination: None,
        )

    with pytest.raises(MaterializationNotProduced, match="no non-empty output"):
        materialize_cached(
            source_path=source,
            output_path=tmp_path / "empty.mp4",
            settings={"fps": 30},
            cache_dir=tmp_path / "cache",
            producer=lambda destination: destination.write_bytes(b""),
        )

    with pytest.raises(ValueError, match="strict JSON"):
        materialize_cached(
            source_path=source,
            output_path=tmp_path / "nan.mp4",
            settings={"fps": float("nan")},
            cache_dir=tmp_path / "cache",
            producer=lambda destination: destination.write_bytes(b"video"),
        )


def test_default_cache_dir_reuses_pipeline_global_root(tmp_path: Path) -> None:
    assert default_video_materialization_cache_dir(tmp_path / "exercise_motion" / "run" / "out.mp4") == (
        tmp_path / "exercise_motion" / "reconstruction-cache" / "video-materialization"
    )
    output = tmp_path / "other" / "run" / "out.mp4"
    assert default_video_materialization_cache_dir(output) == (
        output.parent / "reconstruction-cache" / "video-materialization"
    )


def test_trim_video_reuses_bytes_across_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from exercise_motion_pkg import video_materialization_cache, video_utils

    cache_dir = tmp_path / "exercise_motion" / "reconstruction-cache" / "video-materialization"
    monkeypatch.setattr(
        video_materialization_cache,
        "default_video_materialization_cache_dir",
        lambda anchor: cache_dir,
    )
    monkeypatch.setattr(video_utils, "resolve_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(video_utils, "h264_codec_args", lambda: ["-c:v", "libx264"])
    calls: list[str] = []

    def encode(
        *, source_path, output_path, start_seconds, end_seconds, target_fps=None, ffmpeg
    ) -> None:
        calls.append(f"{start_seconds}:{end_seconds}:{target_fps}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"trimmed:" + source_path.read_bytes())

    monkeypatch.setattr(video_utils, "_trim_video_with_ffmpeg", encode)
    source_a = tmp_path / "run-a" / "source.mp4"
    source_b = tmp_path / "run-b" / "source.mp4"
    source_a.parent.mkdir()
    source_b.parent.mkdir()
    source_a.write_bytes(b"identical source")
    source_b.write_bytes(b"identical source")

    first = video_utils.trim_video(
        source_path=source_a,
        output_path=tmp_path / "run-a" / "input" / "selected_segment.mp4",
        start_seconds=1.0,
        end_seconds=4.0,
        target_fps=30.0,
    )
    second = video_utils.trim_video(
        source_path=source_b,
        output_path=tmp_path / "run-b" / "input" / "selected_segment.mp4",
        start_seconds=1.0,
        end_seconds=4.0,
        target_fps=30.0,
    )

    assert calls == ["1.0:4.0:30.0"]
    assert first.read_bytes() == second.read_bytes()


def test_sanitizer_reuses_encoded_bytes_across_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from exercise_motion_pkg import video_materialization_cache, youtube

    cache_dir = tmp_path / "exercise_motion" / "reconstruction-cache" / "video-materialization"
    monkeypatch.setattr(
        video_materialization_cache,
        "default_video_materialization_cache_dir",
        lambda anchor: cache_dir,
    )
    monkeypatch.setattr(youtube, "resolve_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(youtube, "h264_codec_args", lambda: ["-c:v", "libx264"])
    calls: list[list[str]] = []

    def run_ffmpeg(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        source = Path(args[args.index("-i") + 1])
        destination = Path(args[-1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"encoded:" + source.read_bytes())
        return 0, ""

    monkeypatch.setattr(youtube, "_run_ffmpeg", run_ffmpeg)
    source_a = tmp_path / "run-a" / "clip.mp4"
    source_b = tmp_path / "run-b" / "clip.mp4"
    source_a.parent.mkdir()
    source_b.parent.mkdir()
    source_a.write_bytes(b"identical source")
    source_b.write_bytes(b"identical source")

    first = youtube._sanitize_downloaded_video_uncached(source_a)
    second = youtube._sanitize_downloaded_video_uncached(source_b)
    assert len(calls) == 1
    assert first.read_bytes() == second.read_bytes()

    for cached_output in cache_dir.glob("*.mp4"):
        cached_output.write_bytes(b"corrupted")
    restored = youtube._sanitize_downloaded_video_uncached(source_a)
    assert len(calls) == 2
    assert restored.read_bytes() == b"encoded:identical source"


def test_failed_sanitizer_does_not_cache_partial_video(tmp_path, monkeypatch):
    from exercise_motion_pkg import youtube

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"original")
    monkeypatch.setattr(youtube, "resolve_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(youtube, "retry_h264_codec_args", lambda *args: None)

    def fail(args):
        Path(args[-1]).write_bytes(b"partial")
        return 1, "encoding failed"

    monkeypatch.setattr(youtube, "_run_ffmpeg", fail)
    assert youtube._sanitize_downloaded_video_uncached(source) == source
    cache_dir = default_video_materialization_cache_dir(tmp_path / "clip_sanitized.mp4")
    assert not list(cache_dir.glob("*.mp4"))
    assert source.read_bytes() == b"original"
