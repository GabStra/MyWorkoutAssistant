from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest


SOURCE_FPS = 30.0
OUTPUT_FPS = 24.0
START_SECONDS = 1.1
PARENT_END_SECONDS = 4.15


def _materialized_source_indices(
    source_video: Path,
    *,
    start: float,
    end: float,
    source_fps: float,
    time_base: float,
    source_count: int,
) -> tuple[list[int], int]:
    """Use production's real FFmpeg replay helper to resolve a cut prefix."""

    from exercise_motion_pkg import source_frame_clock as sfc

    guess = max(1, math.ceil((end - start) * OUTPUT_FPS))
    errors: list[str] = []
    for count in range(max(1, guess - 3), guess + 5):
        try:
            indices = sfc._ffmpeg_materialization_source_indices(
                source_video,
                start=start,
                end=end,
                target_fps=OUTPUT_FPS,
                source_fps=source_fps,
                source_time_base=time_base,
                source_frame_count=source_count,
                output_frame_count=count,
            )
            return indices, count
        except ValueError as error:
            errors.append(str(error))
    raise AssertionError("FFmpeg prefix replay failed: " + "; ".join(errors))


@pytest.fixture()
def shifted_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from exercise_motion_pkg import source_frame_clock as sfc

    ffmpeg = sfc.resolve_ffmpeg_path()
    if ffmpeg is None:
        pytest.skip("FFmpeg is required for the source-cut prefix regression")
    source_video = tmp_path / "source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=64x64:rate={SOURCE_FPS:g}:duration=5",
            "-c:v",
            "mpeg4",
            "-pix_fmt",
            "yuv420p",
            str(source_video),
        ],
        check=True,
    )
    metadata = sfc.read_basic_video_metadata(source_video)
    _, time_base = sfc._read_decoded_frame_timestamps(
        source_video, video_role="test source"
    )
    indices, count = _materialized_source_indices(
        source_video,
        start=START_SECONDS,
        end=PARENT_END_SECONDS,
        source_fps=float(metadata.fps),
        time_base=time_base,
        source_count=int(metadata.frame_count),
    )
    clock = {
        "sourceVideoPath": str(source_video),
        "sourceFps": float(metadata.fps),
        "sourceFrameCount": int(metadata.frame_count),
        "sourcePtsVerification": {"timeBaseSec": time_base},
        "outputFps": OUTPUT_FPS,
        "cropStartSeconds": START_SECONDS,
        "frames": [
            {
                "outputFrameIndex": index,
                "sourceFrameIndex": source_index,
                "sourceTimeSec": source_index / float(metadata.fps),
            }
            for index, source_index in enumerate(indices)
        ],
    }
    monkeypatch.setattr(
        sfc, "load_verified_source_frame_clock", lambda *args, **kwargs: clock
    )
    sample_output_indices = list(range(0, count, 3))
    if sample_output_indices[-1] != count - 1:
        sample_output_indices.append(count - 1)
    return {
        "source_video": source_video,
        "clock": clock,
        "metadata": metadata,
        "time_base": time_base,
        "indices": indices,
        "sample_output_indices": sample_output_indices,
    }


def _write_reference(path: Path, sample_times: list[float]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "pose": {
                    "frames": [
                        {"sourceTimeSec": sample_time}
                        for sample_time in sample_times
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _validation(source_video: Path, reference_path: Path) -> dict:
    return {
        "sourceVideoPath": str(source_video),
        "sourcePoseReferencePath": str(reference_path),
        "sourcePoseEndpointContractValidation": {
            "passed": False,
            "blockingMismatches": [
                {
                    "field": "returnEndpointConsistency",
                    "inconsistentFields": ["rootVerticalPosition"],
                }
            ],
        },
    }


def _candidate(**overrides) -> dict:
    return {
        "candidateId": "SHIFTED-24FPS",
        "startSeconds": START_SECONDS,
        "endSeconds": PARENT_END_SECONDS,
        "sourceWindowMinSeconds": 2.0,
        **overrides,
    }


def test_shifted_24fps_window_proposal_emits_exact_clock_prefix(
    shifted_window, tmp_path: Path
) -> None:
    from exercise_motion_pkg import bake_and_rank as bake

    sample_times = [
        index / OUTPUT_FPS for index in shifted_window["sample_output_indices"]
    ]
    reference_path = _write_reference(tmp_path / "pose.json", sample_times)
    proposals = bake.source_cut_endpoint_contract_trim_candidates(
        _candidate(),
        _validation(shifted_window["source_video"], reference_path),
    )

    assert proposals
    proposal = proposals[0]
    target_index = proposal["chunking"]["trimOutputFrameIndex"]
    assert target_index == shifted_window["sample_output_indices"][-1]
    emitted, emitted_count = _materialized_source_indices(
        shifted_window["source_video"],
        start=START_SECONDS,
        end=float(proposal["endSeconds"]),
        source_fps=float(shifted_window["metadata"].fps),
        time_base=shifted_window["time_base"],
        source_count=int(shifted_window["metadata"].frame_count),
    )
    assert emitted == shifted_window["indices"][: target_index + 1]
    assert emitted_count == target_index + 1
    assert float(proposal["endSeconds"]) < PARENT_END_SECONDS
    assert float(proposal["endSeconds"]) - START_SECONDS >= 2.0 - 1e-6


def test_return_tail_trim_fails_closed_without_identity_clock_samples_or_floor(
    shifted_window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg import source_frame_clock as sfc

    sample_times = [
        index / OUTPUT_FPS for index in shifted_window["sample_output_indices"]
    ]
    reference_path = _write_reference(tmp_path / "pose.json", sample_times)
    valid_validation = _validation(shifted_window["source_video"], reference_path)

    assert not bake.source_cut_endpoint_contract_trim_candidates(
        _candidate(), {**valid_validation, "sourceVideoPath": ""}
    )
    assert not bake.source_cut_endpoint_contract_trim_candidates(
        _candidate(), {**valid_validation, "sourcePoseReferencePath": ""}
    )

    def missing_clock(*args, **kwargs):
        raise FileNotFoundError("verified clock absent")

    monkeypatch.setattr(sfc, "load_verified_source_frame_clock", missing_clock)
    assert not bake.source_cut_endpoint_contract_trim_candidates(
        _candidate(), valid_validation
    )

    monkeypatch.setattr(
        sfc,
        "load_verified_source_frame_clock",
        lambda *args, **kwargs: shifted_window["clock"],
    )
    tolerance = 0.49 / OUTPUT_FPS
    frame_times = [
        float(row["sourceTimeSec"]) for row in shifted_window["clock"]["frames"]
    ]
    gap_index = next(
        index
        for index in range(2, len(frame_times) - 1)
        if frame_times[index + 1] - frame_times[index] > 2.0 * tolerance
    )
    relative_times = [value - frame_times[0] for value in frame_times]
    irregular_times = [
        relative_times[0],
        relative_times[1],
        (frame_times[gap_index] + frame_times[gap_index + 1]) / 2.0 - frame_times[0],
        relative_times[gap_index + 1],
        relative_times[-1],
    ]
    irregular_path = _write_reference(tmp_path / "irregular.json", irregular_times)
    assert not bake.source_cut_endpoint_contract_trim_candidates(
        _candidate(),
        _validation(shifted_window["source_video"], irregular_path),
    )
    assert not bake.source_cut_endpoint_contract_trim_candidates(
        _candidate(sourceWindowMinSeconds=PARENT_END_SECONDS - START_SECONDS + 1.0),
        valid_validation,
    )
