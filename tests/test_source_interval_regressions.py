import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.cleanup import cleanup_motion_clip
from exercise_motion_pkg.models import MotionClip, MotionFrame


@pytest.fixture
def recorded_sources():
    return json.loads((Path(__file__).parent / "fixtures/source_interval_regressions.json").read_text(encoding="utf-8"))


def detect_instance(tmp_path, source):
    directory = tmp_path / "segment_detection"
    directory.mkdir(exist_ok=True)
    (directory / "exact_source_pose_reference.json").write_text(json.dumps({"pose": source["pose"]}), encoding="utf-8")
    return bake.exact_source_pose_first_movement_instance(
        candidate_workspace=tmp_path,
        completion_mode="return_to_start",
        exercise_motion_contract=source["contract"],
    )


def test_thruster_does_not_reuse_the_incomplete_two_thirds_cut(tmp_path, recorded_sources):
    result = detect_instance(tmp_path, recorded_sources["barbell-thruster"])
    assert result["endRatio"] > 2 / 3
    assert result["boundaryValidation"]["passed"] is True


def test_bench_press_shorter_interval_has_independent_phase_confirmation(tmp_path, recorded_sources):
    result = detect_instance(tmp_path, recorded_sources["barbell-bench-press"])
    assert result["trimmed"] is True
    assert result["boundaryValidation"]["passed"] is True
    assert result["endRatio"] == pytest.approx(0.52)


def test_failed_boundary_confirmation_preserves_the_approved_interval(tmp_path, recorded_sources, monkeypatch):
    monkeypatch.setattr(bake, "full_repetition_phase_completeness_metrics_from_source_pose_payload",
                        lambda *args, **kwargs: {"required": True, "passed": False})
    result = detect_instance(tmp_path, recorded_sources["barbell-bench-press"])
    assert result["trimmed"] is False
    assert result["reason"] == "proposed_interval_not_confirmed_complete"


def test_materialized_source_reference_is_not_cut_twice(recorded_sources):
    pose = recorded_sources["barbell-bench-press"]["pose"]
    ranking = bake.LoopRanking(0, [], payload={"preWhamSourceIntervalAuthority": {
        "movementInstance": {"trimmed": True, "endRatio": .52},
    }})
    once = bake.source_pose_reference_for_materialized_review(pose, ranking=ranking)
    twice = bake.source_pose_reference_for_materialized_review(once, ranking=ranking)
    assert len(once["frames"]) < len(pose["frames"])
    assert twice is once


def test_selected_video_uses_review_interval_not_cached_ratio(tmp_path):
    directory = tmp_path / "segment_detection"
    directory.mkdir()
    (directory / "exact_source_pose_reference.json").write_text(json.dumps({
        "pose": {"authoritativeMovementInstance": {"trimmed": True, "endRatio": .2}},
    }), encoding="utf-8")
    item = SimpleNamespace(candidate_workspace=tmp_path, loop_index=0,
                           loop_start_seconds=0., loop_end_seconds=1.6, duration_sec=1.6,
                           source_review_video_path=None, source_review_start_seconds=None,
                           source_review_end_seconds=None)
    window = bake.selected_source_section_window_for_review_item(item, source_duration_seconds=3.12)
    assert window.start_seconds == 0.
    assert window.end_seconds == 1.6


def test_source_reviewed_cleanup_preserves_stationary_endpoint_frames(recorded_sources):
    pose = recorded_sources["barbell-bench-press"]["pose"]
    joints = pose["frames"][0]["joints"]
    frames = [MotionFrame(index / 30, {name: tuple(point) for name, point in joints.items()}) for index in range(30)]
    for index in range(10, 20):
        frames[index].joints.update({name: (point[0] + 0.1, point[1], point[2]) for name, point in frames[index].joints.items()})
    clip = MotionClip(30, list(joints), frames)
    cleaned, stats = cleanup_motion_clip(clip, preserve_temporal_extent=True, support_mode_hint="lying")
    assert len(cleaned.frames) == len(frames)
    assert [frame.time_sec for frame in cleaned.frames] == [frame.time_sec for frame in frames]
    assert stats.trimmed_start_frames == stats.trimmed_end_frames == 0
