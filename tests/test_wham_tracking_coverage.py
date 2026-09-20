from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from exercise_motion_pkg.wham_tracking_coverage import (
    best_compatible_chain,
    stitch_track_chain,
    tracking_coverage_report,
)
from exercise_motion_pkg.wham_warm_worker import process_job


def _track(start: int, end: int, *, center_x: float = 100.0) -> defaultdict[str, list]:
    frame_ids = np.arange(start, end + 1)
    frame_count = len(frame_ids)
    bbox = np.tile(np.array([center_x, 100.0, 1.0, 1.0]), (frame_count, 1))
    keypoints = np.zeros((frame_count, 17, 3), dtype=np.float32)
    keypoints[:, :, 0] = center_x
    keypoints[:, :, 1] = 100.0
    keypoints[:, :, 2] = 1.0
    return defaultdict(list, {"frame_id": frame_ids, "bbox": bbox, "keypoints": keypoints})


def test_tracking_coverage_requires_both_movement_boundaries() -> None:
    report = tracking_coverage_report(
        {1: _track(0, 80)},
        fps=30.0,
        frame_count=120,
        required_start_seconds=0.5,
        required_end_seconds=3.5,
    )

    assert report["passed"] is False
    assert report["startCovered"] is True
    assert report["endCovered"] is False


def test_short_overlapping_duplicate_tracks_require_pose_evidence_and_unique_frames():
    tracks = {0: _track(0, 227), 2: _track(226, 274)}
    chain = best_compatible_chain(tracks, max_gap_frames=11)
    assert [key for key, _ in chain] == [0, 2]
    merged, interpolated = stitch_track_chain(tracks, chain)
    assert interpolated == 0
    np.testing.assert_array_equal(merged[0]['frame_id'], np.arange(275))
    assert len(merged[0]['keypoints']) == len(merged[0]['bbox']) == 275
    assert tracking_coverage_report(merged, fps=30., frame_count=285,
                                   required_start_seconds=1.25, required_end_seconds=8.25)['passed']
    for variant in ('other_person', 'missing_pose', 'one_disagreeing_overlap'):
        other = _track(226, 274)
        if variant == 'other_person':
            other['keypoints'][:, :, 0] += 60.
        elif variant == 'missing_pose':
            other['keypoints'][:, :, 2] = 0.
        else:
            other['keypoints'][1, :, 0] += 60.
        rejected = best_compatible_chain({0: tracks[0], 2: other}, max_gap_frames=11)
        assert len(rejected) == 1


def test_preflight_rejection_cache_requires_current_policy(tmp_path, monkeypatch):
    import pytest
    import hashlib
    import importlib.util
    import sys
    from types import ModuleType

    # Only the WHAM-specific imports need substitutes; run the real preflight
    # and its cache logic with an empty detector, without GPU reconstruction.
    for name, attribute in [('configs.config', 'get_cfg_defaults'),
                            ('lib.models.preproc.detector', 'DetectionModel'),
                            ('lib.models.preproc.extractor', 'FeatureExtractor')]:
        stub = ModuleType(name)
        setattr(stub, attribute, object)
        monkeypatch.setitem(sys.modules, name, stub)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    module_path = Path(__file__).parents[1] / 'exercise_motion_pkg/wham_tracking_preflight.py'
    spec = importlib.util.spec_from_file_location('preflight_cache_test', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    video = tmp_path / 'input.mp4'
    video.write_bytes(b'video')
    report_path = tmp_path / 'report.json'
    report_path.write_text(json.dumps({'inputSha256': hashlib.sha256(b'video').hexdigest(),
        'requiredStartSeconds': 0., 'requiredEndSeconds': .1, 'passed': False}))
    capture = SimpleNamespace(isOpened=lambda: True, read=lambda: (False, None), release=lambda: None,
        get=lambda prop: 30. if prop == module.cv2.CAP_PROP_FPS else 3)
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda _: capture)
    calls = []

    def detector(_device):
        calls.append(True)
        return SimpleNamespace(process=lambda fps: defaultdict(
            lambda: defaultdict(list), {7: _track(0, 0)}))

    cfg = SimpleNamespace(DEVICE='cpu', FLIP_EVAL=False)

    def run():
        return module.run_tracking_preflight(video_path=video, output_root=tmp_path / 'output',
            report_path=report_path, required_start_seconds=0., required_end_seconds=.1,
            cfg=cfg, detection_model_factory=detector)

    report = run()
    assert report['cacheStatus'] == 'computed'  # Legacy verdict must not bypass code.
    assert report['passed'] is False
    evidence_path = Path(report['detectionTracksPath'])
    evidence = module.joblib.load(evidence_path)
    np.testing.assert_array_equal(evidence[7]['frame_id'], [0])
    np.testing.assert_array_equal(evidence[7]['keypoints'], _track(0, 0)['keypoints'])
    assert run()['cacheStatus'] == 'reused'
    assert len(calls) == 1
    evidence_path.unlink()
    assert run()['cacheStatus'] == 'computed'
    assert len(calls) == 2
    real_sha256 = module._sha256
    monkeypatch.setattr(module, '_sha256', lambda path: 'changed policy' if path.name ==
                        'wham_tracking_coverage.py' else real_sha256(path))
    assert run()['cacheStatus'] == 'computed'
    cfg.FLIP_EVAL = True
    assert run()['cacheStatus'] == 'computed'
    assert len(calls) == 4

    monkeypatch.setenv('WHAM_BBOX_CONF', '0.61')
    assert run()['cacheStatus'] == 'computed'
    assert run()['cacheStatus'] == 'reused'
    assert len(calls) == 5
    previous_sha256 = module._sha256
    monkeypatch.setattr(module, '_sha256', lambda path: 'changed detector' if path.name ==
                        Path(__file__).name else previous_sha256(path))
    assert run()['cacheStatus'] == 'computed'
    assert run()['cacheStatus'] == 'reused'
    assert len(calls) == 6

    # An interrupted successful coverage check must not bless preprocessing
    # left by an older attempt in the same sequence directory.
    sequence_dir = tmp_path / 'output' / 'input'
    for filename in ('tracking_results.pth', 'slam_results.pth'):
        module.joblib.dump({'stale': True}, sequence_dir / filename)
    extraction_calls = []

    def extract(_video, tracks):
        extraction_calls.append(True)
        if len(extraction_calls) == 1:
            raise RuntimeError('interrupted feature extraction')
        return tracks

    def run_complete():
        return module.run_tracking_preflight(video_path=video, output_root=tmp_path / 'output',
            report_path=report_path, required_start_seconds=0., required_end_seconds=.1,
            cfg=cfg, detection_model_factory=lambda _: SimpleNamespace(process=lambda fps: {7: _track(0, 2)}),
            feature_extractor_factory=lambda *_: SimpleNamespace(run=extract))

    cfg.FLIP_EVAL = False  # Recompute instead of reusing the last negative verdict.
    with pytest.raises(RuntimeError, match='interrupted feature extraction'):
        run_complete()
    assert json.loads(report_path.read_text())['passed'] is True
    resumed = run_complete()
    assert resumed['cacheStatus'] == 'computed'
    assert resumed['reusablePreprocessingWritten'] is True
    assert len(extraction_calls) == 2
    assert 'stale' not in module.joblib.load(sequence_dir / 'tracking_results.pth')
    assert run_complete()['cacheStatus'] == 'reused'
    assert len(extraction_calls) == 2


def test_compatible_short_track_fragments_are_stitched_and_revalidated() -> None:
    tracks = {1: _track(0, 44), 2: _track(46, 89)}
    chain = best_compatible_chain(tracks, max_gap_frames=10)
    stitched, interpolated = stitch_track_chain(tracks, chain)

    report = tracking_coverage_report(
        stitched,
        fps=30.0,
        frame_count=90,
        required_start_seconds=0.0,
        required_end_seconds=3.0,
    )

    assert interpolated == 1
    assert report["passed"] is True
    assert report["coverageRatio"] == 1.0


def test_warm_worker_stops_before_reconstruction_when_preflight_rejects(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "jobs"
    results_dir = tmp_path / "results"
    logs_dir = tmp_path / "logs"
    for path in (jobs_dir, results_dir, logs_dir):
        path.mkdir()
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"video")
    output_root = tmp_path / "output"
    job_path = jobs_dir / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "jobId": "job",
                "video": str(video_path),
                "outputRoot": str(output_root),
                "trackingPreflight": True,
                "requiredStartSeconds": 1.0,
                "requiredEndSeconds": 3.0,
            }
        ),
        encoding="utf-8",
    )
    demo = SimpleNamespace(
        DetectionModel=object(),
        FeatureExtractor=object(),
        run=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("WHAM reconstruction should not run")
        ),
    )
    preflight_calls: list[dict] = []

    class FakePreflight:
        @staticmethod
        def run_tracking_preflight(**kwargs):
            preflight_calls.append(kwargs)
            return {"passed": False, "endCovered": False, "cacheStatus": "computed"}

    state = {
        "demo": demo,
        "cfg": object(),
        "network": object(),
        "trackingPreflight": FakePreflight,
        "loadSeconds": 1.0,
        "preprocessingLoadSeconds": lambda: 0.0,
        "resetPreprocessingModels": lambda: None,
    }

    process_job(job_path, results_dir, logs_dir, state)

    result = json.loads((results_dir / "job.json").read_text(encoding="utf-8"))
    assert result["status"] == "rejected_tracking_preflight"
    assert result["trackingPreflight"]["endCovered"] is False
    assert preflight_calls[0]["required_start_seconds"] == 1.0
    assert preflight_calls[0]["required_end_seconds"] == 3.0


def test_warm_worker_converts_system_exit_to_failed_result_and_resets_state(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "jobs"
    results_dir = tmp_path / "results"
    logs_dir = tmp_path / "logs"
    for path in (jobs_dir, results_dir, logs_dir):
        path.mkdir()
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"video")
    job_path = jobs_dir / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "jobId": "job",
                "video": str(video_path),
                "outputRoot": str(tmp_path / "output"),
            }
        ),
        encoding="utf-8",
    )
    reset_calls: list[bool] = []
    state = {
        "demo": SimpleNamespace(
            args=None,
            run=lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit(1)),
        ),
        "cfg": object(),
        "network": object(),
        "loadSeconds": 1.0,
        "preprocessingLoadSeconds": lambda: 0.0,
        "resetPreprocessingModels": lambda: reset_calls.append(True),
    }

    process_job(job_path, results_dir, logs_dir, state)

    result = json.loads((results_dir / "job.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["error"] == "SystemExit: 1"
    assert reset_calls == [True]
