import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.cleanup import cleanup_motion_clip
from exercise_motion_pkg.models import MotionClip, MotionFrame


def test_source_overview_preserves_dense_integrity_evidence(tmp_path, monkeypatch):
    samples = [tmp_path / f"frame_{index:03d}.jpg" for index in range(24)]
    candidate = bake.SourceCutCandidate(
        candidate_id="A", window=bake.DetectionWindow(index=0, start_seconds=2., end_seconds=8.),
        frame_paths=[tmp_path / f"sheet_{index}.jpg" for index in range(3)],
        sample_frame_paths=samples, visual_integrity={"passed": False},
    )
    captured = {}
    def build_sheet(**kwargs):
        captured.update(kwargs)
        return kwargs["output_path"]
    monkeypatch.setattr(bake, "build_frame_contact_sheet", build_sheet)
    monkeypatch.setattr(bake, "persistent_border_crop", lambda paths: None)
    overview = bake.source_cut_review_overview(candidate, tmp_path)
    assert len(overview.frame_paths) == 1
    assert len(captured["frame_paths"]) == 8
    assert captured["frame_paths"][0] == samples[0]
    assert captured["frame_paths"][-1] == samples[-1]
    assert captured["timestamps"] == sorted(captured["timestamps"])
    assert overview.sample_frame_paths == samples
    assert overview.visual_integrity == {"passed": False}
    assert len(candidate.frame_paths) == 3


@pytest.mark.parametrize('sample_interval', [.1, 1.])
def test_complete_source_context_can_recover_outside_partial_discovery_hint(tmp_path, sample_interval):
    contract = {'completionMode': 'return_to_start', 'observableMotionSpec': {
        'primaryMovingRegions': ['hands'], 'referenceRegions': ['hips'],
        'primaryAxis': 'vertical', 'motionPattern': 'joint_flex_extend',
        'requiresReturnToStart': True, 'mustShowFullCycle': True,
        'oneWayPartialIsInvalid': True, 'mustBeVisibleRegions': ['hands', 'hips']}}
    samples = []
    for index in range(round(12/sample_interval)+1):
        time = index*sample_interval
        joints = {}
        for side, x in [('left', .4), ('right', .6)]:
            for name, y in [('shoulder', .3), ('hip', .55), ('knee', .75), ('ankle', .95),
                            ('elbow', .35), ('wrist', .3+.2*math.cos(time*math.pi/4))]:
                joints[f'{side}_{name}'] = [x, y, 1.]
        samples.append({'timeSeconds': time, 'keypoints': joints})
    candidate = bake.RankedCandidate(exercise_index=0, candidate_rank=0, exercise_id='movement',
        exercise_name='Unspecified exercise', exercise_slug='movement', candidate={
            'videoId': 'retained-source', 'durationSeconds': 12,
            'exerciseMotionContract': contract, 'visionPayload': {
                'bestChunkStartSeconds': 9., 'bestChunkEndSeconds': 11.5, 'bestChunkScore': .95,
                'posePrefilter': {'dominantPoseSamples': samples, 'sampleFps': 1/sample_interval}}})
    variants = bake.observed_complete_source_window_variants(candidate)
    if sample_interval > .5:
        assert not variants  # Sparse observations cannot establish a continuous rep.
    else:
        assert variants and variants[0].hint.start_seconds < 1.
        assert variants[0].hint.end_seconds > 7.
        request = bake.BakeAndRankRequest(candidates_json=tmp_path/'candidates.json',
            workspace=tmp_path/'workspace', wham_repo_path=None, body_model_root=None,
            segment_max_seconds=0.)
        assert bake.collect_source_window_variants(candidate, request=request)[0].source == 'observed_complete_source_cycle'


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


@pytest.mark.parametrize("source", ["barbell-thruster", "barbell-bench-press"])
def test_cyclic_source_retains_endpoint_samples_for_3d_loop_selection(tmp_path, recorded_sources, source):
    result = detect_instance(tmp_path, recorded_sources[source])
    assert result["trimmed"] is False
    assert result["reason"] == "cyclic_boundaries_owned_by_observed_3d_cycle_selection"


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
