from __future__ import annotations

import pytest

import exercise_motion_pkg.ffmpeg_utils as ffmpeg_utils
from exercise_motion_pkg.ffmpeg_utils import h264_codec_args, retry_h264_codec_args


@pytest.fixture(autouse=True)
def reset_probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ffmpeg_utils, "_NVENC_H264_PROBE", None)
    yield


def test_h264_codec_args_uses_nvenc_when_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_utils, "resolve_ffmpeg_path", lambda: "ffmpeg-fake")

    class FakeResult:
        returncode = 0
        stdout = " V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)\n"

    monkeypatch.setattr(
        ffmpeg_utils.subprocess, "run", lambda *args, **kwargs: FakeResult()
    )
    args = h264_codec_args()
    assert args[1] == "h264_nvenc"
    assert "-cq" in args
    # Probe result is cached: a second call must not re-run ffmpeg.
    monkeypatch.setattr(
        ffmpeg_utils.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("probe ran twice")),
    )
    assert h264_codec_args()[1] == "h264_nvenc"


def test_h264_codec_args_falls_back_without_nvenc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_utils, "resolve_ffmpeg_path", lambda: None)
    args = h264_codec_args()
    assert args == ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]
    assert h264_codec_args(fallback=True) == args


def test_retry_h264_codec_args_swaps_only_nvenc_section() -> None:
    codec_args = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0"]
    command = ["ffmpeg", "-y", "-i", "in.mp4", *codec_args, "-pix_fmt", "yuv420p", "out.mp4"]
    retried = retry_h264_codec_args(command, codec_args)
    assert retried is not None
    assert retried[retried.index("-c:v") + 1] == "libx264"
    assert retried[-1] == "out.mp4"
    # Already-CPU codecs never retry.
    assert retry_h264_codec_args(["ffmpeg", "-c:v", "libx264"], ["-c:v", "libx264"]) is None
