from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from exercise_motion_pkg import pipeline
from exercise_motion_pkg import source_frame_clock


def test_prepared_69_frame_source_clock_mismatch_stops_before_gpu(monkeypatch, tmp_path: Path):
    original = tmp_path / "selected-69.mp4"
    prepared = tmp_path / "selected-68.mp4"
    clock = tmp_path / "selected-68.source_frame_clock.json"
    original.write_bytes(b"0" * 69)
    prepared.write_bytes(b"0" * 68)
    original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    clock.write_text("{}", encoding="utf-8")
    gpu_calls: list[bool] = []

    def load_clock(_clock_path: Path, *, expected_video_path: Path | None = None):
        assert expected_video_path == prepared.resolve()
        if hashlib.sha256(expected_video_path.read_bytes()).hexdigest() != original_sha:
            raise ValueError("source frame clock output identity does not match the prepared video")
        return {"outputFrameCount": 69, "outputFps": 30.0, "frames": [{}] * 69}

    monkeypatch.setattr(pipeline, "ensure_three_module_asset", lambda: None)
    monkeypatch.setattr(pipeline, "prepare_input_video", lambda _request, _paths: prepared)
    monkeypatch.setattr(source_frame_clock, "source_frame_clock_path_for_video", lambda _path: clock)
    monkeypatch.setattr(source_frame_clock, "load_verified_source_frame_clock", load_clock)

    request = pipeline.GenerateRequest(
        exercise_slug="clock-guard",
        workspace=tmp_path / "workspace",
        video_path=original,
        source_frame_clock_path=clock,
        body_model_root=tmp_path / "body-model",
        use_reconstruction_docker=True,
        motion_tuning_enabled=False,
        video_world_alignment_enabled=False,
    )

    def fake_gpu(operation):
        gpu_calls.append(True)
        return operation()

    with pytest.raises(ValueError, match="output identity does not match"):
        pipeline._run_generation_pipeline_uncached(
            request,
            run_reconstruction_exclusive=fake_gpu,
            runtime_identity={"cacheable": False},
        )
    assert gpu_calls == []
