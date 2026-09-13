import copy
import math
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import pose_fidelity as fidelity
from exercise_motion_pkg.repetition_phase import complete_repetition


@pytest.mark.parametrize('width,height', [(640, 360), (360, 640), (1000, 1000)])
def test_image_geometry_is_invariant_to_canvas_aspect_ratio(width, height):
    # Same physical triangle, expressed in three differently shaped images.
    points = {'a': [20, 20], 'b': [80, 20], 'c': [80, 90]}
    payload = {'coordinateSpace': 'normalized_image_xy', 'imageWidth': width,
               'imageHeight': height, 'frames': [{'sourceTimeSec': 0,
               'joints': {n: [x / width, y / height] for n, (x, y) in points.items()}}]}
    observed = fidelity._pose_frames(payload, source=True)[0]['joints']
    for name, point in points.items():
        assert observed[name] == pytest.approx([v / height for v in point])


def test_missing_image_dimensions_do_not_silently_assume_square_pixels():
    assert fidelity._pose_frames({'coordinateSpace': 'normalized_image_xy',
        'frames': [{'sourceTimeSec': 0, 'joints': {'a': [.1, .2]}}]}, source=True) == []


def test_sparse_observations_do_not_stretch_motion_or_extrapolate():
    frames = [{'time': t, 'joints': {'wrist': (2*t, t, 0)}} for t in [0., 1., 2.]]
    assert fidelity._motion_frame_at_time(frames, 1.8)['joints']['wrist'] == pytest.approx((3.6, 1.8, 0))
    assert fidelity._motion_frame_at_time(frames, 2.1) is None
    assert fidelity._motion_frame_at_time(frames, -.1) is None


def test_fidelity_matches_sparse_video_to_motion_in_metric_space():
    base = {'left_shoulder': (1., 1.), 'right_shoulder': (2., 1.),
            'left_hip': (1., 2.), 'right_hip': (2., 2.),
            'left_knee': (1., 3.), 'right_knee': (2., 3.),
            'left_ankle': (1., 4.), 'right_ankle': (2., 4.),
            'left_elbow': (.5, 1.5), 'right_elbow': (2.5, 1.5),
            'left_wrist': (.2, 2.), 'right_wrist': (2.8, 2.)}
    def joints(t):
        return {n: (x + (.2*t if 'wrist' in n else 0), y) for n, (x, y) in base.items()}
    source = {'coordinateSpace': 'normalized_image_xy', 'imageWidth': 640, 'imageHeight': 360,
              'frames': [{'sourceTimeSec': t, 'joints': {n: [x*50/640, y*50/360]
                          for n, (x, y) in joints(t).items()}} for t in [.15, .3, .7, 1.1, 1.8]]}
    motion = {'frames': [{'timeSec': t, 'joints': {n: [x, -y, 0]
                         for n, (x, y) in joints(t).items()}} for t in [0., 1., 2., 3., 4.]]}
    result = fidelity.source_to_motion_pose_fidelity_metrics_for_projection(source, motion,
        projection_reference={'projectionHorizontalVector': [1., 0.], 'mirrored': False})
    assert result['available']
    assert result['comparableFrameCount'] == 5
    assert result['p90JointErrorBodyRatio'] < 1e-10


def test_rejected_source_cycle_does_not_call_expensive_solver(monkeypatch):
    from exercise_motion_pkg import controlled_motion
    def unexpected(*args, **kwargs):
        pytest.fail('Source-rejected cycles must not spend a trajectory-fit attempt')
    monkeypatch.setattr(controlled_motion, '_fit_controlled_motion', unexpected)
    payload = {'loop': {'enabled': True}, 'observedCycleProposals': [], 'sourceCyclePreflight': []}
    result, report = controlled_motion._fit_observed_cycles(payload, timeout_seconds=10)
    assert result is payload
    assert report['reason'] == 'source_cycle_preflight_rejected'


@pytest.mark.parametrize('verified_fit', [False, True])
def test_support_invariant_uses_verified_fit_ownership(tmp_path, monkeypatch, verified_fit):
    from exercise_motion_pkg import bake_and_rank as bake, controlled_motion
    baseline = SimpleNamespace(settings_variant_id='adaptive-baseline', settings_options={},
        export_payload={}, skeleton_path=tmp_path/'baseline.json')
    alternative = SimpleNamespace(settings_variant_id='adaptive-trial',
        settings_options={'lockPlantedFeet': True}, export_payload={'controlledMotionFit': {'applied': True}},
        skeleton_path=tmp_path/'trial.json')
    monkeypatch.setattr(controlled_motion, 'can_reuse_controlled_motion', lambda payload: verified_fit)
    checks = []
    def distal_check(*args):
        checks.append(True)
        return {'passed': False, 'rejectionReasons': ['upstream_pose_changed']}
    monkeypatch.setattr(bake, 'support_lock_baseline_safety_metrics', distal_check)
    kept = bake.prefer_baseline_safe_support_lock_artifacts([baseline, alternative])
    assert (alternative in kept) == verified_fit
    assert bool(checks) == (not verified_fit)


def test_retained_source_window_uses_explicit_time_origin_without_mutation():
    source = {'frames': [{'sourceTimeSec': t, 'joints': {'wrist': [t, 0]}}
                         for t in [0., 10., 10.5, 11., 12.]]}
    original = copy.deepcopy(source)
    motion = {'frames': [{'sourceTimeSec': t, 'timeSec': t-10} for t in [10., 11.]]}
    selected = fidelity.source_pose_reference_for_motion(source, motion)
    assert [f['time'] for f in fidelity._pose_frames(selected, source=True)] == [0., .5, 1.]
    assert source == original


@pytest.mark.parametrize('offset', [0, math.pi/4, math.pi/2, math.pi, 1.7*math.pi])
def test_complete_cycle_is_independent_of_start_phase(offset):
    values = [math.sin(offset + i*2*math.pi/120) for i in range(121)]
    assert complete_repetition(values)[0]


def test_partial_multiple_and_stationary_sequences_are_not_single_cycles():
    for half_cycles in (3, 4, 5):
        values = [math.cos(i*math.pi/120) for i in range(120*half_cycles+1)]
        assert complete_repetition(values, exactly_one=False)[0]
        assert not complete_repetition(values)[0]
    assert not complete_repetition([math.cos(i*math.pi/120) for i in range(121)], exactly_one=False)[0]
    assert not complete_repetition([1.] * 121, exactly_one=False)[0]
    assert not complete_repetition([math.cos(i*math.pi/120) for i in range(121)])[0]
    assert not complete_repetition([math.sin(i*4*math.pi/120) for i in range(121)])[0]
    assert not complete_repetition([1.] * 121)[0]
    # Both extreme bands were visited, but the endpoints neither return nor
    # continue in the same direction. Coverage alone must not pass this.
    assert not complete_repetition([.5, .2, 0., .2, .8, 1., .8])[0]
